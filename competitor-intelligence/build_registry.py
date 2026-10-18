#!/usr/bin/env python3
"""Build a standalone competitor research registry from Avito exports.

The script does not modify or depend on the browser extension. It ranks seller
profiles, extracts public business clues already present in saved listings and
creates an editable CSV plus an HTML research queue with links to public sources.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote_plus, urlparse


MANUAL_FIELDS = [
    "identity_status",
    "match_confidence",
    "legal_name",
    "legal_form",
    "inn",
    "ogrn_or_ogrnip",
    "company_status",
    "registered_at",
    "okved",
    "website_confirmed",
    "yandex_maps_card",
    "two_gis_card",
    "business_contact_public",
    "service_geography_confirmed",
    "revenue_latest_rub",
    "profit_latest_rub",
    "reporting_year",
    "tender_contracts_found",
    "evidence_urls",
    "analyst_notes",
    "last_checked",
]


def clean(value: object) -> str:
    return str(value or "").strip()


def number(value: object) -> float:
    try:
        return float(clean(value).replace(",", "."))
    except ValueError:
        return 0.0


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def percentile_map(rows: list[dict[str, str]], field: str) -> dict[str, float]:
    ordered = sorted((number(row.get(field)), row["seller_key"]) for row in rows)
    if len(ordered) <= 1:
        return {key: 1.0 for _, key in ordered}
    result: dict[str, float] = {}
    for index, (_, key) in enumerate(ordered):
        result[key] = index / (len(ordered) - 1)
    return result


def seller_key(row: dict[str, str]) -> str:
    return clean(row.get("seller_url")) or f"seller:{clean(row.get('seller'))}"


def normalize_seller_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Accept both enriched seller metrics and the extension's seller CSV."""
    normalized = []
    for source in rows:
        row = dict(source)
        row.setdefault("core_listings", clean(row.get("listing_count")))
        row.setdefault("cities", "")
        row.setdefault("city_list", "")
        row.setdefault("first_page_slot_share_pct", "0")
        row.setdefault("observed_view_share_pct", "0")
        row.setdefault("promoted_listings", "")
        row.setdefault("rating", "")
        row.setdefault("reviews", "")
        normalized.append(row)
    return normalized


