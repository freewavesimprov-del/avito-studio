#!/usr/bin/env python3
"""Build relevance reports and importable cleaned Avito research backups."""

from __future__ import annotations

import argparse
import csv
import json
import re
import uuid
from collections import Counter, defaultdict
from pathlib import Path


SPACE = re.compile(r"\s+")
INJECTION = re.compile(r"инъекц|инъектир|инъектирован|инъекции|инжектир|иъектир", re.I)
CONSTRUCTION = re.compile(
    r"гидроизол|фундамент|подвал|паркинг|бетон|трещин|шв|кладк|стен|грунт|"
    r"протеч|теч[ьи]|конструкц|цокол|кирпич|деформац|отсечн|герметиз",
    re.I,
)
RELATED_TITLE = re.compile(
    r"гидроизол|фундамент|подвал|паркинг|трещин|шв|кладк|бетон|цокол|"
    r"протеч|теч[ьи]|усилен|укрепл|ремонт конструкц",
    re.I,
)
WATERPROOF_TITLE = re.compile(r"гидроизол|гироизол|устранен\w* (?:протеч|теч)|герметизац\w* трещ|течет подвал|защит\w* от воды", re.I)
SERVICE = re.compile(
    r"услуг|работ|ремонт|устран|монтаж|устройств|выполн|под ключ|выезд|замер|"
    r"бригада|мастер|гарант|цена за|стоимость|укрепл|усилен|герметизац",
    re.I,
)
SERVICE_PARAMS = re.compile(
    r"работы:|чем занимается исполнитель|доступно мастеров|опыт в сфере|"
    r"гарантия на работу|работа по договору|минимальный объем работ|"
    r"бесплатный выезд на замер|исполнитель закупает материалы",
    re.I,
)
PRODUCT_PARAMS = re.compile(
    r"характеристики|состояние:\s*(?:новое|б/у)|доступность:\s*в наличии|"
    r"тип гидроизоляции:|бренд:|подходит для:",
    re.I,
)
SERVICE_OBJECT_TITLE = re.compile(
    r"гидроизол\w* (?:фундамент|подвал|паркинг|цокол|кровл|кры|гараж|бассейн|"
    r"бетон|плит|стен|шв)|(?:фундамент|подвал|паркинг|цокол|кровл|кры|гараж|"
    r"бассейн|бетон|плит|стен|шв).*гидроизол",
    re.I,
)
PRODUCT = re.compile(
    r"\b(?:насос|аппарат|оборудован|пакер|смол[аы]|составы?|материалы?|купить|"
    r"продам|продажа|аренда|дилер\w*|кг|мешок|рулон|технониколь|кнауф|флэхендихт|"
    r"стеклоизол|унифлекс|линокром|икопал|рубитекс|гидроизол хпп|"
    r"пенетрон адмикс|ceresit|glims|safety base|сейфити бейз)\b",
    re.I,
)
ACTION_TITLE = re.compile(r"услуг|работ|ремонт|монтаж|устройств|нанесен|напылен|под ключ|выполн", re.I)
HARD_NOISE = re.compile(
    r"сантех|отоплен|тепл\w* пол|водоснаб|водоочист|очистк\w* вод|фильтр\w* вод|"
    r"защит\w* от протеч|neptun|нептун|gidrolock|tuya|zigbee|умный дом|"
    r"видеонаблюд|домофон|электрик|автоматик\w* кот|посудомоеч|стиральн|"
    r"косметолог|подкожн|инфузи|инъекц\w* губ|инъекц\w* лиц|"
    r"утеплен|ппу|пеноизол|эковат|"
    r"водосток|кессон|скважин|септик|буронабивн|сваи|отмостк|венц|подъем дома|"
    r"строительств\w* дом|фундамент под ключ|бетонные работы|площадк\w* под авто|"
    r"поиск\w*.*утеч|скрыт\w*.*утеч|утечк\w* воды",
    re.I,
)
TARGET_REPAIR_TITLE = re.compile(r"трещин|шв|герметизац|протеч|теч[ьи]", re.I)
STRUCTURAL_INJECTION_TITLE = re.compile(
    r"(?:усилен|укреп|ремонт)\w*.*фунд|фунд\w*.*(?:усилен|укреп|ремонт)", re.I
)
QUERY_PRODUCT_INTENT = re.compile(
    r"аппарат|насос|материал|купить|смол|состав|система защиты от протеч|^отсечная гидроизоляция$",
    re.I,
)

