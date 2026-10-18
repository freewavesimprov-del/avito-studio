import {mergeCapture, normalizeState, enabledQueries, searchPageURL, searchScanSettings, checkSearchCapture} from './core.js';

const $=id=>document.getElementById(id);
let research=normalizeState((await chrome.storage.local.get('research')).research);
let controllerTabId=(await chrome.tabs.getCurrent())?.id;
let workerTabId=null,queue=[],current=null,settings=null;
let completed=0,skipped=0,stopRequested=false,userPaused=false,running=false;
const endedQueries=new Set();
if(controllerTabId)try{await chrome.tabs.update(controllerTabId,{autoDiscardable:false});}catch{}

class PageIssue extends Error{constructor(type,message){super(message);this.type=type;}}
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const tabExists=async id=>{try{return await chrome.tabs.get(id);}catch{return null;}};
const setStatus=text=>{$('status').textContent=text;};
const log=text=>{const li=document.createElement('li');li.textContent=`${new Date().toLocaleTimeString()} — ${text}`;$('log').prepend(li);};
const targetKey=t=>`${t.query}\u0000${t.page}\u0000${t.sort}`;
const captureKey=c=>`${c.query}\u0000${c.page}\u0000${c.sort}`;
const closeWorker=async()=>{if(workerTabId&&await tabExists(workerTabId))try{await chrome.tabs.remove(workerTabId);}catch{}workerTabId=null;if(controllerTabId)try{await chrome.tabs.update(controllerTabId,{active:true});}catch{}};
const bounded=(promise,milliseconds)=>new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('Chrome не ответил на чтение вкладки')),milliseconds);promise.then(value=>{clearTimeout(timer);resolve(value);},error=>{clearTimeout(timer);reject(error);});});

function renderQueries(){
  $('queries').replaceChildren(...enabledQueries(research,'avito').map((query,index)=>{
    const label=document.createElement('label');const input=document.createElement('input');input.type='checkbox';input.checked=true;input.value=query;input.id=`query-${index}`;
    label.append(input,document.createTextNode(query));return label;
  }));
}
const selectedQueries=()=>[...$('queries').querySelectorAll('input:checked')].map(x=>x.value);
async function reloadResearch(showMessage=false){
  if(running)return;research=normalizeState((await chrome.storage.local.get('research')).research||research);renderQueries();refresh();
  if(showMessage)setStatus(`Список обновлён: для Авито включено ${enabledQueries(research,'avito').length} фраз.`);
}
function refresh(){
  const searches=(research?.captures||[]).filter(c=>c.kind==='search');
  $('summary').textContent=`Сохранений выдачи: ${searches.length} · Уникальных объявлений: ${Object.keys(research?.listings||{}).length}`;
  $('bar').style.width=`${queue.length?Math.min(100,100*(completed+skipped)/queue.length):0}%`;
}
async function waitCountdown(seconds,label){
  const until=Date.now()+seconds*1000;
  while(Date.now()<until&&!stopRequested){
    while(userPaused&&!stopRequested){setStatus('Пауза. Нажмите «Продолжить».');await sleep(250);}
    if(stopRequested)break;
    setStatus(`${label}: ${Math.max(1,Math.ceil((until-Date.now())/1000))} сек.`);await sleep(Math.min(500,Math.max(1,until-Date.now())));
  }
}
async function readCapture(tabId){
  const result=await bounded(chrome.scripting.executeScript({target:{tabId},files:['capture.js']}),4000);
  return result[0]?.result;
}
async function waitForSearch(tabId,target,seconds){
  const deadline=Date.now()+seconds*1000;let lastError='Страница ещё загружается';
  while(Date.now()<deadline&&!stopRequested){
    if(!await tabExists(tabId))throw new PageIssue('ordinary','Рабочая вкладка была закрыта');
    try{
      const capture=await readCapture(tabId);
      if(capture?.kind==='status'&&capture.status==='challenge')throw new PageIssue('challenge',capture.reason);
      const check=checkSearchCapture(capture,target);if(check.ok)return capture;lastError=capture?.reason||check.reason;
    }catch(error){if(error?.type==='challenge')throw error;lastError=error?.message||String(error);}
    setStatus(`Ждём выдачу: ${target.query}, стр. ${target.page} · ${Math.max(1,Math.ceil((deadline-Date.now())/1000))} сек. · ${lastError}`);
    await sleep(Math.min(1000,Math.max(1,deadline-Date.now())));
  }
  if(stopRequested)throw new PageIssue('stop','Остановлено пользователем');
  throw new PageIssue('ordinary',lastError);
}
async function waitForChallenge(tabId,target){
  const deadline=Date.now()+settings.challengeTimeout*1000;$('problem').hidden=false;
  while(Date.now()<deadline&&!stopRequested){
    const left=Math.max(1,Math.ceil((deadline-Date.now())/1000));
    $('problemText').textContent=`Ожидаем решение для «${target.query}», стр. ${target.page}. Осталось ${left} сек.`;
    setStatus(`Нужна капча: осталось ${left} сек. После успешной проверки сбор продолжится сам.`);
    if(!await tabExists(tabId))throw new PageIssue('ordinary','Рабочая вкладка была закрыта');
    try{const capture=await readCapture(tabId);if(checkSearchCapture(capture,target).ok)return capture;}catch{}
    await sleep(Math.min(1000,Math.max(1,deadline-Date.now())));
  }
  if(stopRequested)throw new PageIssue('stop','Остановлено пользователем');
  throw new PageIssue('challenge-timeout','Капча не пройдена за отведённое время');
}
async function openCurrent(){
  if(!workerTabId||!await tabExists(workerTabId)){const tab=await chrome.tabs.create({url:current.url,active:true});workerTabId=tab.id;}
  else await chrome.tabs.update(workerTabId,{active:true});
}
async function save(capture){
  capture.scanId=settings.scanId;const stored=normalizeState((await chrome.storage.local.get('research')).research||research);
  research=mergeCapture(stored,capture);await chrome.storage.local.set({research});
}
async function finishCapture(capture){
  await save(capture);completed++;log(`Сохранено: ${current.query}, стр. ${current.page}, карточек ${capture.items.length}`);
  if(capture.items.length<20){endedQueries.add(current.query);log(`Дальнейшие страницы «${current.query}» пропущены: выдача закончилась.`);}
  $('problem').hidden=true;await closeWorker();refresh();
}

