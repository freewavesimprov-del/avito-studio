"""Exercise one automatic search capture with mocked Chrome APIs."""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,executable_path='/usr/bin/chromium')
    page=browser.new_page(viewport={'width':920,'height':900})
    page.add_init_script('''
      const research={version:1,queries:['инъектирование'],region:'moskva_i_mo',captures:[],listings:{}};
      let db={research};let nextTab=10;
      window.chrome={storage:{local:{get:async()=>structuredClone(db),set:async v=>Object.assign(db,structuredClone(v))}},tabs:{getCurrent:async()=>({id:1}),update:async(id,o)=>({id,...o}),create:async o=>({id:nextTab++,...o}),get:async id=>({id,status:'complete'}),remove:async()=>{}},scripting:{executeScript:async()=>[{result:{kind:'search',captureId:'search-1',at:'2026-10-17T12:00:00Z',url:'https://www.avito.ru/moskva_i_mo/predlozheniya_uslug?q=инъектирование&p=1',query:'инъектирование',region:'moskva_i_mo',page:'1',sort:'default',items:[{id:'123',url:'https://www.avito.ru/moskva/uslugi/inject_123',title:'Инъектирование',position:1}]}}]}};
    ''')
    def serve(route):
        name=route.request.url.split('/')[-1] or 'search-automation.html';file=ROOT/'browser-extension'/name
        content_type={'js':'application/javascript','html':'text/html','css':'text/css'}.get(file.suffix[1:],'text/plain')
        route.fulfill(body=file.read_text(),content_type=content_type+'; charset=utf-8')
    page.route('https://extension.test/**',serve);page.goto('https://extension.test/search-automation.html')
    page.locator('#lastPage').fill('1');page.locator('#start').click()
    page.locator('#status').filter(has_text='Серия завершена').wait_for()
    assert 'Сохранений выдачи: 1' in page.locator('#summary').inner_text()
    assert 'Сохранено: инъектирование, стр. 1' in page.locator('#log').inner_text()
    browser.close()
print('Search automation UI passed: queue, capture, persistence and completion')