FUTURE_QUERIES = [
    ("инъекционная гидроизоляция", "инъектирование"),
    ("гидроизоляционное инъектирование", "инъектирование"),
    ("инъектирование трещин", "инъектирование"),
    ("инъектирование швов", "инъектирование"),
    ("инъектирование фундамента", "инъектирование"),
    ("инъектирование подвала", "инъектирование"),
    ("инъектирование бетона", "инъектирование"),
    ("инъектирование кирпичной кладки", "инъектирование"),
    ("инъектирование деформационных швов", "инъектирование"),
    ("инъектирование холодных швов", "инъектирование"),
    ("инъектирование грунта под фундаментом", "инъектирование"),
    ("усиление фундамента инъектированием", "инъектирование"),
    ("укрепление фундамента инъектированием", "инъектирование"),
    ("инъекционная отсечная гидроизоляция", "инъектирование"),
    ("гидроизоляционные работы", "общая гидроизоляция"),
    ("гидроизоляция фундамента услуги", "объекты"),
    ("гидроизоляция подвала услуги", "объекты"),
    ("гидроизоляция паркинга", "объекты"),
    ("гидроизоляция цоколя услуги", "объекты"),
    ("гидроизоляция бетона услуги", "объекты"),
    ("гидроизоляция кровли услуги", "объекты"),
    ("гидроизоляция бассейна услуги", "объекты"),
    ("устранение протечек в подвале", "ремонт"),
    ("герметизация трещин бетона", "ремонт"),
    ("ремонт деформационных швов", "ремонт"),
    ("монтаж гидроизоляционной мембраны", "технологии"),
    ("нанесение жидкой гидроизоляции", "технологии"),
    ("проникающая гидроизоляция работы", "технологии"),
    ("обмазочная гидроизоляция работы", "технологии"),
    ("рулонная гидроизоляция монтаж", "технологии"),
]


def norm(value: object) -> str:
    return SPACE.sub(" ", str(value or "").replace("ё", "е").lower()).strip()


def truthy(value: object) -> bool:
    return str(value or "").lower() in {"1", "true", "yes", "да"}


def listing_text(value: dict) -> tuple[str, str, str]:
    detail = value.get("detail") or {}
    card = value.get("card") or {}
    title = norm(detail.get("title") or card.get("title"))
    body = norm(
        "\n".join(
            str(item or "")
            for item in (
                detail.get("description"),
                detail.get("parametersText"),
                detail.get("rawText"),
                card.get("description"),
                card.get("rawText"),
            )
        )
    )
    seller = norm(detail.get("seller") or card.get("seller"))
    return title, body, seller


def seller_url(value: dict) -> str:
    detail = value.get("detail") or {}
    card = value.get("card") or {}
    return str(detail.get("sellerURL") or card.get("sellerURL") or "")


