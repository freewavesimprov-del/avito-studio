#!/usr/bin/env python3
"""Find company sites and legal records through Yandex Search API.

The API key is requested with getpass and is never written to disk. Search
responses are cached locally so an interrupted run can continue without spending
the same API quota twice.
"""

from __future__ import annotations

import argparse
import base64
import csv
import getpass
import hashlib
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse


API_ENDPOINT = "https://searchapi.api.cloud.yandex.net/v2/web/search"
LEGAL_DOMAINS = {
    "rusprofile.ru",
    "checko.ru",
    "audit-it.ru",
    "list-org.com",
    "zachestnyibiznes.ru",
    "sbis.ru",
    "companies.rbc.ru",
}
NO_OFFICIAL_SITE_DOMAINS = LEGAL_DOMAINS | {
    "avito.ru",
    "yandex.ru",
    "2gis.ru",
    "vk.com",
    "vk.ru",
    "youtube.com",
    "rutube.ru",
    "instagram.com",
    "facebook.com",
    "profi.ru",
    "youdo.com",
    "zoon.ru",
    "orgpage.ru",
    "spravker.ru",
    "t.me",
    "checksite.ru",
    "flamp.ru",
    "rubrikator.org",
    "otzywy.com",
    "tilbagevise.ru",
    "uslugi.yandex.ru",
    "propartner.ru",
}
SERVICE_WORDS = {
    "гидроизоляция",
    "инъектирование",
    "инъекционный",
    "инъекционная",
    "фундамент",
    "подвал",
    "трещина",
    "протечка",
    "ремонт",
    "строительство",
}
NAME_STOPWORDS = SERVICE_WORDS | {
    "ооо",
    "ип",
    "ао",
    "пао",
    "про",
    "рф",
    "москва",
    "московская",
    "область",
    "компания",
    "услуги",
}
COMMON_FIRST_NAMES = {
    "александр", "алексей", "андрей", "артем", "вадим", "валентин", "василий",
    "виталий", "владимир", "дмитрий", "евгений", "игорь", "илья", "ильяс",
    "кирилл", "максим", "михаил", "николай", "павел", "роман", "сергей",
    "семен", "станислав", "тимофей", "федор", "юрий",
}


@dataclass
class SearchResult:
    query: str
    title: str
    url: str
    domain: str
    snippet: str
    score: int = 0
    result_type: str = "other"
    confidence: str = "low"
    legal_name: str = ""
    inn: str = ""
    ogrn: str = ""


def clean(value: object) -> str:
    return str(value or "").strip()


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).lower().replace("ё", "е")
    value = re.sub(r"[^a-zа-я0-9]+", " ", value)
    return " ".join(value.split())


def domain_of(url: str) -> str:
    domain = urlparse(url).netloc.lower().split(":")[0]
    return domain[4:] if domain.startswith("www.") else domain


def registrable_match(domain: str, candidates: set[str]) -> bool:
    return any(domain == candidate or domain.endswith("." + candidate) for candidate in candidates)


def brand_tokens(name: str) -> list[str]:
    return [token for token in normalize(name).split() if len(token) >= 3 and token not in NAME_STOPWORDS]


def is_generic_name(name: str) -> bool:
    tokens = brand_tokens(name)
    normalized = normalize(name)
    return len(tokens) <= 1 and not re.search(r"\b(?:ооо|ип|ао|пао)\b", normalized)


def quoted(value: str) -> str:
    value = re.sub(r"[«»\"“”]+", " ", value)
    return f'"{" ".join(value.split())}"'


def is_unsearchable_identity(competitor: dict[str, str]) -> bool:
    seller = normalize(clean(competitor.get("seller")))
    if not seller or re.fullmatch(r"\d+\s+отзыв(?:а|ов)?", seller):
        return True
    if clean(competitor.get("legal_name_hint")) or clean(competitor.get("avito_contact_person")):
        return False
    return seller in COMMON_FIRST_NAMES