def rank_sellers(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    prepared = []
    for row in rows:
        item = dict(row)
        item["seller_key"] = seller_key(item)
        prepared.append(item)

    visibility = percentile_map(prepared, "first_page_slot_share_pct")
    attention = percentile_map(prepared, "observed_view_share_pct")
    inventory_rows = [dict(row, inventory_log=str(math.log1p(number(row.get("core_listings"))))) for row in prepared]
    inventory = percentile_map(inventory_rows, "inventory_log")

    by_visibility = {row["seller_key"] for row in sorted(prepared, key=lambda row: number(row.get("first_page_slot_share_pct")), reverse=True)[:10]}
    by_attention = {row["seller_key"] for row in sorted(prepared, key=lambda row: number(row.get("observed_view_share_pct")), reverse=True)[:10]}
    by_inventory = {row["seller_key"] for row in sorted(prepared, key=lambda row: number(row.get("core_listings")), reverse=True)[:10]}

    for row in prepared:
        key = row["seller_key"]
        row["priority_score"] = round(100 * (0.45 * visibility[key] + 0.35 * attention[key] + 0.20 * inventory[key]), 1)
        reasons = []
        if key in by_visibility:
            reasons.append("топ-10 видимости")
        if key in by_attention:
            reasons.append("топ-10 накопленных просмотров")
        if key in by_inventory:
            reasons.append("топ-10 числа объявлений")
        row["priority_reasons"] = "; ".join(reasons) or "сводный рейтинг"
    return sorted(prepared, key=lambda row: (number(row["priority_score"]), number(row.get("core_listings"))), reverse=True)


def load_listing_evidence(path: Path | None) -> dict[str, dict[str, object]]:
    if not path:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    grouped: dict[str, dict[str, object]] = defaultdict(lambda: {"texts": [], "titles": [], "profile_types": []})
    for listing in data.get("listings", {}).values():
        detail = listing.get("detail") or {}
        card = listing.get("card") or {}
        url = clean(detail.get("sellerURL") or card.get("sellerURL"))
        if not url:
            continue
        bucket = grouped[url]
        bucket["titles"].append(clean(detail.get("title") or card.get("title")))
        for value in (
            detail.get("description"),
            detail.get("parametersText"),
            detail.get("rawText"),
            card.get("rawText"),
        ):
            if value:
                bucket["texts"].append(str(value))
    return grouped


def extract_evidence(name: str, seller_url: str, bucket: dict[str, object] | None) -> dict[str, str]:
    texts = list((bucket or {}).get("texts", []))
    titles = [title for title in (bucket or {}).get("titles", []) if title]
    text = "\n".join(texts)
    compact = re.sub(r"[ \t]+", " ", text)

    types = Counter()
    for label in ("Компания", "Частный исполнитель", "Самозанятый"):
        types[label] = len(re.findall(rf"(?im)^\s*{re.escape(label)}\s*$", text))
    explicit_ip = bool(re.match(r"(?i)^\s*ИП(?:[.\s]|$)", name))
    profile_type = "ИП" if explicit_ip else (types.most_common(1)[0][0] if types and types.most_common(1)[0][1] else "не распознано")

    legal_hints = []
    if re.match(r"(?i)^\s*(?:ООО|ИП|АО|ПАО)(?:[.\s]|$)", name):
        legal_hints.append(name)
    for match in re.findall(r"(?im)^\s*((?:ООО|ИП|АО|ПАО)\s+[А-ЯЁA-Z][^\n,.!?]{2,80})", text):
        if "КЕХ еКоммерц" not in match and match not in legal_hints:
            legal_hints.append(match.strip())

    inns = sorted(set(re.findall(r"(?i)\bИНН\s*[:№]?\s*(\d{10}|\d{12})\b", compact)))
    years = [int(year) for year in re.findall(r"На Авито\s+[cс]\s+(\d{4})\s+года", text, re.I)]
    profile_ads = [int(value.replace(" ", "")) for value in re.findall(r"(\d[\d ]*)\s+объявлен(?:ие|ия|ий)\s+пользователя", text, re.I)]
    min_orders = sorted(set(re.findall(r"Минимальная сумма заказа:\s*([^\n]+)", text, re.I)))

    contact_people = []
    for match in re.findall(r"Контактное лицо\s*\n+\s*([^\n]{2,80})", text, re.I):
        candidate = match.strip()
        if candidate not in contact_people and not re.search(r"телефон|сообщение", candidate, re.I):
            contact_people.append(candidate)

    slug = urlparse(seller_url).path.rstrip("/").split("/")[-1] if seller_url else ""
    website_candidate = ""
    if re.fullmatch(r"[a-z0-9-]+\.(?:ru|рф|com|pro)", slug, re.I):
        website_candidate = f"https://{slug}"

    theme_patterns = {
        "подвалы/цоколи": r"подвал|цокол",
        "трещины/бетон": r"трещин|бетон",
        "фундаменты/грунты": r"фундамент|грунт",
        "швы": r"шов",
        "активные течи": r"активн\w*\s+(?:теч|протеч)|устранен\w*\s+(?:теч|протеч)",
        "паркинги": r"паркинг",
        "бассейны": r"бассейн",
        "усиление": r"усилен",
    }
    title_text = "\n".join(titles)
    themes = [label for label, pattern in theme_patterns.items() if re.search(pattern, title_text, re.I)]

    return {
        "avito_profile_type": profile_type,
        "avito_since_year": str(min(years)) if years else "",
        "avito_public_profile_ads": str(max(profile_ads)) if profile_ads else "",
        "avito_contact_person": "; ".join(contact_people[:3]),
        "legal_name_hint": "; ".join(legal_hints[:3]),
        "inn_hint": "; ".join(inns),
        "website_candidate": website_candidate,
        "website_candidate_basis": "домен в URL бренда Авито" if website_candidate else "",
        "minimum_order_hints": "; ".join(min_orders[:5]),
        "service_themes_from_titles": "; ".join(themes),
        "sample_titles": " | ".join(dict.fromkeys(titles[:8])),
    }


def search_links(name: str, legal_hint: str, inn_hint: str) -> dict[str, str]:
    query = legal_hint or name
    exact = f'"{query}" гидроизоляция'
    legal_query = inn_hint or query
    return {
        "web_search": f"https://yandex.ru/search/?text={quote_plus(exact)}",
        "maps_search": f"https://yandex.ru/maps/?text={quote_plus(query + ' гидроизоляция')}",
        "two_gis_search": f"https://2gis.ru/moscow/search/{quote_plus(query + ' гидроизоляция')}",
        "rusprofile_search": f"https://yandex.ru/search/?text={quote_plus('site:rusprofile.ru ' + legal_query)}",
        "checko_search": f"https://yandex.ru/search/?text={quote_plus('site:checko.ru ' + legal_query)}",
        "fns_registry": "https://egrul.nalog.ru/index.html",
        "procurement_search": "https://zakupki.gov.ru/epz/order/extendedsearch/results.html?searchString=" + quote_plus(query),
    }


def preserve_manual(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    return {seller_key(row): row for row in read_csv(path)}


def write_registry(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_html(path: Path, rows: list[dict[str, str]]) -> None:
    cards = []
    for row in rows:
        links = search_links(row["seller"], row["legal_name_hint"], row["inn_hint"])
        anchors = " ".join(
            f'<a href="{html.escape(url)}" target="_blank" rel="noreferrer">{html.escape(label)}</a>'
            for label, url in (
                ("Поиск", links["web_search"]),
                ("Яндекс Карты", links["maps_search"]),
                ("2ГИС", links["two_gis_search"]),
                ("Rusprofile", links["rusprofile_search"]),
                ("Checko", links["checko_search"]),
                ("ФНС", links["fns_registry"]),
                ("Закупки", links["procurement_search"]),
            )
        )
        clues = []
        for label, field in (
            ("Тип", "avito_profile_type"),
            ("Юр. подсказка", "legal_name_hint"),
            ("ИНН", "inn_hint"),
            ("Кандидат сайта", "website_candidate"),
            ("Темы", "service_themes_from_titles"),
        ):
            if row.get(field):
                clues.append(f"<li><b>{html.escape(label)}:</b> {html.escape(row[field])}</li>")
        cards.append(
            f"""<article><h2>{row['research_priority']}. {html.escape(row['seller'])}</h2>
            <p><b>Приоритет:</b> {row['priority_score']} · {html.escape(row['priority_reasons'])}</p>
            <p><a href="{html.escape(row['seller_url'])}" target="_blank">Профиль Авито</a> {anchors}</p>
            <ul>{''.join(clues)}</ul>
            <p class="muted">Объявлений ядра: {row.get('core_listings','')} · гео: {row.get('cities','')} ·
            доля слотов первой страницы: {row.get('first_page_slot_share_pct','')}% ·
            доля накопленных просмотров: {row.get('observed_view_share_pct','')}%</p></article>"""
        )
    document = f"""<!doctype html><html lang="ru"><meta charset="utf-8">
    <title>Очередь исследования конкурентов</title><style>
    body{{font:16px/1.45 system-ui,sans-serif;max-width:1050px;margin:32px auto;padding:0 20px;background:#f5f7f8;color:#172731}}
    article{{background:white;border:1px solid #d8e1e5;border-radius:14px;padding:18px 22px;margin:16px 0}}
    h1{{margin-bottom:4px}} h2{{margin:0 0 8px}} a{{display:inline-block;margin:3px 10px 3px 0;color:#087b75}}
    .muted{{color:#5d707b}} code{{background:#eef2f3;padding:2px 5px}}</style>
    <h1>Очередь исследования конкурентов</h1>
    <p>Сначала подтвердите организацию по ИНН/ОГРН или нескольким независимым признакам. Записывайте результат в <code>competitors.csv</code>.</p>
    {''.join(cards)}</html>"""
    path.write_text(document, encoding="utf-8")


def write_report(path: Path, rows: list[dict[str, str]]) -> None:
    recognized_types = Counter(row["avito_profile_type"] for row in rows)
    legal_hints = sum(bool(row["legal_name_hint"]) for row in rows)
    site_candidates = sum(bool(row["website_candidate"]) for row in rows)
    lines = [
        "# Реестр проверки конкурентов",
        "",
        f"В очереди: **{len(rows)} профилей**. Юридическая подсказка уже найдена у **{legal_hints}**, кандидат сайта — у **{site_candidates}**.",
        "",
        "Типы профилей, распознанные в сохранённых карточках: " + ", ".join(f"{key}: {value}" for key, value in recognized_types.most_common()) + ".",
        "",
        "| № | Профиль | Приоритет | Причина | Объявления | Гео | Юр. подсказка |",
        "|---:|---|---:|---|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['research_priority']} | {row['seller']} | {row['priority_score']} | {row['priority_reasons']} | "
            f"{row.get('core_listings','')} | {row.get('cities','')} | {row['legal_name_hint'] or '—'} |"
        )
    lines += [
        "",
        "## Правило подтверждения",
        "",
        "- **Высокая уверенность:** совпал ИНН/ОГРН либо реквизиты прямо связаны с профилем или официальным сайтом.",
        "- **Средняя:** совпали минимум три независимых признака — бренд, деловой телефон, география, домен или контактное лицо.",
        "- **Низкая:** совпало только название или имя; такое соответствие нельзя использовать в выводах.",
        "",
        "Финансовые показатели ООО могут включать другие направления бизнеса, а по ИП публичной выручки обычно нет. Источник и дату каждого факта нужно сохранять в полях `evidence_urls` и `last_checked`.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seller-metrics", type=Path, required=True, help="CSV с агрегатами продавцов")
    parser.add_argument("--research-json", type=Path, help="JSON-выгрузка расширения для извлечения подсказок")
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    ranked = rank_sellers(normalize_seller_rows(read_csv(args.seller_metrics)))[: max(1, args.limit)]
    evidence = load_listing_evidence(args.research_json)
    registry_path = args.output_dir / "competitors.csv"
    old = preserve_manual(registry_path)
    output = []
    for index, seller in enumerate(ranked, 1):
        key = seller["seller_key"]
        row = {
            "research_priority": str(index),
            "priority_score": str(seller["priority_score"]),
            "priority_reasons": seller["priority_reasons"],
            "seller": clean(seller.get("seller")),
            "seller_url": clean(seller.get("seller_url")),
            "core_listings": clean(seller.get("core_listings")),
            "cities": clean(seller.get("cities")),
            "city_list": clean(seller.get("city_list")),
            "first_page_slot_share_pct": clean(seller.get("first_page_slot_share_pct")),
            "observed_view_share_pct": clean(seller.get("observed_view_share_pct")),
            "promoted_listings": clean(seller.get("promoted_listings")),
            "rating": clean(seller.get("rating")),
            "reviews": clean(seller.get("reviews")),
            **extract_evidence(clean(seller.get("seller")), clean(seller.get("seller_url")), evidence.get(clean(seller.get("seller_url")))),
        }
        previous = old.get(key, {})
        row.update({field: clean(previous.get(field)) for field in MANUAL_FIELDS})
        output.append(row)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_registry(registry_path, output)
    write_html(args.output_dir / "research-links.html", output)
    write_report(args.output_dir / "README.md", output)
    print(f"Создано профилей: {len(output)}")
    print(registry_path.resolve())
    print((args.output_dir / "research-links.html").resolve())


if __name__ == "__main__":
    main()
