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
        self.assertEqual(scored.confidence, "high")

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


if __name__ == "__main__":
    unittest.main()
