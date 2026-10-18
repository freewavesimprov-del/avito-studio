import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("build_registry.py")
SPEC = importlib.util.spec_from_file_location("build_registry", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RegistryTests(unittest.TestCase):
    def test_extracts_business_clues_without_footer_company(self):
        evidence = {
            "texts": [
                "ООО ГИДРОПРО\nИНН 7712345678\nНа Авито c 2018 года\n"
                "12 объявлений пользователя\nМинимальная сумма заказа: 50000 ₽\n"
                "ООО «КЕХ еКоммерц» 2007–2026"
            ],
            "titles": ["Инъектирование трещин в бетоне"],
        }
        row = MODULE.extract_evidence("ООО ГИДРОПРО", "https://www.avito.ru/brands/gidropro.ru", evidence)
        self.assertEqual(row["legal_name_hint"], "ООО ГИДРОПРО")
        self.assertEqual(row["inn_hint"], "7712345678")
        self.assertEqual(row["website_candidate"], "https://gidropro.ru")
        self.assertEqual(row["avito_since_year"], "2018")
        self.assertIn("трещины/бетон", row["service_themes_from_titles"])

    def test_preserves_manual_research_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "competitors.csv"
            path.write_text(
                "seller_url,identity_status,inn,analyst_notes\n"
                "https://www.avito.ru/brands/example,confirmed,7712345678,checked\n",
                encoding="utf-8",
            )
            old = MODULE.preserve_manual(path)
            row = old["https://www.avito.ru/brands/example"]
            self.assertEqual(row["identity_status"], "confirmed")
            self.assertEqual(row["inn"], "7712345678")

    def test_explicit_ip_name_wins_over_profile_label(self):
        row = MODULE.extract_evidence(
            "ИП Лебедев Александр Александрович",
            "https://www.avito.ru/brands/example",
            {"texts": ["Частный исполнитель"], "titles": []},
        )
        self.assertEqual(row["avito_profile_type"], "ИП")

    def test_accepts_extension_seller_export(self):
        rows = MODULE.normalize_seller_rows(
            [{"seller_url": "https://www.avito.ru/brands/example", "seller": "Компания", "listing_count": "12"}]
        )
        self.assertEqual(rows[0]["core_listings"], "12")
        self.assertEqual(rows[0]["first_page_slot_share_pct"], "0")


if __name__ == "__main__":
    unittest.main()
