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
        page.wait_for_selector.side_effect = [None, TimeoutError('no cards')]
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
        with patch('playwright.sync_api.sync_playwright', return_value=manager), patch('collect.wait_until'):
            data = collect.collect(cfg, 2)
        self.assertEqual(page.goto.call_count, 2)
        self.assertEqual(page.wait_for_selector.call_count, 2)
        self.assertEqual(len(data['queries'][0]['items']), 50)
        self.assertEqual(data['queries'][0]['status'], 'partial')
        self.assertEqual(data['stop_reason'], 'access_restricted')
        self.assertEqual(data['queries_not_run'], 15)
        ctx.close.assert_called_once()

    def test_persistent_restriction_stops_after_wait(self):
        page = MagicMock()
        page.goto.return_value.status = 200
        page.title.return_value = "Доступ ограничен"
        page.wait_for_selector.side_effect = TimeoutError("no cards")
        with self.assertRaises(collect.AccessRestricted):
            collect.load_listing_page(page, 'https://www.avito.ru/')
        page.wait_for_selector.assert_called_once_with('[data-marker="item"]', state="visible", timeout=45000)

    def test_resume_starts_at_failed_page(self):
        page = MagicMock()
        page.goto.side_effect = [MagicMock(status=200), MagicMock(status=429)]
        page.title.return_value = "Авито"
        page.wait_for_selector.side_effect = [None, TimeoutError('no cards')]
        page.evaluate.return_value = {"total": 100, "items": [
            {"id": str(i), "title": "Инъектирование", "position": i + 1} for i in range(50)]}
        ctx = MagicMock()
        ctx.pages = [page]
        pw = MagicMock()
        pw.chromium.launch_persistent_context.return_value = ctx
        manager = MagicMock()
        manager.__enter__.return_value = pw
        cfg = {**collect.load_config(), "queries": ["инъектирование"], "collect_by_date": False}
        with tempfile.TemporaryDirectory() as temp, patch('playwright.sync_api.sync_playwright', return_value=manager), patch('collect.wait_until') as wait:
            checkpoint = Path(temp) / 'progress.json'
            data = collect.collect(cfg, 2, checkpoint, interval=900)
            self.assertEqual(len(data['queries'][0]['items']), 50)
            saved = json.loads(checkpoint.read_text())
            self.assertEqual(saved['page'], 2)
            self.assertGreater(wait.call_args.args[0], saved['last_request'] + 899)
            page.goto.side_effect = None
            page.goto.return_value.status = 200
            page.evaluate.return_value = {"total": 100, "items": [{"id": "new", "title": "Инъектирование", "position": 1}]}
            page.wait_for_selector.side_effect = None
            page.goto.reset_mock()
            data = collect.collect(cfg, 2, checkpoint, resume=True, interval=1800)
            self.assertEqual(page.goto.call_count, 1)
            self.assertIn('&p=2', page.goto.call_args.args[0])
            wait.assert_called_with(saved['last_request'] + 1800)
            self.assertEqual(len(data['queries'][0]['items']), 51)
            self.assertEqual(data['queries'][0]['status'], 'ok')
            self.assertNotIn('stop_reason', data)
            with self.assertRaises(ValueError):
                collect.collect(cfg, 3, checkpoint, resume=True)

    def test_long_wait_is_interruptible(self):
        with patch('collect.time.time', side_effect=[0, 0, 0, 30, 30, 60, 60, 90]), patch('collect.time.sleep') as sleep:
            collect.wait_until(90)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [30, 30, 30])

    def test_pilot_uses_one_page_and_separate_output(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(collect, 'HERE', Path(temp)), patch('sys.argv', ['collect.py', '--pilot', '--diagnose']), patch('collect.collect', return_value={"queries": []}) as run:
            collect.main()
            cfg, pages, checkpoint, resume, interval, diagnostics, diagnose = run.call_args.args
            self.assertEqual(pages, 1)
            self.assertEqual(len(cfg['queries']), 1)
            self.assertEqual(len(cfg['regions']), 1)
            self.assertFalse(cfg['collect_by_date'])
            self.assertEqual(cfg['price_bands'], [])
            self.assertTrue(checkpoint.parent.name.startswith('pilot-'))
            self.assertTrue(diagnose)

    def test_diagnostics_survive_closed_browser(self):
        page = MagicMock()
        page.title.side_effect = RuntimeError('Browser closed')
        page.screenshot.side_effect = RuntimeError('Browser closed')
        page.url = 'https://www.avito.ru/'
        with tempfile.TemporaryDirectory() as temp:
            path = collect.save_diagnostics(page, Path(temp), {'http_status': 429}, collect.AccessRestricted('access_restricted'))
            data = json.loads(path.read_text())
            self.assertEqual(data['http_status'], 429)
            self.assertIn('screenshot_error', data)
            self.assertIsNone(data['title'])

    def test_http_observation_on_restriction(self):
        page = MagicMock()
        page.goto.return_value.status = 429
        page.wait_for_selector.side_effect = TimeoutError('no cards')
        page.goto.return_value.url = 'https://www.avito.ru/blocked'
        page.goto.return_value.headers = {'retry-after': '600'}
        observation = {}
        with self.assertRaises(collect.AccessRestricted):
            collect.load_listing_page(page, 'https://www.avito.ru/', observation)
        self.assertEqual(observation['http_status'], 429)
        self.assertEqual(observation['retry_after'], '600')
        page.wait_for_selector.assert_called_once_with('[data-marker="item"]', state="visible", timeout=45000)

    def test_intermediate_restriction_with_cards_is_success(self):
        page = MagicMock()
        page.goto.return_value.status = 439
        page.goto.return_value.headers = {}
        page.title.return_value = "Доступ ограничен: проверка безопасности"
        observation = {}
        collect.load_listing_page(page, 'https://www.avito.ru/', observation)
        self.assertTrue(observation['listing_ready'])
        page.goto.assert_called_once()
        page.wait_for_selector.assert_called_once_with('[data-marker="item"]', state="visible", timeout=45000)

    def test_browser_waits_for_delayed_cards_after_439(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, executable_path=os.environ.get('COLLECTOR_BROWSER') or None)
            page = browser.new_page()
            page.route('https://example.test/**', lambda route: route.fulfill(status=439, content_type='text/html; charset=utf-8', body='''<title>Доступ ограничен: проверка безопасности</title><body>Проверка пройдена, перенаправление…
                <script>setTimeout(() => { document.title = 'Объявления'; document.body.innerHTML = '<div data-marker="item">Карточка</div>'; }, 200);</script></body>'''))
            observation = {}
            collect.load_listing_page(page, 'https://example.test/search', observation)
            self.assertTrue(observation['listing_ready'])
            self.assertEqual(observation['http_status'], 439)
            self.assertEqual(page.title(), 'Объявления')
            browser.close()

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
            with tempfile.TemporaryDirectory() as temp:
                report = collect.save_diagnostics(page, Path(temp), {"http_status": 200}, RuntimeError('fixture'))
                diagnostic = json.loads(report.read_text())
                self.assertEqual(diagnostic['http_status'], 200)
                self.assertTrue((Path(temp) / diagnostic['screenshot']).is_file())
            browser.close()


if __name__ == '__main__':
    unittest.main()
