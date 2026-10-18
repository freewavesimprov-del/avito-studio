import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("clean_research.py")
SPEC = importlib.util.spec_from_file_location("clean_research", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
classify_direct = MODULE.classify_direct
query_report = MODULE.query_report
split_backup = MODULE.split_backup


def listing(title, description="", parameters="", detail=True):
    card = {"id": "1", "title": title, "url": "https://www.avito.ru/moskva/item_1"}
    value = {"id": "1", "url": card["url"], "card": card}
    if detail:
        value["detail"] = {**card, "description": description, "parametersText": parameters, "rawText": description}
    return value


class CleanResearchTests(unittest.TestCase):
    def test_injection_service_wins_over_wrong_product_category(self):
        value = listing(
            "Гидроизоляция подвалов, паркингов, инъектирование",
            "Выполняем работы с гарантией",
            "Характеристики\nСостояние: Новое\nТип гидроизоляции: Цементная",
        )
        self.assertEqual(classify_direct(value)["decision"], "core")

    def test_waterproofing_service_is_relevant(self):
        value = listing(
            "Гидроизоляция крыши гаража",
            "Выполняем ремонт и монтаж",
            "Подробности\nРаботы: Гидроизоляция\nГарантия на работу: Есть",
        )
        self.assertEqual(classify_direct(value)["decision"], "relevant")

    def test_material_and_equipment_are_irrelevant(self):
        material = listing("Гидроизоляция Кнауф Флэхендихт 5 кг", "В наличии", "Характеристики\nСостояние: Новое")
        equipment = listing("Аренда инъекционного насоса", "Оборудование в наличии")
        self.assertEqual(classify_direct(material)["decision"], "irrelevant")
        self.assertEqual(classify_direct(equipment)["decision"], "irrelevant")

    def test_unrelated_service_is_irrelevant(self):
        value = listing("Монтаж отопления и тёплых полов", "Работаем по договору", "Подробности\nГарантия на работу: Есть")
        self.assertEqual(classify_direct(value)["decision"], "irrelevant")

    def test_leak_detection_and_dealer_ads_are_irrelevant(self):
        leak = listing("Поиск скрытой утечки воды. Устранение протечки", "Работаем по договору")
        dealer = listing("Ищем дилеров. Гидроизоляция", "Выгодные условия сотрудничества")
        self.assertEqual(classify_direct(leak)["decision"], "irrelevant")
        self.assertEqual(classify_direct(dealer)["decision"], "irrelevant")

    def test_pending_waterproofing_service_stays_in_queue(self):
        value = listing("Гидроизоляция подвала и фундамента", detail=False)
        self.assertEqual(classify_direct(value)["decision"], "relevant")

    def test_noisy_query_is_disabled(self):
        captures = [
            {"kind": "search", "query": "система защиты от протечек", "page": "1", "sort": "default", "items": [{"id": "1"}, {"id": "2"}]},
            {"kind": "search", "query": "инъекционная гидроизоляция", "page": "1", "sort": "default", "items": [{"id": "3"}, {"id": "4"}]},
        ]
        decisions = {"1": {"decision": "irrelevant"}, "2": {"decision": "irrelevant"}, "3": {"decision": "core"}, "4": {"decision": "relevant"}}
        rows = {row["query"]: row for row in query_report(captures, decisions)}
        self.assertEqual(rows["система защиты от протечек"]["recommendation"], "disable")
        self.assertEqual(rows["инъекционная гидроизоляция"]["recommendation"], "keep")

    def test_product_intent_query_is_disabled_even_with_relevant_results(self):
        captures = [{"kind": "search", "query": "инъекционный насос для гидроизоляции", "page": "1", "sort": "default", "items": [{"id": "1"}]}]
        rows = query_report(captures, {"1": {"decision": "core"}})
        self.assertEqual(rows[0]["recommendation"], "disable")

    def test_backup_parts_respect_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = split_backup(Path(directory), "clean", {"queries": [], "queryMeta": {}, "sellerProfiles": {}, "wordstat": {}}, {"1": listing("Гидроизоляция")}, [], "2026-10-18T00:00:00Z", 1024 * 1024)
            self.assertEqual(len(paths), 1)
            self.assertLess(paths[0].stat().st_size, 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
