"""Exercise automatic challenge recovery and unattended error skipping."""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]

def serve(route):
    name=route.request.url.split('/')[-1] or 'automation.html'
    file=ROOT/'browser-extension'/name
    content_type={'js':'application/javascript','html':'text/html','css':'text/css'}.get(file.suffix[1:],'text/plain')
    route.fulfill(body=file.read_text(),content_type=content_type+'; charset=utf-8')

def init_script(mode):
    result = """calls++===0
      ? {kind:'status',status:'challenge',reason:'Авито запрашивает капчу'}
      : {kind:'detail',captureId:'detail-1',at:'2026-10-18T09:00:00Z',url:'https://www.avito.ru/moskva/uslugi/item_123',items:[{id:'123',url:'https://www.avito.ru/moskva/uslugi/item_123',title:'Гидроизоляция',description:'Описание',images:[],missingFields:[]}]}""" if mode=='challenge' else """({kind:'status',status:'transient',reason:'Временная ошибка страницы'})"""
    return f'''
      let fakeNow=0;Date.now=()=>{{fakeNow+=5000;return fakeNow;}};
      const nativeTimeout=setTimeout;window.setTimeout=(fn)=>nativeTimeout(fn,0);
      const research={{version:2,queries:['q'],region:'moskva_i_mo',captures:[],listings:{{
        '123':{{id:'123',url:'https://www.avito.ru/moskva/uslugi/item_123',firstSeen:'2026-10-18T08:00:00Z',card:{{id:'123',url:'https://www.avito.ru/moskva/uslugi/item_123',title:'Гидроизоляция'}}}}
      }}}};let db={{research}},nextTab=10,calls=0;
      window.chrome={{storage:{{local:{{get:async()=>structuredClone(db),set:async v=>Object.assign(db,structuredClone(v))}}}},
        tabs:{{getCurrent:async()=>({{id:1}}),update:async(id,o)=>({{id,...o}}),create:async o=>({{id:nextTab++,...o}}),get:async id=>({{id,status:'complete'}}),remove:async()=>{{}}}},
        scripting:{{executeScript:async()=>[{{result:{result}}}]}}}};
    '''

with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,executable_path='/usr/bin/chromium')
    for mode in ['challenge','ordinary']:
        page=browser.new_page(viewport={'width':920,'height':900})
        page.add_init_script(init_script(mode));page.route('https://extension.test/**',serve)
        page.goto('https://extension.test/automation.html');page.locator('#limit').fill('1');page.locator('#start').click()
        page.locator('#status').filter(has_text='Серия завершена').wait_for()
        journal=page.locator('#log').inner_text()
        if mode=='challenge':
            assert 'Требуется капча' in journal and 'Сохранено: Гидроизоляция' in journal
            assert 'Подробно сохранено: 1' in page.locator('#summary').inner_text()
        else:
            assert 'Автопропуск' in journal and 'автоматически пропущено 1' in page.locator('#status').inner_text()
        page.close()
    browser.close()
print('Automation resilience UI passed: challenge recovery and ordinary error auto-skip')
