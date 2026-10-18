"""Exercise one automated seller profile capture with mocked Chrome APIs."""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, executable_path='/usr/bin/chromium')
    page = browser.new_page(viewport={'width': 920, 'height': 900})
    page.add_init_script('''
      const profileURL='https://www.avito.ru/brands/gidropro';
      const listingURL='https://www.avito.ru/moskva/uslugi/inject_123';
      const research={version:3,queries:['q'],region:'moskva_i_mo',captures:[{kind:'search',captureId:'s',at:'2026-10-18T10:00:00Z',url:'https://www.avito.ru/moskva_i_mo/predlozheniya_uslug?q=q',query:'q',region:'moskva_i_mo',page:'1',sort:'default',items:[{id:'123',url:listingURL,title:'Инъектирование',position:1}]}],sellerProfiles:{},listings:{'123':{id:'123',url:listingURL,firstSeen:'2026-10-18T10:00:00Z',lastSeen:'2026-10-18T10:00:00Z',card:{id:'123',url:listingURL,title:'Инъектирование',seller:'ГидроПро',sellerURL:profileURL}}}};
      let db={research};let nextTab=10;
      window.chrome={runtime:{getURL:path=>'https://extension.test/'+path},storage:{local:{get:async()=>structuredClone(db),set:async value=>Object.assign(db,structuredClone(value))}},tabs:{getCurrent:async()=>({id:1}),update:async(id,opts)=>({id,...opts}),create:async opts=>({id:nextTab++,...opts}),get:async id=>({id,status:'complete'}),remove:async()=>{}},scripting:{executeScript:async()=>[{result:{kind:'seller',at:'2026-10-18T11:00:00Z',url:profileURL,profile:{url:profileURL,seller:'ГидроПро',profileType:'Компания',listingsTotal:10,verifiedRequisites:true,legalName:'ООО ГИДРОПРО',inn:'7712345678',badges:['Реквизиты проверены']}}}]}};
    ''')
    def serve(route):
        name=route.request.url.split('/')[-1] or 'seller-automation.html'
        file=ROOT/'browser-extension'/name
        content_type={'js':'application/javascript','html':'text/html','css':'text/css'}.get(file.suffix[1:],'text/plain')
        route.fulfill(body=file.read_text(),content_type=content_type+'; charset=utf-8')
    page.route('https://extension.test/**',serve)
    page.goto('https://extension.test/seller-automation.html')
    assert 'Уникальных профилей: 1' in page.locator('#summary').inner_text()
    page.locator('#limit').fill('1');page.locator('#start').click()
    page.locator('#status').filter(has_text='Серия завершена').wait_for()
    assert 'Сохранено: 1' in page.locator('#summary').inner_text()
    assert 'ИНН 7712345678' in page.locator('#log').inner_text()
    browser.close()
print('Seller automation UI passed: queue, profile capture and persistence')