def classify_direct(value: dict) -> dict:
    title, body, _ = listing_text(value)
    full = f"{title}\n{body}"
    unavailable = bool((value.get("detail") or {}).get("availability"))
    pending = not value.get("detail")
    title_injection = bool(INJECTION.search(title) and CONSTRUCTION.search(title))
    body_injection = bool(INJECTION.search(body) and CONSTRUCTION.search(body))
    parameters = norm((value.get("detail") or {}).get("parametersText"))
    service_params = bool(SERVICE_PARAMS.search(parameters))
    product_params = bool(PRODUCT_PARAMS.search(parameters)) and not service_params
    product_title = bool(PRODUCT.search(title)) and not ACTION_TITLE.search(title)
    product = product_params or product_title
    hard_noise = bool(HARD_NOISE.search(title))
    service = bool(service_params or SERVICE.search(title) or SERVICE.search(body[:5000]))

    # Некоторые исполнители ошибочно публикуют услуги в товарной категории Авито.
    # Явный строительный заголовок сильнее товарных параметров, если сам заголовок
    # не описывает насос, смолу или другой продукт.
    if title_injection and not product_title and not hard_noise:
        return {"decision": "core", "reason": "инъектирование указано в заголовке", "confidence": 100}
    if hard_noise and not re.search(r"гидроизол|гироизол", title, re.I) and not title_injection:
        return {"decision": "irrelevant", "reason": "нерелевантная услуга или инженерная система в заголовке", "confidence": 100}
    if WATERPROOF_TITLE.search(title) and ACTION_TITLE.search(title):
        return {"decision": "relevant", "reason": "явно указаны работы по гидроизоляции", "confidence": 100}
    if WATERPROOF_TITLE.search(title) and SERVICE_OBJECT_TITLE.search(title) and service and not product_title:
        return {"decision": "relevant", "reason": "услуга гидроизоляции объекта", "confidence": 95}
    if product:
        return {"decision": "irrelevant", "reason": "товар, материал или оборудование", "confidence": 100}
    if WATERPROOF_TITLE.search(title) and (service or service_params):
        return {"decision": "relevant", "reason": "услуга по гидроизоляции", "confidence": 95}
    if WATERPROOF_TITLE.search(title) and not value.get("detail"):
        return {"decision": "relevant", "reason": "неоткрытая карточка услуги по гидроизоляции", "confidence": 85}
    if WATERPROOF_TITLE.search(title) and unavailable:
        return {"decision": "relevant", "reason": "закрытая карточка услуги по гидроизоляции", "confidence": 85}
    if WATERPROOF_TITLE.search(title) and not product_params:
        return {"decision": "review", "reason": "гидроизоляция в заголовке, тип объявления не распознан", "confidence": 60}
    if RELATED_TITLE.search(title) and body_injection and service and (TARGET_REPAIR_TITLE.search(title) or STRUCTURAL_INJECTION_TITLE.search(title)):
        return {"decision": "relevant", "reason": "смежный строительный заголовок, инъектирование в карточке", "confidence": 85}
    if RELATED_TITLE.search(title) and body_injection:
        return {"decision": "review", "reason": "инъектирование упомянуто только в тексте смежной карточки", "confidence": 60}
    if unavailable and (INJECTION.search(title) and CONSTRUCTION.search(title)):
        return {"decision": "core", "reason": "закрытая карточка с релевантным заголовком", "confidence": 95}
    if pending and INJECTION.search(title) and CONSTRUCTION.search(title):
        return {"decision": "core", "reason": "неоткрытая карточка с релевантным заголовком", "confidence": 95}
    return {"decision": "irrelevant", "reason": "в заголовке нет целевой услуги", "confidence": 90}


def classify_all(listings: dict) -> dict[str, dict]:
    decisions = {item_id: classify_direct(value) for item_id, value in listings.items()}
    core_sellers = {
        seller_url(listings[item_id])
        for item_id, row in decisions.items()
        if row["decision"] == "core" and seller_url(listings[item_id])
    }
    for item_id, row in decisions.items():
        if row["decision"] != "review":
            continue
        value = listings[item_id]
        title, _, _ = listing_text(value)
        if seller_url(value) in core_sellers and WATERPROOF_TITLE.search(title):
            decisions[item_id] = {
                "decision": "relevant",
                "reason": "гидроизоляционная карточка продавца с подтверждённым инъектированием",
                "confidence": 80,
            }
    return decisions


