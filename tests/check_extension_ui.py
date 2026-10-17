"""Popup interaction and downloads with mocked Chrome API in real Chromium."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT = Path(__file__).resolve().parents[1]
with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, executable_path='/usr/bin/chromium')
    page = browser.new_page(viewport={'width':760,'height':900})
    page.add_init_script('''
      const db = {};
      window.chrome = {
        storage: {local: {get: async () => structuredClone(db), set: async value => Object.assign(db, structuredClone(value))}},
        tabs: {query: async () => [{id:1,url:'https://www.avito.ru/moskva_i_mo/predlozheniya_uslug?q=инъектирование'}],create:async x=>x},
        scripting: {executeScript: async () => [{result:{kind:'search',captureId:'fixture',at:'2026-10-17T10:00:00Z',url:'https://www.avito.ru/moskva_i_mo/predlozheniya_uslug?q=инъектирование',region:'moskva_i_mo',page:'1',sort:'default',query:'инъектирование',items:[{id:'123',url:'https://www.avito.ru/moskva/uslugi/inject_123',title:'Инъектирование швов',position:1,price:null,seller:'Компания',sellerURL:'https://www.avito.ru/user/company'}]}}]}
      };
    ''')
    def serve(route):
        name=route.request.url.split('/')[-1] or 'popup.html'
        file=ROOT/'browser-extension'/name
        content_type={'js':'application/javascript','html':'text/html','css':'text/css'}.get(file.suffix[1:],'text/plain')
        route.fulfill(body=file.read_text(),content_type=content_type+'; charset=utf-8')
    page.route('https://extension.test/**',serve)
    page.goto('https://extension.test/popup.html')
    page.locator('#capture').click()
    page.locator('#message').filter(has_text='Сохранено 1').wait_for()
    assert 'Объявлений: 1' in page.locator('#stats').inner_text()
    page.locator('#detailTab').click()
    assert page.locator('#listingList').inner_text().startswith('Инъектирование швов')
    page.locator('#exportTab').click()
    with page.expect_download() as download:
        page.locator('#json').click()
    backup=json.loads(Path(download.value.path()).read_text())
    assert len(backup['listings'])==1 and len(backup['captures'])==1
    with page.expect_download() as download:
        page.locator('#sellersCSV').click()
    assert 'Компания' in Path(download.value.path()).read_text(encoding='utf-8-sig')
    restored=backup.copy()
    restored['listings']['456']={'id':'456','url':'https://www.avito.ru/moskva/uslugi/second_456','firstSeen':'2026-10-17T09:00:00Z','lastSeen':'2026-10-17T09:00:00Z','card':{'id':'456','url':'https://www.avito.ru/moskva/uslugi/second_456','title':'Вторая карточка'}}
    page.on('dialog',lambda dialog:dialog.accept())
    page.locator('#importJSON').set_input_files({'name':'backup.json','mimeType':'application/json','buffer':json.dumps(restored).encode()})
    page.locator('#message').filter(has_text='JSON-копия восстановлена').wait_for()
    assert 'Объявлений: 2' in page.locator('#stats').inner_text()
    page.locator('#searchTab').click()
    page.locator('#queries').fill('Инъектирование трещин\nИнъектирование трещин\nГидроизоляция')
    page.locator('#saveSettings').click()
    page.locator('#message').filter(has_text='Список сохранён').wait_for()
    assert page.locator('#queryList .row').count()==2
    page.screenshot(path='/tmp/avito-extension-popup.png',full_page=True)
    browser.close()
print('Popup interactions, settings, JSON and seller CSV downloads passed (Chrome API mocked)')
