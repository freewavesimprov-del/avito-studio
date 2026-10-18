import base64
import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("enrich_yandex.py")
SPEC = importlib.util.spec_from_file_location("enrich_yandex", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class YandexEnrichmentTests(unittest.TestCase):
    def test_parses_xml_results(self):
        xml = """<yandexsearch><response><results><grouping><group><doc>
        <url>https://www.rusprofile.ru/id/123</url><domain>www.rusprofile.ru</domain>
        <title>ООО «ГИДРОПРО»</title><passages><passage>ИНН 7712345678, Москва</passage></passages>
        </doc></group></grouping></results></response></yandexsearch>"""
        rows = MODULE.parse_search_xml(xml, 'site:rusprofile.ru "ГИДРОПРО"')
        self.assertEqual(rows[0].domain, "rusprofile.ru")
        self.assertEqual(rows[0].result_type, "legal_registry")
        scored = MODULE.score_result(rows[0], {"seller": "ООО ГИДРОПРО", "city_list": "Москва"})
        self.assertEqual(scored.inn, "7712345678")
        self.assertEqual(scored.confidence, "medium")

    def test_decodes_api_raw_data(self):
        raw = base64.b64encode("<yandexsearch/>".encode()).decode()
        self.assertEqual(MODULE.decode_xml_response({"rawData": raw}), "<yandexsearch/>")

    def test_generic_name_uses_contact(self):
        queries = MODULE.query_plan(
            {"seller": "Андрей", "legal_name_hint": "", "avito_contact_person": "Андрей Ожегов"},
            4,
        )
        self.assertIn('"Андрей Ожегов"', queries[0])
        self.assertTrue(any("site:rusprofile.ru" in query for query in queries))

    def test_bad_or_bare_person_name_is_skipped(self):
        self.assertEqual(MODULE.query_plan({"seller": "3 отзыва"}, 4), [])
        self.assertEqual(MODULE.query_plan({"seller": "Николай"}, 4), [])

    def test_nested_quotes_are_cleaned(self):
        queries = MODULE.query_plan({"seller": 'ООО "ГеоЦемСтрой"', "legal_name_hint": 'ООО "ГеоЦемСтрой"'}, 4)
        self.assertEqual(queries[0], '"ООО ГеоЦемСтрой" ИНН')

    def test_partial_brand_does_not_count_as_exact_phrase(self):
        result = MODULE.SearchResult(
            query='site:checko.ru "РСУ-Комп"',
            title='ЗАО РСУ Комплект-Сервис',
            url='https://checko.ru/company/example',
            domain='checko.ru',
            snippet='ИНН 7727119467',
            result_type='legal_registry',
        )
        scored = MODULE.score_result(result, {"seller": "РСУ-Комп", "city_list": "Москва"})
        self.assertNotEqual(scored.confidence, "high")

    def test_adaptive_search_prefers_found_brand_domain(self):
        result = MODULE.SearchResult(
            query='"ЧИНИМ ТРУБЫ" гидроизоляция Москва',
            title='Чиним трубы — официальный сайт',
            url='https://chinimtruby.ru/',
            domain='chinimtruby.ru',
            snippet='Ремонт труб в Москве',
            score=79,
            result_type='official_site_candidate',
            confidence='medium',
        )
        queries = MODULE.adaptive_queries({"seller": "ЧИНИМ ТРУБЫ"}, [result], 4)
        self.assertEqual(queries[0], "site:chinimtruby.ru ИНН ОГРН реквизиты")

    def test_low_legal_matches_do_not_become_identity(self):
        result = MODULE.SearchResult(
            query='site:checko.ru "РСУ-Комп"',
            title='ООО РСУ-1 Москва',
            url='https://checko.ru/company/example',
            domain='checko.ru',
            snippet='ИНН 7712345678',
            score=59,
            result_type='legal_registry',
            confidence='medium',
            inn='7712345678',
        )
        chosen = MODULE.choose_candidates([result])
        self.assertEqual(chosen["auto_search_status"], "no_reliable_candidate")
        self.assertEqual(chosen["auto_inn_candidate"], "")

    def test_expected_inn_confirms_registry_record(self):
        result = MODULE.SearchResult(
            query="site:rusprofile.ru 7712345678",
            title='ООО "ПРИМЕР"',
            url="https://www.rusprofile.ru/id/123",
            domain="rusprofile.ru",
            snippet="ИНН 7712345678 Москва",
            result_type="legal_registry",
        )
        scored = MODULE.score_result(result, {"seller": "Бренд", "inn_hint": "7712345678"})
        self.assertEqual(scored.confidence, "high")


if __name__ == "__main__":
    unittest.main()
