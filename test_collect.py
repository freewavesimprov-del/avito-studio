import unittest
import os
import tempfile
import csv
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import collect
from playwright.sync_api import sync_playwright


class CollectorTests(unittest.TestCase):
    def test_service_labels(self):
        for title, expected in [
            ('Инъектирование трещин подвала', 'injection'),
            ('Инъекционный насос в аренду', 'equipment_or_materials'),
            ('Гидроизоляция фундамента', 'related'),
            ('Комод', 'uncertain'),
        ]:
            with self.subTest(title=title):
                self.assertEqual(collect.service_metadata({'title': title})['relevance'], expected)

    def test_moscow_and_no_embedded_token(self):
        cfg = collect.load_config()
        self.assertEqual([r['slug'] for r in cfg['regions']], ['moskva_i_mo'])
        self.assertNotIn('token', cfg)
        self.assertNotIn('panel_url', cfg)

    def test_local_exports(self):
        payload = {"queries": [{"query": "инъектирование", "region": "Москва",
                   "mode": "ranked", "status": "ok", "items": [
                   {"id": "123", "title": "=опасная формула", "price": None,
                    "url": "/moskva/uslugi/test_123"}]}]}
        with tempfile.TemporaryDirectory() as temp:
            snapshot, table = collect.save_results(payload, Path(temp))
            self.assertEqual(json.loads(snapshot.read_text()), payload)
            with table.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0]['title'].startswith("'="))
            self.assertEqual(rows[0]['url'], 'https://www.avito.ru/moskva/uslugi/test_123')

    def test_access_restricted_stops_entire_run_and_retains_first_page(self):
        page = MagicMock()
        page.goto.side_effect = [MagicMock(status=200), MagicMock(status=429)]
        page.title.return_value = "Авито"
        page.evaluate.return_value = {"total": 100, "items": [
            {"id": str(i), "title": "Инъектирование трещин", "position": i + 1}
            for i in range(50)]}
        ctx = MagicMock()
        ctx.pages = [page]
        pw = MagicMock()
        pw.chromium.launch_persistent_context.return_value = ctx
        manager = MagicMock()
        manager.__enter__.return_value = pw
        cfg = collect.load_config()
        with patch('playwright.sync_api.sync_playwright', return_value=manager), patch('collect.time.sleep'):
            data = collect.collect(cfg, 2)
        self.assertEqual(page.goto.call_count, 2)
        self.assertEqual(page.wait_for_selector.call_count, 1)
        self.assertEqual(len(data['queries'][0]['items']), 50)
        self.assertEqual(data['queries'][0]['status'], 'partial')
        self.assertEqual(data['stop_reason'], 'access_restricted')
        self.assertEqual(data['queries_not_run'], 15)
        ctx.close.assert_called_once()

    def test_restriction_in_title_stops_before_wait(self):
        page = MagicMock()
        page.goto.return_value.status = 200
        page.title.return_value = "Доступ ограничен"
        with self.assertRaises(collect.AccessRestricted):
            collect.load_listing_page(page, 'https://www.avito.ru/')
        page.wait_for_selector.assert_not_called()

    def test_extract_real_dom(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, executable_path=os.environ.get('COLLECTOR_BROWSER') or None)
            page = browser.new_page()
            page.set_content('''<span data-marker="page-title/count">2 объявления</span>
              <article data-marker="item"><a href="/user/wrong_thing">Компания</a>
                <a data-marker="item-title" href="/moskva/uslugi/injection_123?x=1"><h3 itemprop="name">Инъектирование трещин</h3></a>
                <div>от <span itemprop="price" content="1500.50">1500,50 ₽</span> за пог. м</div>
              </article>
              <article data-marker="item"><a data-marker="item-title" href="/moskva/uslugi/seams_456"><h3 itemprop="name">Гидроизоляция швов</h3></a>
                <span itemprop="price" content="">Договорная</span>
              </article>''')
            data = page.evaluate(collect.EXTRACT_JS)
            self.assertEqual(data['total'], 2)
            a, b = data['items']
            self.assertEqual(a['id'], '123')
            self.assertEqual(a['price'], 1500.5)
            self.assertTrue(a['price_from'])
            self.assertEqual(a['price_unit'], 'linear_m')
            self.assertIsNone(b['price'])
            self.assertEqual(b['price_unit'], 'unspecified')
            browser.close()


if __name__ == '__main__':
    unittest.main()