def load_parts(paths: list[Path]) -> tuple[dict, dict, list, dict]:
    parts = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    if not parts:
        raise ValueError("Не выбраны части JSON")
    export_ids = {part.get("exportId") for part in parts}
    expected = parts[0].get("parts")
    if len(export_ids) != 1 or len(parts) != expected or {part.get("part") for part in parts} != set(range(1, expected + 1)):
        raise ValueError("Части относятся к разным или неполным выгрузкам")
    common = None
    listings: dict[str, dict] = {}
    captures: list[dict] = []
    for part in sorted(parts, key=lambda item: item["part"]):
        for record in part.get("records", []):
            if record.get("type") == "common":
                if common is not None:
                    raise ValueError("Служебная запись повторяется")
                common = record["value"]
            elif record.get("type") == "listing":
                listings[record["id"]] = record["value"]
            elif record.get("type") == "capture":
                captures.append(record["value"])
    if common is None:
        raise ValueError("Служебная запись не найдена")
    return common, listings, captures, parts[0]


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def query_report(captures: list[dict], decisions: dict[str, dict]) -> list[dict]:
    ids_by_query: dict[str, set[str]] = defaultdict(set)
    pages = defaultdict(set)
    for capture in captures:
        if capture.get("kind") != "search":
            continue
        query = str(capture.get("query") or "")
        pages[query].add((str(capture.get("page") or "1"), str(capture.get("sort") or "default")))
        for item in capture.get("items") or []:
            item_id = str(item.get("id") or "")
            if item_id:
                ids_by_query[query].add(item_id)
    all_queries = list(ids_by_query)
    relevant_sets = {
        query: {item_id for item_id in ids if decisions.get(item_id, {}).get("decision") in {"core", "relevant"}}
        for query, ids in ids_by_query.items()
    }
    eligible = {query for query, ids in ids_by_query.items() if ids and 100 * len(relevant_sets[query]) / len(ids) >= 35}
    target = set().union(*(relevant_sets[query] for query in eligible)) if eligible else set()
    selected: set[str] = set()
    covered: set[str] = set()
    while eligible - selected and len(covered) < 0.90 * len(target):
        query = max(
            eligible - selected,
            key=lambda value: (len(relevant_sets[value] - covered), len(relevant_sets[value]) / len(ids_by_query[value]), value),
        )
        if not (relevant_sets[query] - covered):
            break
        selected.add(query)
        covered.update(relevant_sets[query])
    rows = []
    for query in all_queries:
        ids = ids_by_query[query]
        counts = Counter(decisions.get(item_id, {}).get("decision", "missing") for item_id in ids)
        relevant = relevant_sets[query]
        other_relevant = set().union(*(relevant_sets[q] for q in all_queries if q != query)) if len(all_queries) > 1 else set()
        share = 100 * len(relevant) / len(ids) if ids else 0
        marginal = relevant - other_relevant
        if QUERY_PRODUCT_INTENT.search(query):
            recommendation = "disable"
            reason = "товарное намерение запроса или заведомо шумная выдача"
        elif query in selected:
            recommendation = "keep"
            reason = "входит в компактный набор с покрытием не менее 90% релевантной выдачи"
        elif share >= 35:
            recommendation = "review"
            reason = "релевантная, но в основном дублирует активный набор"
        else:
            recommendation = "disable"
            reason = "почти вся выдача нерелевантна"
        rows.append({
            "query": query,
            "recommendation": recommendation,
            "reason": reason,
            "pages_saved": len(pages[query]),
            "unique_listings": len(ids),
            "core": counts["core"],
            "relevant": counts["relevant"],
            "review": counts["review"],
            "irrelevant": counts["irrelevant"],
            "relevant_share_pct": f"{share:.1f}",
            "marginal_relevant": len(marginal),
        })
    return sorted(rows, key=lambda row: (-float(row["relevant_share_pct"]), -int(row["marginal_relevant"]), row["query"]))


