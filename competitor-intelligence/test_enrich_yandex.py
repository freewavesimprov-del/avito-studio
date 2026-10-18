import base64
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("enrich_yandex.py")
SPEC = importlib.util.spec_from_file_location("enrich_yandex", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class YandexEnrichmentTests(unittest.TestCase):
    def test_credentials_are_saved_and_loaded_with_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "credentials.json"
            MODULE.save_credentials(path, "folder-1", "secret-key")
            self.assertEqual(
                MODULE.load_credentials(path),
                {"folder_id": "folder-1", "api_key": "secret-key"},
            )
            if os.name == "posix":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_invalid_credentials_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.json"
            path.write_text("not-json", encoding="utf-8")
            self.assertEqual(MODULE.load_credentials(path), {})

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
        self.assertEqual(MODULE.query_plan({"seller": "Пользователь"}, 4), [])

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

    def test_expected_twelve_digit_inn_confirms_sole_trader(self):
        result = MODULE.SearchResult(
            query="site:rusprofile.ru 570800933090",
            title="ИП Фатьянов Алексей Васильевич",
            url="https://www.rusprofile.ru/ip/321508100252474",
            domain="rusprofile.ru",
            snippet="ИНН 570800933090 Москва",
            result_type="legal_registry",
        )
        scored = MODULE.score_result(result, {"seller": "ЧИНИМ ТРУБЫ", "inn_hint": "570800933090"})
        self.assertEqual(scored.inn, "570800933090")
        self.assertEqual(scored.confidence, "high")
        official_site = MODULE.SearchResult(
            query="site:chinimtruby.ru ИНН ОГРН реквизиты",
            title="Чиним трубы",
            url="https://chinimtruby.ru/uslugi/remont-livnevoj-kanalizaczii/",
            domain="chinimtruby.ru",
            snippet="ИП Фатьянов Алексей Васильевич, ИНН 570800933090, ОГРНИП 321508100252474",
            score=34,
            result_type="official_site_candidate",
            confidence="low",
            legal_name="ИП Фатьянов Алексей Васильевич",
            inn="570800933090",
            ogrn="321508100252474",
        )
        chosen = MODULE.choose_candidates([scored, official_site])
        self.assertEqual(chosen["auto_inn_candidate"], "570800933090")
        self.assertEqual(chosen["auto_ogrn_candidate"], "321508100252474")

    def test_business_directory_is_not_official_site(self):
        self.assertEqual(MODULE.classify_result("propartner.ru"), "other")
        self.assertEqual(MODULE.classify_result("focus.kontur.ru"), "other")
        self.assertEqual(MODULE.classify_result("vbankcenter.ru"), "other")

    def test_confirmed_legal_identity_drives_overall_confidence(self):
        website = MODULE.SearchResult(
            query='"ГеоЦемСтрой" ИНН',
            title="ГеоЦемСтрой",
            url="https://geocemstroy.ru/",
            domain="geocemstroy.ru",
            snippet="Официальный сайт",
            score=65,
            result_type="official_site_candidate",
            confidence="medium",
        )
        legal = MODULE.SearchResult(
            query="site:checko.ru 5948073464",
            title='ООО "ГЕОЦЕМСТРОЙ"',
            url="https://checko.ru/company/gcs-1245900013446",
            domain="checko.ru",
            snippet="ИНН 5948073464",
            score=100,
            result_type="legal_registry",
            confidence="high",
            legal_name='ООО "ГЕОЦЕМСТРОЙ"',
            inn="5948073464",
        )
        chosen = MODULE.choose_candidates([website, legal])
        self.assertEqual(chosen["auto_match_confidence"], "high")
        self.assertEqual(chosen["auto_match_score"], "100")
        self.assertEqual(chosen["auto_website_candidate"], "https://geocemstroy.ru/")


if __name__ == "__main__":
    unittest.main()
