"""Exercise one automated detail capture with mocked Chrome APIs."""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, executable_path='/usr/bin/chromium')
    page = browser.new_page(viewport={'width': 920, 'height': 900})
    page.add_init_script('''
      const research={version:1,queries:['q'],region:'moskva_i_mo',captures:[],listings:{
        '123':{id:'123',url:'https://www.avito.ru/moskva/uslugi/inject_123',firstSeen:'2026-10-17T10:00:00Z',lastSeen:'2026-10-17T10:00:00Z',card:{id:'123',url:'https://www.avito.ru/moskva/uslugi/inject_123',title:'Инъектирование швов'}}
      }};
      let db={research}; let nextTab=10;
      window.chrome={
        runtime:{getURL:path=>'https://extension.test/'+path},
        storage:{local:{get:async key=>structuredClone(db),set:async value=>Object.assign(db,structuredClone(value))}},
        tabs:{
          getCurrent:async()=>({id:1}), update:async(id,opts)=>({id,...opts}),
          create:async opts=>({id:nextTab++,status:'loading',...opts}), get:async id=>({id,status:'complete'}), remove:async()=>{}
        },
        scripting:{executeScript:async()=>[{result:{kind:'detail',captureId:'detail-1',at:'2026-10-17T11:00:00Z',url:'https://www.avito.ru/moskva/uslugi/inject_123',items:[{id:'123',url:'https://www.avito.ru/moskva/uslugi/inject_123',title:'Инъектирование швов',description:'Полное описание',images:[],missingFields:['images']}]}}]}
      };
    ''')
    def serve(route):
        name=route.request.url.split('/')[-1] or 'automation.html'
        file=ROOT/'browser-extension'/name
        content_type={'js':'application/javascript','html':'text/html','css':'text/css'}.get(file.suffix[1:],'text/plain')
        route.fulfill(body=file.read_text(),content_type=content_type+'; charset=utf-8')
    page.route('https://extension.test/**',serve)
    page.goto('https://extension.test/automation.html')
    assert 'В очереди: 1' in page.locator('#summary').inner_text()
    page.locator('#limit').fill('1')
    page.locator('#start').click()
    page.locator('#status').filter(has_text='Серия завершена').wait_for()
    assert 'Подробно сохранено: 1' in page.locator('#summary').inner_text()
    assert 'Сохранено: Инъектирование швов' in page.locator('#log').inner_text()
    browser.close()
print('Automation UI passed: pending queue, capture, persistence and completion')
