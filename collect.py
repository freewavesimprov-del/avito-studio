"""Сбор объявлений об услугах гидроизоляционного инъектирования.

Выдача по релевантности и по дате — отдельные наблюдения, не оценки сделок.
Работает через Playwright. результаты сохраняются локально в JSON и CSV.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "queries.json"

# Пауза между страницами. Ходим медленнее человека: задача не выкачать рынок,
# а раз в неделю снять срез, оставшись незаметными.
PAUSE = (7.0, 14.0)

# Профиль браузера храним между запусками: куки и история делают нас
# возвращающимся посетителем, а не новым безликим клиентом при каждом заходе.
# Без профиля защита срабатывает уже на втором запросе подряд.
PROFILE = HERE / ".browser-profile"

# Сколько ждать, если всё-таки поймали ограничение доступа.
COOLDOWN = 90


def log(msg: str) -> None:
    print(f"{datetime.now():%H:%M:%S}  {msg}", flush=True)


def load_config(path: Path = CONFIG) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    if not cfg.get("queries") or not cfg.get("regions"):
        raise ValueError("Нужны непустые queries и regions")
    if not isinstance(cfg.get("headless", False), bool):
        raise ValueError("headless должен быть true или false")
    return cfg


def service_metadata(item: dict) -> dict:
    text = (item.get("title", "") + " " + item.get("description", "")).lower().replace("ё", "е")
    injection = bool(re.search(r"инъек|иньек|инжект", text))
    waterproof = bool(re.search(r"гидроизол|теч[ьи]|протеч|подвал|фундамент|трещин|швов|шва", text))
    goods = bool(re.search(r"аренда|продаж[аи]|купить|оборудован|насос|пакер|инъектор", text))
    return {
        "relevance": "equipment_or_materials" if goods else "injection" if injection and waterproof else "related" if waterproof else "uncertain",
        "price_unit": item.get("price_unit") or "unspecified",
        "price_from": bool(item.get("price_from")),
    }


def enrich_items(items: list[dict]) -> list[dict]:
    for item in items:
        item.update(service_metadata(item))
    return items


# --- Сбор --------------------------------------------------------------------

# Данные берём из отрендеренной страницы: внутренний JSON-эндпоинт Авито
# требует подбора параметров и молча отдаёт не ту выдачу, а разметка карточек
# стабильна и проверяема глазами.
EXTRACT_JS = r"""
() => {
  const items = [...document.querySelectorAll('[data-marker="item"]')];
  let total = null;
  const counter = document.querySelector('[data-marker="page-title/count"]');
  if (counter) total = parseInt(counter.textContent.replace(/\D/g, ''), 10);
  if (!total) {
    const m = document.body.innerText.match(/([\d\s ]{3,})\s*объявлени/);
    if (m) total = parseInt(m[1].replace(/\D/g, ''), 10);
  }
  const rows = items.map((el, i) => {
    const text = el.innerText;
    const priceEl = el.querySelector('[itemprop="price"]');

    // Продавца опознаём по ссылке на профиль: она стабильнее имени, которое
    // склеено с рейтингом в одном текстовом узле («Татьяна5,05,0·38 отзывов»).
    let sellerId = null, sellerName = null;
    for (const a of el.querySelectorAll('a[href]')) {
      const h = a.getAttribute('href') || '';
      if (/\/(user|brands)\//.test(h)) {
        sellerId = h.split('?')[0];
        const raw = a.textContent.trim();
        // отрезаем всё начиная с рейтинга: цифра с запятой или скобка отзывов
        sellerName = raw.split(/\d+[,.]\d|\(|·/)[0].trim() || null;
        break;
      }
    }

    // число фото Авито пишет прямо на карточке; счёт <img> — запасной вариант
    const photoText = (text.match(/(\d+)\s*фото/) || [])[1];
    const images = photoText ? parseInt(photoText, 10) : (el.querySelectorAll('img').length || null);

    let reviews = null;
    const rev = text.match(/·\s*(\d[\d\s ]*)\s*отзыв|\((\d[\d\s ]*)\)/);
    if (rev) reviews = parseInt((rev[1] || rev[2]).replace(/\D/g, ''), 10);

    const link = el.querySelector('[data-marker="item-title"]') || [...el.querySelectorAll('a[href]')].find(a => /_\d+(?:\?|$)/.test(a.getAttribute('href') || ''));
    const href = link ? link.getAttribute('href') : '';
    const idm = href.match(/_(\d+)(?:\?|$)/);
    const nameEl = el.querySelector('[itemprop="name"]');
    return {
      id: idm ? idm[1] : null,
      title: nameEl ? nameEl.textContent.trim().replace(/\s+/g, ' ') : '',
      price: priceEl && Number.isFinite(parseFloat(priceEl.getAttribute('content'))) ? parseFloat(priceEl.getAttribute('content')) : null,
      description: (el.querySelector('[data-marker="item-specific-params"], [data-marker="item-description"]') || {}).textContent || '',
      price_text: (priceEl && priceEl.parentElement ? priceEl.parentElement.innerText : ''),
      price_from: /(?:^|\s)от\s*\d/i.test(text),
      price_unit: /(?:м²|м2|кв\.?\s*м)/i.test(text) ? 'm2' :
                  /(?:пог\.?\s*м|погонн)/i.test(text) ? 'linear_m' :
                  /за\s*час/i.test(text) ? 'hour' :
                  /за\s*выезд/i.test(text) ? 'visit' : 'unspecified',
      seller: sellerName,
      seller_id: sellerId,
      reviews,
      images,
      delivery: /Доставка/i.test(text),
      promoted: /Продвинуто|Реклама/i.test(text),
      position: i + 1,
      url: href.split('?')[0],
    };
  }).filter(r => r.id);
  return { total, items: rows };
}
"""


def _blocked(page) -> bool:
    try:
        return "Доступ ограничен" in page.title()
    except Exception:
        return False


def collect(cfg: dict, pages: int) -> dict:
    from playwright.sync_api import sync_playwright

    ours = {str(x) for x in (cfg.get("our_item_ids") or [])}
    result = {"collected_at": datetime.now().isoformat(timespec="seconds"),
              "queries": []}

    with sync_playwright() as pw:
        # Режим браузера задаётся в queries.json. Ограничения доступа не обходим.
        ctx = pw.chromium.launch_persistent_context(
            str(PROFILE),
            headless=cfg.get("headless", False),
                executable_path=os.environ.get("COLLECTOR_BROWSER") or None,
            locale="ru-RU",
            viewport={"width": 1440, "height": 900},
            
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # Сортировки храним отдельно; они не гарантируют случайную выборку.
        modes: list[tuple[str, str]] = [("ranked", "")]
        if cfg.get("collect_by_date", True):
            modes.append(("by_date", "&s=104"))
        for lo, hi in cfg.get("price_bands") or []:
            band = f"&pmin={lo}" + (f"&pmax={hi}" if hi else "")
            modes.append((f"band_{lo}_{hi or 'plus'}", "&s=104" + band))

        for mode, sort_suffix in modes:
          for region in cfg["regions"]:
            for query in cfg["queries"]:
                items: list[dict] = []
                total = None
                errors = []
                for page_no in range(1, pages + 1):
                    url = (f'https://www.avito.ru/{region["slug"]}/'
                           f'{cfg.get("category_path", "predlozheniya_uslug")}'
                           f'?q={urllib.parse.quote(query)}&p={page_no}{sort_suffix}')
                    ok = False
                    for attempt in (1, 2):
                        try:
                            page.goto(url, wait_until="domcontentloaded", timeout=45000)
                            page.wait_for_selector('[data-marker="item"]', timeout=25000)
                            ok = True
                            break
                        except Exception as exc:
                            if _blocked(page) and attempt == 1:
                                log(f'  … ограничение доступа, ждём {COOLDOWN} с')
                                time.sleep(COOLDOWN)
                                continue
                            log(f'  !! {query} / {region["name"]} стр.{page_no}: {str(exc)[:70]}')
                            break
                    if not ok:
                        errors.append({"page": page_no, "reason": "page_unavailable"})
                        break

                    data = page.evaluate(EXTRACT_JS)
                    if total is None:
                        total = data.get("total")
                    batch = enrich_items(data.get("items") or [])
                    existing = {i["id"] for i in items}
                    fresh = [i for i in batch if i["id"] not in existing]
                    for item in fresh:
                        item["position"] += (page_no - 1) * 50
                    if batch and not fresh:
                        break
                    items.extend(fresh)
                    log(f'  {query} / {region["name"]} стр.{page_no}: '
                        f'{len(batch)} карточек, всего в категории {total}')
                    if len(batch) < 20:
                        break
                    time.sleep(random.uniform(*PAUSE))

                positions = {i["id"]: i["position"] for i in items if i["id"] in ours}
                result["queries"].append({
                    "query": query, "region": region["name"],
                    "region_slug": region["slug"], "total": total,
                    "mode": mode,
                    "our_positions": positions, "items": items,
                    "status": "partial" if errors and items else "failed" if errors else "ok",
                    "errors": errors,
                })
                log(f'  [{mode}] {query} / {region["name"]}: снято {len(items)}')
                time.sleep(random.uniform(*PAUSE))

        ctx.close()
    return result


def save_results(payload: dict, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = "snapshot-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    snapshot = output_dir / (stem + ".json")
    snapshot.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    table = output_dir / (stem + ".csv")
    fields = ["query", "region", "mode", "status", "id", "title", "description", "price",
              "price_text", "price_unit", "price_from", "relevance", "seller", "seller_id",
              "position", "promoted", "url"]
    with table.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for block in payload["queries"]:
            for item in block["items"]:
                row = {**item, **{k: block.get(k) for k in ("query", "region", "mode", "status")}}
                row["url"] = urllib.parse.urljoin("https://www.avito.ru", row.get("url") or "")
                # Не позволяем тексту объявления стать формулой в Excel.
                for key, value in row.items():
                    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                        row[key] = "'" + value
                writer.writerow(row)
    return snapshot, table


def main() -> None:
    ap = argparse.ArgumentParser(description="Локальный сбор услуг гидроизоляционного инъектирования")
    ap.add_argument("--config", type=Path, default=CONFIG)
    ap.add_argument("--pages", type=int, default=2)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--gap", type=int, default=60, help="минут между обходами")
    ap.add_argument("--output-dir", type=Path, default=HERE / "results")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--dry", action="store_true", help="совместимость: результаты всегда локальные")
    args = ap.parse_args()
    if args.pages < 1 or args.repeat < 1 or args.gap < 0:
        ap.error("pages и repeat должны быть положительными; gap >= 0")
    cfg = load_config(args.config)
    if args.headless:
        cfg["headless"] = True
    for run in range(args.repeat):
        if run:
            time.sleep(args.gap * 60)
        payload = collect(cfg, args.pages)
        paths = save_results(payload, args.output_dir)
        log("Сохранено: " + ", ".join(str(p) for p in paths))
        if any(b.get("status") != "ok" for b in payload["queries"]):
            log("Есть ошибки загрузки: это не означает отсутствие объявлений; см. JSON")
            raise SystemExit(2)


if __name__ == "__main__":
    main()