def clean_state(common: dict, listings: dict, captures: list[dict], decisions: dict[str, dict], active_queries: dict[str, str], mode: str) -> tuple[dict, dict, list]:
    statuses = {"core"} if mode == "strict" else {"core", "relevant"}
    keep_ids = {item_id for item_id, row in decisions.items() if row["decision"] in statuses}
    clean_listings = {item_id: value for item_id, value in listings.items() if item_id in keep_ids}
    used_sellers = {seller_url(value) for value in clean_listings.values() if seller_url(value)}
    clean_common = dict(common)
    old_meta = common.get("queryMeta") or {}
    clean_common["queries"] = list(active_queries)
    clean_common["queryMeta"] = {
        query: {**old_meta.get(query, {}), "avito": True, "wordstat": True, "cluster": cluster, "source": old_meta.get(query, {}).get("source", "cleaning")}
        for query, cluster in active_queries.items()
    }
    clean_common["sellerProfiles"] = {url: value for url, value in (common.get("sellerProfiles") or {}).items() if url in used_sellers}
    wordstat = dict(common.get("wordstat") or {})
    if isinstance(wordstat.get("results"), dict):
        wordstat["results"] = {query: value for query, value in wordstat["results"].items() if query in active_queries}
    clean_common["wordstat"] = wordstat
    clean_captures = []
    for capture in captures:
        kind = capture.get("kind")
        if kind == "search":
            if capture.get("query") not in active_queries:
                continue
            updated = dict(capture)
            updated["items"] = [item for item in capture.get("items") or [] if str(item.get("id") or "") in keep_ids]
            clean_captures.append(updated)
        elif kind == "detail":
            items = [item for item in capture.get("items") or [] if str(item.get("id") or "") in keep_ids]
            if items:
                updated = dict(capture)
                updated["items"] = items
                clean_captures.append(updated)
    return clean_common, clean_listings, clean_captures