def extract_legal(text: str) -> tuple[str, str, str]:
    plain = re.sub(r"\s+", " ", text)
    legal = re.search(
        r"\b(ООО|ИП|АО|ПАО|ЗАО|ОАО)\s*[«\"“]?([А-ЯЁA-Z0-9][^|;,.!?<>]{1,80})",
        plain,
        re.I,
    )
    legal_name = ""
    if legal:
        tail = re.sub(r"[»\"”]+$", "", legal.group(2).strip())
        legal_name = f"{legal.group(1).upper()} {tail}"
    inn = ""
    inn_match = re.search(r"\bИНН\s*[:№]?\s*(\d{10}|\d{12})\b", plain, re.I)
    if inn_match:
        inn = inn_match.group(1)
    ogrn = ""
    ogrn_match = re.search(r"\bОГРН(?:ИП)?\s*[:№]?\s*(\d{13}|\d{15})\b", plain, re.I)
    if ogrn_match:
        ogrn = ogrn_match.group(1)
    return legal_name, inn, ogrn


def classify_result(domain: str) -> str:
    if registrable_match(domain, LEGAL_DOMAINS):
        return "legal_registry"
    if domain in {"yandex.ru", "2gis.ru"} or domain.endswith(".yandex.ru"):
        return "map_or_directory"
    if not registrable_match(domain, NO_OFFICIAL_SITE_DOMAINS):
        return "official_site_candidate"
    return "other"


def phrase_in(phrase: str, text: str) -> bool:
    if not phrase:
        return False
    return bool(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text))


def score_result(result: SearchResult, competitor: dict[str, str]) -> SearchResult:
    name = clean(competitor.get("legal_name_hint")) or clean(competitor.get("seller"))
    haystack = normalize(f"{result.title} {result.snippet} {result.domain}")
    normalized_name = normalize(name)
    tokens = brand_tokens(name)
    contact_tokens = brand_tokens(clean(competitor.get("avito_contact_person")))
    query_legal = "site:rusprofile.ru" in result.query or "site:checko.ru" in result.query

    score = 0
    if phrase_in(normalized_name, haystack):
        score += 35
    if tokens:
        haystack_tokens = set(haystack.split())
        matched = sum(token in haystack_tokens for token in tokens)
        score += round(30 * matched / len(tokens))
    if any(word in haystack for word in SERVICE_WORDS):
        score += 10
    if any(token in haystack for token in contact_tokens):
        score += 12
    if "моск" in haystack or "москов" in normalize(clean(competitor.get("city_list"))):
        score += 4
    if result.result_type == "legal_registry" and query_legal:
        score += 10
    if result.result_type == "official_site_candidate":
        domain_tokens = set(normalize(result.domain).split())
        if any(token in result.domain.replace("-", "") for token in tokens) or domain_tokens.intersection(tokens):
            score += 12

    legal_name, inn, ogrn = extract_legal(f"{result.title} {result.snippet}")
    # Check 12 digits first: with the opposite alternation order a sole-trader
    # INN was truncated to its first 10 digits and could never be confirmed.
    expected_inns = set(
        re.findall(
            r"(?<!\d)(?:\d{12}|\d{10})(?!\d)",
            " ".join([clean(competitor.get("inn_hint")), clean(competitor.get("inn"))]),
        )
    )
    inn_confirmed = bool(inn and inn in expected_inns)
    if inn_confirmed:
        score += 45
    elif inn:
        score += 20
    if legal_name and normalize(legal_name) == normalized_name:
        score += 25
    if is_generic_name(name) and not inn_confirmed:
        score -= 25
    score = max(0, min(100, score))

    confidence = "low"
    exact_legal_hint = bool(clean(competitor.get("legal_name_hint"))) and normalize(legal_name) == normalize(clean(competitor.get("legal_name_hint")))
    if (inn_confirmed and score >= 55) or (exact_legal_hint and score >= 75):
        confidence = "high"
    elif score >= 55:
        confidence = "medium"
    result.score = score
    result.confidence = confidence
    result.legal_name = legal_name
    result.inn = inn
    result.ogrn = ogrn
    return result


