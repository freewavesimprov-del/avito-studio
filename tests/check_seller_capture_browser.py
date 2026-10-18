"""Verify seller profile parsing and requisites disclosure in Chromium."""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT/'browser-extension'/'seller-capture.js').read_text()
HTML = '''<!doctype html><html><body>
<h1 data-marker="profile-title">ГидроПро</h1>
<div>5,0<br>17 отзывов клиентов</div><div>Компания</div><div>На Авито c 2019 года</div>
<div>42 объявления пользователя</div><div>Контактное лицо\nИван Петров</div>
</body></html>'''
LISTING_HTML = '''<!doctype html><html><body>
<h1>Инъекционная гидроизоляция</h1><p>Подробное описание услуги по гидроизоляции, ремонту конструкций и устранению протечек в здании.</p><div>Профилем владеет компания</div>
<button id="requisites">Реквизиты проверены</button>
<div id="modal" role="dialog" style="display:none">ООО «ГИДРОПРО»\nИНН 7712345678\nОГРН 1234567890123\nКПП 771201001\nЮридический адрес:\nМосква, Тестовая улица, 1</div>
<script>document.querySelector('#requisites').onclick=()=>document.querySelector('#modal').style.display='block'</script>
</body></html>'''
with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,executable_path='/usr/bin/chromium')
    page=browser.new_page();page.route('https://www.avito.ru/**',lambda route:route.fulfill(body=LISTING_HTML if '_1234567890' in route.request.url else HTML,content_type='text/html; charset=utf-8'))
    page.goto('https://www.avito.ru/brands/gidropro')
    capture=page.evaluate(SCRIPT);assert capture['kind']=='seller';profile=capture['profile']
    assert profile['seller']=='ГидроПро' and profile['listingsTotal']==42 and profile['reviews']==17
    page.goto('https://www.avito.ru/moskva/predlozheniya_uslug/injekcionnaya_gidroizolyaciya_1234567890')
    first=page.evaluate(SCRIPT);assert first['status']=='opening_requisites'
    second=page.evaluate(SCRIPT);assert second['kind']=='requisites';profile=second['profile']
    assert profile['legalName']=='ООО ГИДРОПРО' and profile['inn']=='7712345678' and profile['ogrn']=='1234567890123'
    assert profile['verifiedRequisites'] is True and profile['requisitesCheckedAt']
    browser.close()
print('Seller capture browser fixture passed: profile and listing requisites parsed')
