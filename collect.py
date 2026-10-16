"""Сбор объявлений об услугах гидроизоляционного инъектирования.

Выдача по релевантности и по дате — отдельные наблюдения, не оценки сделок.
Работает через Playwright. Результаты сохраняются локально в JSON и CSV.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "queries.json"

# Локальный постоянный профиль браузера.
PROFILE = HERE / ".browser-profile"


class AccessRestricted(RuntimeError):
    """Сайт явно запретил доступ: дальнейшие запросы прекращаем."""


def load_listing_page(page, url: str, observation: dict | None = None) -> None:
    if observation is None:
        observation = {}
    observation.update({"requested_url": url, "http_status": None, "response_url": None,
                        "retry_after": None})
    response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
    if response is not None:
        observation.update({"http_status": response.status, "response_url": response.url,
                            "retry_after": response.headers.get("retry-after")})
    # Начальный статус и заголовок могут относиться к промежуточной проверке.
    # Ждём штатное перенаправление сайта без reload/goto и повторных запросов.
    if (response is not None and response.status in (403, 429, 439)) or _blocked(page):
        log("Промежуточная страница проверки. Ждём карточки до 45 секунд…")
    try:
        page.wait_for_selector('[data-marker="item"]', state="visible", timeout=45000)
        observation["listing_ready"] = True
    except Exception:
        observation["listing_ready"] = False
        if _blocked(page):
            raise AccessRestricted("access_restricted_after_wait") from None
        if response is not None and response.status in (403, 429, 439):
            raise AccessRestricted("listing_unavailable_after_restricted_response") from None
        raise


def save_diagnostics(page, directory: Path, observation: dict, exc: Exception) -> Path:
    """Сохраняем только локально: без cookies, заголовков авторизации и HTML."""
    directory.mkdir(parents=True, exist_ok=True)
    stem = "diagnostic-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    data = {**observation, "at": datetime.now().isoformat(timespec="seconds"),
            "error_type": type(exc).__name__, "error": str(exc)[:1500]}
    for key, getter in (("final_url", lambda: page.url), ("title", page.title)):
        try:
            data[key] = getter()
        except Exception as error:
            data[key] = None
            data[key + "_error"] = str(error)[:200]
    screenshot = directory / (stem + ".png")
    try:
        page.screenshot(path=str(screenshot), full_page=False, timeout=10000)
        data["screenshot"] = screenshot.name
    except Exception as error:
        data["screenshot_error"] = str(error)[:300]
    path = directory / (stem + ".json")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Диагностика: {path}")
    return path


def inspect_browser() -> None:
    if not sys.stdin.isatty():
        log("Терминал неинтерактивный: ожидание осмотра пропущено.")
        return
    try:
        input("Осмотрите страницу в Chromium. Enter — закрыть браузер и завершить. Повторного запроса не будет. ")
    except (EOFError, KeyboardInterrupt):
        pass


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
        title = page.title().lower()
        return "доступ ограничен" in title or "доступ временно заблокирован" in title
    except Exception:
        return False


def write_checkpoint(path: Path | None, state: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def wait_until(timestamp: float) -> None:
    remaining = timestamp - time.time()
    if remaining > 0:
        log(f"Следующий запрос не раньше чем через {remaining / 60:.1f} мин. Ctrl+C — остановить.")
    while timestamp > time.time():
        time.sleep(min(30, timestamp - time.time()))


def collect(cfg: dict, pages: int, checkpoint: Path | None = None,
            resume: bool = False, interval: float = 900,
            diagnostics_dir: Path | None = None, diagnose: bool = False) -> dict:
    from playwright.sync_api import sync_playwright

    modes = [("ranked", "")]
    if cfg.get("collect_by_date", True):
        modes.append(("by_date", "&s=104"))
    for lo, hi in cfg.get("price_bands") or []:
        modes.append((f"band_{lo}_{hi or 'plus'}", f"&s=104&pmin={lo}" + (f"&pmax={hi}" if hi else "")))
    plan = [(mode, suffix, region, query) for mode, suffix in modes
            for region in cfg["regions"] for query in cfg["queries"]]
    signature = hashlib.sha256(json.dumps([plan, pages, cfg.get("category_path")],
                                          ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    state = {"signature": signature, "block": 0, "page": 1, "last_request": 0,
             "result": {"collected_at": datetime.now().isoformat(timespec="seconds"), "queries": []}}
    if resume:
        if checkpoint is None:
            raise ValueError("Для продолжения нужен checkpoint")
        state = json.loads(checkpoint.read_text(encoding="utf-8"))
        if state.get("signature") != signature:
            raise ValueError("План изменился: восстановите queries.json и --pages или начните новый сбор")
    result = state["result"]
    result.pop("stop_reason", None)
    result.pop("queries_not_run", None)
    result["queries_planned"] = len(plan)
    if state["block"] >= len(plan):
        return result

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

        try:
            while state["block"] < len(plan):
                index = state["block"]
                mode, suffix, region, query = plan[index]
                if len(result["queries"]) <= index:
                    result["queries"].append({"query": query, "region": region["name"],
                        "region_slug": region["slug"], "mode": mode, "items": [],
                        "total": None, "status": "partial", "errors": [], "our_positions": {}})
                block = result["queries"][index]
                page_no = state["page"]
                wait_until(state["last_request"] + interval if state["last_request"] else 0)
                url = (f'https://www.avito.ru/{region["slug"]}/'
                       f'{cfg.get("category_path", "predlozheniya_uslug")}'
                       f'?q={urllib.parse.quote(query)}&p={page_no}{suffix}')
                state["last_request"] = time.time()
                write_checkpoint(checkpoint, state)
                observation = {}
                try:
                    load_listing_page(page, url, observation)
                    data = page.evaluate(EXTRACT_JS)
                except Exception as exc:
                    reason = "access_restricted" if isinstance(exc, AccessRestricted) else "page_unavailable"
                    block["errors"].append({"page": page_no, "reason": reason, "url": url,
                                            "at": datetime.now().isoformat(timespec="seconds")})
                    block["status"] = "partial" if block["items"] else "failed"
                    result["stop_reason"] = reason
                    result["queries_not_run"] = len(plan) - len(result["queries"])
                    if diagnostics_dir is not None:
                        try:
                            path = save_diagnostics(page, diagnostics_dir, observation, exc)
                            block["errors"][-1]["diagnostic_file"] = str(path)
                        except Exception as diagnostic_error:
                            log(f"Не удалось сохранить диагностику: {diagnostic_error}")
                    write_checkpoint(checkpoint, state)
                    if diagnose and not cfg.get("headless", False):
                        inspect_browser()
                    log(f"Остановлено: {reason}. Прогресс сохранён; автоматических повторов нет.")
                    return result
                batch = enrich_items(data.get("items") or [])
                existing = {item["id"] for item in block["items"]}
                fresh = []
                for item in batch:
                    if item["id"] not in existing:
                        existing.add(item["id"])
                        item["position"] += (page_no - 1) * 50
                        fresh.append(item)
                block["items"].extend(fresh)
                block["total"] = data.get("total")
                block["our_positions"] = {i["id"]: i["position"] for i in block["items"]
                                          if i["id"] in {str(x) for x in cfg.get("our_item_ids", [])}}
                block["errors"] = []
                block["last_success_at"] = datetime.now().isoformat(timespec="seconds")
                log(f"{query} / {region['name']} [{mode}] стр.{page_no}: {len(batch)} карточек")
                if page_no >= pages or len(batch) < 20 or not fresh:
                    block["status"] = "ok"
                    state["block"] += 1
                    state["page"] = 1
                else:
                    block["status"] = "partial"
                    state["page"] += 1
                write_checkpoint(checkpoint, state)
        finally:
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
    ap.add_argument("--interval", type=float, default=900, help="секунд между началами запросов; по умолчанию 900")
    ap.add_argument("--resume", action="store_true", help="продолжить из checkpoint")
    ap.add_argument("--checkpoint", type=Path, help="по умолчанию output-dir/progress.json")
    ap.add_argument("--pilot", action="store_true", help="один запрос, первый регион, одна страница, только ranked")
    ap.add_argument("--query", help="запрос для --pilot; по умолчанию первый из queries.json")
    ap.add_argument("--diagnose", action="store_true", help="оставить видимый браузер открытым при ошибке до Enter")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--dry", action="store_true", help="совместимость: результаты всегда локальные")
    args = ap.parse_args()
    if args.pages < 1 or args.repeat < 1 or args.gap < 0 or not 1 <= args.interval < float("inf"):
        ap.error("pages и repeat должны быть положительными; gap >= 0; interval >= 1")
    if args.query and not args.pilot:
        ap.error("--query применяется вместе с --pilot")
    if args.query is not None and not args.query.strip():
        ap.error("--query не должен быть пустым")
    cfg = load_config(args.config)
    if args.pilot:
        if args.repeat != 1:
            ap.error("--pilot выполняет только один запрос; уберите --repeat")
        cfg = {**cfg, "queries": [args.query.strip() if args.query else cfg["queries"][0]],
               "regions": cfg["regions"][:1], "collect_by_date": False, "price_bands": []}
        args.pages = 1
        if args.output_dir == HERE / "results" and not args.resume and not args.checkpoint:
            args.output_dir = HERE / "results" / ("pilot-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    if args.headless:
        cfg["headless"] = True
    if args.diagnose and cfg.get("headless", False):
        ap.error("--diagnose требует видимого браузера: уберите --headless и headless: true из настроек")
    for run in range(args.repeat):
        if run:
            time.sleep(args.gap * 60)
        checkpoint = args.checkpoint or args.output_dir / "progress.json"
        if run == 0 and checkpoint.exists() and not args.resume:
            ap.error("Checkpoint уже существует: используйте --resume либо другой --output-dir")
        payload = collect(cfg, args.pages, checkpoint, args.resume and run == 0, args.interval,
                          args.output_dir / "diagnostics", args.diagnose)
        paths = save_results(payload, args.output_dir)
        log("Сохранено: " + ", ".join(str(p) for p in paths))
        if any(b.get("status") != "ok" for b in payload["queries"]):
            log("Есть ошибки загрузки: это не означает отсутствие объявлений; см. JSON")
            raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Остановлено пользователем. Если есть progress.json, продолжите с --resume.")
        raise SystemExit(130)
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("playwright"):
            log("Playwright не установлен. Запустите «Установить.command» или установите requirements.txt.")
            raise SystemExit(1)
        raise
    except (ValueError, OSError) as exc:
        log(f"Ошибка настроек или файлов: {exc}")
        raise SystemExit(1)