def query_plan(competitor: dict[str, str], max_queries: int) -> list[str]:
    seller = clean(competitor.get("seller"))
    legal_hint = clean(competitor.get("legal_name_hint"))
    contact = clean(competitor.get("avito_contact_person")).split(";", 1)[0]
    name = legal_hint or seller
    if is_unsearchable_identity(competitor):
        return []
    name_phrase = quoted(name)
    seller_phrase = quoted(seller)
    contact_phrase = quoted(contact) if contact else ""
    queries = []
    if legal_hint:
        queries.append(f"{name_phrase} ИНН")
    elif is_generic_name(seller) and contact:
        queries.append(f"{seller_phrase} {contact_phrase} гидроизоляция Москва")
    else:
        queries.append(f"{seller_phrase} гидроизоляция Москва")
    queries.append(f"site:rusprofile.ru {name_phrase}")
    queries.append(f"site:checko.ru {name_phrase}")
    if not legal_hint:
        queries.append(f"{seller_phrase} ИНН гидроизоляция")
    queries.append(f"{name_phrase} инъектирование")
    return list(dict.fromkeys(queries))[:max_queries]


def adaptive_queries(competitor: dict[str, str], collected: list[SearchResult], max_queries: int) -> list[str]:
    """Choose follow-up searches from evidence found by the first query."""
    if max_queries <= 1:
        return []
    scored = sorted(collected, key=lambda item: item.score, reverse=True)
    website = next(
        (item for item in scored if item.result_type == "official_site_candidate" and item.score >= 55),
        None,
    )
    queries = []
    if website:
        queries.append(f"site:{website.domain} ИНН ОГРН реквизиты")
    exact_identity = next((item for item in scored if item.inn and item.score >= 55), None)
    if exact_identity:
        queries.extend(
            [
                f"site:rusprofile.ru {exact_identity.inn}",
                f"site:checko.ru {exact_identity.inn}",
            ]
        )
    else:
        name = clean(competitor.get("legal_name_hint")) or clean(competitor.get("seller"))
        phrase = quoted(name)
        queries.extend([f"site:rusprofile.ru {phrase}", f"site:checko.ru {phrase}"])
    return list(dict.fromkeys(queries))[: max(0, max_queries - 1)]


def registry_queries(competitor: dict[str, str], collected: list[SearchResult], preferred_domain: str = "") -> list[str]:
    trusted_identity = next(
        (
            item
            for item in sorted(collected, key=lambda value: value.score, reverse=True)
            if item.inn
            and ((preferred_domain and item.domain == preferred_domain) or (not preferred_domain and item.score >= 55))
        ),
        None,
    )
    if trusted_identity:
        return [f"site:rusprofile.ru {trusted_identity.inn}", f"site:checko.ru {trusted_identity.inn}"]
    name = clean(competitor.get("legal_name_hint")) or clean(competitor.get("seller"))
    phrase = quoted(name)
    return [f"site:rusprofile.ru {phrase}", f"site:checko.ru {phrase}"]


def decode_xml_response(payload: dict) -> str:
    raw = payload.get("rawData") or payload.get("raw_data")
    if not raw:
        raise ValueError("В ответе Search API отсутствует rawData")
    try:
        return base64.b64decode(raw).decode("utf-8", errors="replace")
    except Exception as error:
        raise ValueError("Не удалось декодировать rawData Search API") from error


def element_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def find_child(element: ET.Element, name: str) -> ET.Element | None:
    for child in element.iter():
        if child.tag.rsplit("}", 1)[-1] == name:
            return child
    return None