async function run(){
  running=true;$('start').disabled=true;$('pause').disabled=false;$('stop').disabled=false;
  try{
    for(current of queue){
      if(stopRequested)break;if(endedQueries.has(current.query)){skipped++;continue;}
      while(userPaused&&!stopRequested)await sleep(250);
      let done=false,challengeRetries=0;
      while(!done&&!stopRequested){
        try{
          setStatus(`Открываем ${completed+skipped+1} из ${queue.length}: ${current.query}, стр. ${current.page}`);
          await openCurrent();const capture=await waitForSearch(workerTabId,current,settings.timeout);await finishCapture(capture);done=true;
        }catch(error){
          if(stopRequested||error?.type==='stop')break;
          if(error?.type==='challenge'){
            log(`Требуется капча: ${current.query}, стр. ${current.page}`);
            try{const capture=await waitForChallenge(workerTabId,current);await finishCapture(capture);done=true;continue;}
            catch(challengeError){
              if(stopRequested||challengeError?.type==='stop')break;
              $('problem').hidden=true;await closeWorker();
              if(challengeRetries<settings.challengeRetries){challengeRetries++;log(`Капча не пройдена. Повтор ${challengeRetries} из ${settings.challengeRetries} после паузы.`);await waitCountdown(settings.challengeCooldown,'Пауза после капчи');continue;}
              skipped++;done=true;log(`Автопропуск после капчи: ${current.query}, стр. ${current.page}`);refresh();continue;
            }
          }
          skipped++;done=true;$('problem').hidden=true;log(`Автопропуск: ${current.query}, стр. ${current.page} · ${error?.message||String(error)}`);await closeWorker();refresh();
        }
      }
      if(!stopRequested&&completed+skipped<queue.length)await waitCountdown(settings.interval,'Следующая страница через');
    }
  }finally{
    await closeWorker();$('problem').hidden=true;running=false;$('start').disabled=false;$('pause').disabled=true;$('stop').disabled=true;$('pause').textContent='Пауза';userPaused=false;
    setStatus(stopRequested?`Остановлено. Сохранено ${completed}, пропущено ${skipped}.`:`Серия завершена. Сохранено ${completed}, автоматически пропущено ${skipped}.`);
    research=normalizeState((await chrome.storage.local.get('research')).research||research);refresh();
  }
}

$('start').onclick=async()=>{
  try{
    if(!research)throw Error('Сначала сохраните или импортируйте данные расширения');
    const queries=selectedQueries();if(!queries.length)throw Error('Выберите хотя бы один запрос');
    settings={...searchScanSettings({firstPage:$('firstPage').value,lastPage:$('lastPage').value,interval:$('interval').value,timeout:$('timeout').value,sort:$('sort').value,challengeTimeout:$('challengeTimeout').value,challengeCooldown:$('challengeCooldown').value,challengeRetries:$('challengeRetries').value}),scanId:crypto.randomUUID()};
    const existing=new Set((research.captures||[]).filter(c=>c.kind==='search').map(captureKey));queue=[];
    for(const query of queries)for(let page=settings.firstPage;page<=settings.lastPage;page++){
      const target={query,page:String(page),sort:settings.sort,region:research.region,url:searchPageURL(query,research.region,page,settings.sort)};
      if(!$('skipExisting').checked||!existing.has(targetKey(target)))queue.push(target);
    }
    if(!queue.length)throw Error('Все выбранные страницы уже сохранены. Отключите пропуск для нового снимка.');
    completed=0;skipped=0;stopRequested=false;userPaused=false;endedQueries.clear();$('log').replaceChildren();refresh();await run();
  }catch(error){setStatus(error?.message||String(error));}
};
$('pause').onclick=()=>{userPaused=!userPaused;$('pause').textContent=userPaused?'Продолжить':'Пауза';};
$('stop').onclick=async()=>{stopRequested=true;await closeWorker();};
$('selectAll').onclick=()=>[...$('queries').querySelectorAll('input')].forEach(x=>x.checked=true);
$('selectNone').onclick=()=>[...$('queries').querySelectorAll('input')].forEach(x=>x.checked=false);
$('reloadQueries').onclick=()=>reloadResearch(true);
chrome.storage.onChanged?.addListener((changes,area)=>{if(area==='local'&&changes.research&&!running)reloadResearch(true);});
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&!running)reloadResearch(false);});
renderQueries();refresh();