def split_backup(output: Path, stem: str, common: dict, listings: dict, captures: list, exported_at: str, max_bytes: int) -> list[Path]:
    records = [{"type": "common", "value": common}]
    records.extend({"type": "listing", "id": item_id, "value": value} for item_id, value in listings.items())
    records.extend({"type": "capture", "value": value} for value in captures)
    groups: list[list[dict]] = []
    group: list[dict] = []
    current_size = 2
    for record in records:
        encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if group and current_size + len(encoded) + 1 > max_bytes:
            groups.append(group)
            group = []
            current_size = 2
        group.append(record)
        current_size += len(encoded) + 1
    if group:
        groups.append(group)
    export_id = str(uuid.uuid4())
    paths = []
    for index, values in enumerate(groups, 1):
        payload = {"format": "avito-research-parts-v1", "exportId": export_id, "exportedAt": exported_at, "part": index, "parts": len(groups), "records": values}
        path = output / f"{stem}-part-{index:03d}-of-{len(groups):03d}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        if path.stat().st_size > max_bytes:
            raise ValueError(f"Часть превышает лимит: {path}")
        paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parts", nargs="+", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("output/cleaned"))
    parser.add_argument("--max-part-mb", type=int, default=18)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    common, listings, captures, source_meta = load_parts(args.parts)
    decisions = classify_all(listings)
    queries = query_report(captures, decisions)
    active_queries = dict(FUTURE_QUERIES)

    listing_rows = []
    for item_id, value in listings.items():
        title, _, seller = listing_text(value)
        row = decisions[item_id]
        listing_rows.append({"id": item_id, "decision": row["decision"], "confidence": row["confidence"], "reason": row["reason"], "title": title, "seller": seller, "seller_url": seller_url(value), "detail_saved": bool(value.get("detail")), "unavailable": bool((value.get("detail") or {}).get("availability")), "url": value.get("url") or (value.get("detail") or {}).get("url") or (value.get("card") or {}).get("url") or ""})
    listing_rows.sort(key=lambda row: (row["decision"], row["title"], row["id"]))
    write_csv(args.output_dir / "listing-decisions.csv", listing_rows, ["id", "decision", "confidence", "reason", "title", "seller", "seller_url", "detail_saved", "unavailable", "url"])
    pending_rows = [row for row in listing_rows if row["decision"] in {"core", "relevant"} and not row["detail_saved"] and not row["unavailable"]]
    write_csv(args.output_dir / "pending-to-collect.csv", pending_rows, ["id", "decision", "confidence", "reason", "title", "seller", "seller_url", "url"])
    review_rows = [row for row in listing_rows if row["decision"] == "review"]
    write_csv(args.output_dir / "manual-review.csv", review_rows, ["id", "decision", "confidence", "reason", "title", "seller", "seller_url", "detail_saved", "unavailable", "url"])
    write_csv(args.output_dir / "query-quality.csv", queries, ["query", "recommendation", "reason", "pages_saved", "unique_listings", "core", "relevant", "review", "irrelevant", "relevant_share_pct", "marginal_relevant"])
    for status in ("keep", "review", "disable"):
        values = [row["query"] for row in queries if row["recommendation"] == status]
        (args.output_dir / f"queries-history-{status}.txt").write_text("\n".join(values) + ("\n" if values else ""), encoding="utf-8")
    (args.output_dir / "queries-future.txt").write_text("\n".join(active_queries) + "\n", encoding="utf-8")
    write_csv(
        args.output_dir / "queries-future.csv",
        [{"query": query, "cluster": cluster, "reason": "сформулирован как запрос услуги, без товарного намерения"} for query, cluster in active_queries.items()],
        ["query", "cluster", "reason"],
    )

    seller_groups: dict[str, list[dict]] = defaultdict(list)
    for row in listing_rows:
        if row["seller_url"]:
            seller_groups[row["seller_url"]].append(row)
    seller_rows = []
    for url, rows in seller_groups.items():
        counts = Counter(row["decision"] for row in rows)
        keep = counts["core"] + counts["relevant"]
        seller_rows.append({"seller_url": url, "seller": next((row["seller"] for row in rows if row["seller"]), ""), "total_listings": len(rows), "core": counts["core"], "relevant": counts["relevant"], "review": counts["review"], "irrelevant": counts["irrelevant"], "keep_listings": keep, "keep_share_pct": f"{100*keep/len(rows):.1f}", "seller_decision": "keep" if keep else "exclude"})
    seller_rows.sort(key=lambda row: (-int(row["keep_listings"]), -int(row["total_listings"]), row["seller"]))
    write_csv(args.output_dir / "seller-decisions.csv", seller_rows, ["seller_url", "seller", "seller_decision", "total_listings", "core", "relevant", "review", "irrelevant", "keep_listings", "keep_share_pct"])

    outputs = {}
    for mode in ("strict", "balanced"):
        clean_common, clean_listings, clean_captures = clean_state(common, listings, captures, decisions, active_queries, mode)
        paths = split_backup(args.output_dir, f"avito-research-clean-{mode}", clean_common, clean_listings, clean_captures, str(source_meta.get("exportedAt") or ""), args.max_part_mb * 1024 * 1024)
        outputs[mode] = {"listings": len(clean_listings), "sellers": len({seller_url(value) for value in clean_listings.values() if seller_url(value)}), "captures": len(clean_captures), "parts": [path.name for path in paths]}

    counts = Counter(row["decision"] for row in listing_rows)
    pending_counts = Counter(row["decision"] for row in listing_rows if not row["detail_saved"] and not row["unavailable"])
    summary = {"source_listings": len(listings), "source_captures": len(captures), "source_seller_profiles": len(common.get("sellerProfiles") or {}), "decisions": counts, "pending_decisions": pending_counts, "query_recommendations": Counter(row["recommendation"] for row in queries), "future_queries": len(active_queries), "outputs": outputs}
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