def parse_search_xml(xml: str, query: str) -> list[SearchResult]:
    root = ET.fromstring(xml)
    results = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "doc":
            continue
        url = element_text(find_child(element, "url"))
        if not url:
            continue
        title = element_text(find_child(element, "title"))
        passages = []
        for part in element.iter():
            if part.tag.rsplit("}", 1)[-1] in {"passage", "headline"}:
                value = element_text(part)
                if value:
                    passages.append(value)
        domain = element_text(find_child(element, "domain")) or domain_of(url)
        domain = domain_of("https://" + domain) if "://" not in domain else domain_of(domain)
        results.append(
            SearchResult(
                query=query,
                title=title,
                url=url,
                domain=domain,
                snippet=" ".join(dict.fromkeys(passages)),
                result_type=classify_result(domain),
            )
        )
    return results


class YandexSearchClient:
    def __init__(self, api_key: str, folder_id: str, region: str, cache_dir: Path, delay: float):
        self.api_key = api_key
        self.folder_id = folder_id
        self.region = region
        self.cache_dir = cache_dir
        self.delay = delay
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def search(self, query: str) -> list[SearchResult]:
        digest = hashlib.sha256(f"{self.folder_id}\0{self.region}\0{query}".encode()).hexdigest()
        cache_path = self.cache_dir / f"{digest}.json"
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            results = [SearchResult(**item) for item in cached["results"]]
            # Classification rules evolve between releases, while the response
            # cache is intentionally preserved. Reclassify cached URLs so an old
            # directory result cannot remain an "official site" forever.
            for result in results:
                result.domain = domain_of(result.url) or result.domain
                result.result_type = classify_result(result.domain)
            return results

        body = {
            "query": {
                "searchType": "SEARCH_TYPE_RU",
                "queryText": query,
                "familyMode": "FAMILY_MODE_MODERATE",
                "page": "0",
                "fixTypoMode": "FIX_TYPO_MODE_ON",
            },
            "sortSpec": {"sortMode": "SORT_MODE_BY_RELEVANCE", "sortOrder": "SORT_ORDER_DESC"},
            "groupSpec": {"groupMode": "GROUP_MODE_DEEP", "groupsOnPage": "10", "docsInGroup": "1"},
            "maxPassages": "3",
            "region": self.region,
            "folderId": self.folder_id,
            "responseFormat": "FORMAT_XML",
        }
        request = urllib.request.Request(
            API_ENDPOINT,
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Api-Key {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            message = error.read(2000).decode("utf-8", errors="replace")
            if error.code == 403:
                raise RuntimeError(
                    "Search API вернул 403. Проверьте значение API-ключа, folder ID, включённый "
                    "Yandex Search API и роль search-api.webSearch.user/search-api.execute. "
                    f"Ответ: {message}"
                ) from error
            raise RuntimeError(f"Search API вернул HTTP {error.code}: {message}") from error
        xml = decode_xml_response(payload)
        results = parse_search_xml(xml, query)
        cache_path.write_text(
            json.dumps({"query": query, "results": [asdict(item) for item in results]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        time.sleep(self.delay)
        return results


def read_registry(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader), list(reader.fieldnames or [])


AUTO_FIELDS = [
    "auto_search_status",
    "auto_match_confidence",
    "auto_match_score",
    "auto_legal_name_candidate",
    "auto_inn_candidate",
    "auto_ogrn_candidate",
    "auto_website_candidate",
    "auto_legal_record_url",
    "auto_evidence_urls",
    "auto_queries",
]


def choose_candidates(results: list[SearchResult]) -> dict[str, str]:
    ranked = sorted(results, key=lambda item: (item.score, item.confidence == "high"), reverse=True)
    legal = next(
        (
            item
            for item in ranked
            if item.result_type == "legal_registry"
            and (item.score >= 70 or (item.confidence == "high" and bool(item.inn)))
        ),
        None,
    )
    website = next((item for item in ranked if item.result_type == "official_site_candidate" and item.score >= 55), None)
    # A confirmed registry identity is stronger than a plausible website.
    best = legal or website
    same_identity = [item for item in ranked if legal and item.inn == legal.inn]
    legal_name = legal.legal_name if legal else ""
    ogrn = legal.ogrn if legal else ""
    if legal and not legal_name:
        legal_name = next((item.legal_name for item in same_identity if item.legal_name), "")
    if legal and not ogrn:
        ogrn = next((item.ogrn for item in same_identity if item.ogrn), "")
    evidence = []
    for item in ranked:
        if item.score >= 35 and item.url not in evidence:
            evidence.append(item.url)
    return {
        "auto_search_status": "candidate_found" if best else ("no_reliable_candidate" if ranked else "no_results"),
        "auto_match_confidence": best.confidence if best else "none",
        "auto_match_score": str(best.score) if best else "0",
        "auto_legal_name_candidate": legal_name,
        "auto_inn_candidate": legal.inn if legal else "",
        "auto_ogrn_candidate": ogrn,
        "auto_website_candidate": website.url if website else "",
        "auto_legal_record_url": legal.url if legal else "",
        "auto_evidence_urls": "\n".join(evidence[:8]),
    }


def write_csv(path: Path, rows: list[dict[str, str]], original_fields: list[str]) -> None:
    fields = original_fields + [field for field in AUTO_FIELDS if field not in original_fields]
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_results_csv(path: Path, all_results: list[tuple[str, SearchResult]]) -> None:
    fields = ["seller", "query", "score", "confidence", "result_type", "title", "url", "domain", "legal_name", "inn", "ogrn", "snippet"]
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for seller, result in all_results:
            writer.writerow({"seller": seller, **asdict(result)})


def write_html(path: Path, rows: list[dict[str, str]], results_by_seller: dict[str, list[SearchResult]]) -> None:
    cards = []
    for row in rows:
        seller = clean(row.get("seller"))
        result_rows = []
        for result in sorted(results_by_seller.get(seller, []), key=lambda item: item.score, reverse=True)[:10]:
            result_rows.append(
                f"<tr><td>{result.score}</td><td>{html.escape(result.confidence)}</td><td>{html.escape(result.result_type)}</td>"
                f"<td><a href='{html.escape(result.url)}' target='_blank'>{html.escape(result.title or result.domain)}</a>"
                f"<br><small>{html.escape(result.snippet[:450])}</small></td></tr>"
            )
        cards.append(
            f"<article><h2>{html.escape(seller)}</h2><p><b>Автовывод:</b> {html.escape(row.get('auto_match_confidence',''))} "
            f"({html.escape(row.get('auto_match_score',''))}) · {html.escape(row.get('auto_legal_name_candidate',''))} "
            f"{html.escape(row.get('auto_inn_candidate',''))}</p><table><tr><th>Балл</th><th>Уверенность</th><th>Тип</th><th>Результат</th></tr>"
            f"{''.join(result_rows) or '<tr><td colspan=4>Ничего не найдено</td></tr>'}</table></article>"
        )
    path.write_text(
        "<!doctype html><html lang='ru'><meta charset='utf-8'><title>Yandex enrichment</title><style>"
        "body{font:15px/1.45 system-ui;max-width:1200px;margin:30px auto;background:#f5f7f8;color:#172731}"
        "article{background:white;padding:18px;margin:16px;border-radius:12px}table{border-collapse:collapse;width:100%}"
        "td,th{border-top:1px solid #dde4e7;padding:8px;text-align:left;vertical-align:top}small{color:#60727c}</style>"
        "<h1>Кандидаты идентификации через Yandex Search API</h1><p>Высокая и средняя уверенность требуют проверки человеком перед переносом в подтверждённые поля.</p>"
        + "".join(cards)
        + "</html>",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=Path("output/competitors.csv"))
    parser.add_argument("--folder-id", required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("output/yandex-search"))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--max-queries", type=int, default=4)
    parser.add_argument("--region", default="213", help="Регион Yandex Search API; 213 — Москва")
    parser.add_argument("--delay", type=float, default=0.7)
    parser.add_argument("--dry-run", action="store_true", help="Только показать план запросов, не обращаться к API")
    parser.add_argument("--api-key", help="Не рекомендуется: попадёт в историю shell. Лучше скрытый запрос.")
    args = parser.parse_args()

    rows, original_fields = read_registry(args.registry)
    rows = rows[: max(1, args.limit)]
    plans = {clean(row.get("seller")): query_plan(row, args.max_queries) for row in rows}
    if args.dry_run:
        for seller, queries in plans.items():
            print(f"\n{seller}")
            for query in queries:
                print(f"  {query}")
        return

    api_key = args.api_key or os.environ.get("YANDEX_SEARCH_API_KEY") or getpass.getpass("API-ключ Yandex Search API: ")
    if not api_key:
        parser.error("API-ключ не указан")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    client = YandexSearchClient(api_key, args.folder_id, args.region, args.output_dir / "cache", args.delay)
    results_by_seller: dict[str, list[SearchResult]] = {}
    flat_results: list[tuple[str, SearchResult]] = []
    for index, row in enumerate(rows, 1):
        seller = clean(row.get("seller"))
        print(f"[{index}/{len(rows)}] {seller}")
        if not plans[seller]:
            row.update({field: "" for field in AUTO_FIELDS})
            row["auto_search_status"] = "insufficient_identity_clues"
            results_by_seller[seller] = []
            print("  пропущено: недостаточно признаков для надёжного поиска")
            continue
        collected: dict[str, SearchResult] = {}
        try:
            initial_query = plans[seller][0]
            actual_queries = [initial_query]
            for result in client.search(initial_query):
                scored = score_result(result, row)
                collected[scored.url] = scored
            remaining = max(0, args.max_queries - 1)
            website = next(
                (
                    item
                    for item in sorted(collected.values(), key=lambda value: value.score, reverse=True)
                    if item.result_type == "official_site_candidate" and item.score >= 55
                ),
                None,
            )
            if website and remaining:
                site_query = f"site:{website.domain} ИНН ОГРН реквизиты"
                actual_queries.append(site_query)
                for result in client.search(site_query):
                    scored = score_result(result, row)
                    previous = collected.get(scored.url)
                    if previous is None or scored.score > previous.score:
                        collected[scored.url] = scored
                remaining -= 1
            trusted_site_identity = next(
                (
                    item
                    for item in sorted(collected.values(), key=lambda value: value.score, reverse=True)
                    if website and item.domain == website.domain and item.inn
                ),
                None,
            )
            scoring_context = dict(row)
            if trusted_site_identity:
                scoring_context["inn_hint"] = trusted_site_identity.inn
            followups = registry_queries(row, list(collected.values()), website.domain if website else "")[:remaining]
            actual_queries.extend(followups)
            for query in followups:
                for result in client.search(query):
                    scored = score_result(result, scoring_context)
                    previous = collected.get(scored.url)
                    if previous is None or scored.score > previous.score:
                        collected[scored.url] = scored
        except Exception as error:
            print(f"Ошибка: {error}", file=sys.stderr)
            row.update({field: "" for field in AUTO_FIELDS})
            row["auto_search_status"] = f"error: {error}"
            results_by_seller[seller] = list(collected.values())
            continue
        results = list(collected.values())
        results_by_seller[seller] = results
        flat_results.extend((seller, result) for result in results)
        row.update(choose_candidates(results))
        row["auto_queries"] = "\n".join(actual_queries)

    write_csv(args.output_dir / "competitors.enriched.csv", rows, original_fields)
    write_results_csv(args.output_dir / "search-results.csv", flat_results)
    write_html(args.output_dir / "review.html", rows, results_by_seller)
    print(f"Готово: {(args.output_dir / 'review.html').resolve()}")


if __name__ == "__main__":
    main()
