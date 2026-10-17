import {mergeCapture, normalizeState, enabledQueries, searchPageURL, searchScanSettings} from './core.js';

const $=id=>document.getElementById(id);
let research=normalizeState((await chrome.storage.local.get('research')).research);
let controllerTabId=(await chrome.tabs.getCurrent())?.id;
let workerTabId=null,queue=[],current=null,settings=null,decision=null;
let completed=0,skipped=0,stopRequested=false,userPaused=false;
const endedQueries=new Set();
if(controllerTabId)try{await chrome.tabs.update(controllerTabId,{autoDiscardable:false});}catch{}

const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const tabExists=async id=>{try{return await chrome.tabs.get(id);}catch{return null;}};
const setStatus=text=>{$('status').textContent=text;};
const log=text=>{const li=document.createElement('li');li.textContent=`${new Date().toLocaleTimeString()} — ${text}`;$('log').prepend(li);};
const targetKey=t=>`${t.query}\u0000${t.page}\u0000${t.sort}`;
const captureKey=c=>`${c.query}\u0000${c.page}\u0000${c.sort}`;
const closeWorker=async()=>{if(workerTabId&&await tabExists(workerTabId))try{await chrome.tabs.remove(workerTabId);}catch{}workerTabId=null;if(controllerTabId)try{await chrome.tabs.update(controllerTabId,{active:true});}catch{}};

function renderQueries(){
  $('queries').replaceChildren(...enabledQueries(research,'avito').map((query,index)=>{
    const label=document.createElement('label');
    const input=document.createElement('input');input.type='checkbox';input.checked=true;input.value=query;input.id=`query-${index}`;
    label.append(input,document.createTextNode(query));return label;
  }));
}
function selectedQueries(){return [...$('queries').querySelectorAll('input:checked')].map(x=>x.value);}
function refresh(){
  const searches=(research?.captures||[]).filter(c=>c.kind==='search');
  $('summary').textContent=`Сохранений выдачи: ${searches.length} · Уникальных объявлений: ${Object.keys(research?.listings||{}).length}`;
  $('bar').style.width=`${queue.length?Math.min(100,100*(completed+skipped)/queue.length):0}%`;
}
async function waitBetween(seconds){
  const until=Date.now()+seconds*1000;
  while(Date.now()<until&&!stopRequested){
    while(userPaused&&!stopRequested){setStatus('Пауза. Нажмите «Продолжить».');await sleep(250);}
    if(stopRequested)break;
    setStatus(`Следующая страница через ${Math.ceil((until-Date.now())/1000)} сек.`);await sleep(Math.min(500,Math.max(1,until-Date.now())));
  }
}
async function waitForSearch(tabId,target,seconds){
  const deadline=Date.now()+seconds*1000;let lastError='Страница ещё загружается';
  while(Date.now()<deadline&&!stopRequested){
    if(!await tabExists(tabId))throw Error('Рабочая вкладка была закрыта');
    try{
      const result=await chrome.scripting.executeScript({target:{tabId},files:['capture.js']});
      const capture=result[0]?.result;
      if(capture?.kind==='search'&&capture.query===target.query&&String(capture.page)===String(target.page)&&capture.sort===target.sort)return capture;
      lastError='Сайт открыл другую страницу или выдача ещё не готова';
    }catch(error){lastError=error?.message||String(error);}
    await sleep(1000);
  }
  if(stopRequested)throw Error('Остановлено пользователем');throw Error(lastError);
}
async function openCurrent(){
  if(!workerTabId||!await tabExists(workerTabId)){const tab=await chrome.tabs.create({url:current.url,active:true});workerTabId=tab.id;}
  else await chrome.tabs.update(workerTabId,{active:true});
}
async function save(capture){
  capture.scanId=settings.scanId;
  const stored=normalizeState((await chrome.storage.local.get('research')).research||research);
  research=mergeCapture(stored,capture);await chrome.storage.local.set({research});
}
function waitForDecision(error){$('problem').hidden=false;$('problemText').textContent=error;setStatus('Сбор приостановлен: проверьте рабочую вкладку.');return new Promise(resolve=>{decision=resolve;});}

async function run(){
  $('start').disabled=true;$('pause').disabled=false;$('stop').disabled=false;
  try{
    for(current of queue){
      if(stopRequested)break;
      if(endedQueries.has(current.query)){skipped++;continue;}
      while(userPaused&&!stopRequested)await sleep(250);
      setStatus(`Открываем ${completed+skipped+1} из ${queue.length}: ${current.query}, стр. ${current.page}`);
      let done=false;
      while(!done&&!stopRequested){
        try{
          await openCurrent();const capture=await waitForSearch(workerTabId,current,settings.timeout);await save(capture);
          completed++;done=true;log(`Сохранено: ${current.query}, стр. ${current.page}, карточек ${capture.items.length}`);
          if(capture.items.length<20){endedQueries.add(current.query);log(`Дальнейшие страницы «${current.query}» пропущены: выдача закончилась.`);}
          $('problem').hidden=true;await closeWorker();refresh();
        }catch(error){
          if(stopRequested)break;
          const action=await waitForDecision(error?.message||String(error));decision=null;$('problem').hidden=true;
          if(action==='skip'){skipped++;done=true;log(`Пропущено: ${current.query}, стр. ${current.page}`);await closeWorker();}
          if(action==='stop'){stopRequested=true;break;}
        }
      }
      if(!stopRequested&&completed+skipped<queue.length)await waitBetween(settings.interval);
    }
  }finally{
    await closeWorker();$('start').disabled=false;$('pause').disabled=true;$('stop').disabled=true;$('pause').textContent='Пауза';userPaused=false;
    setStatus(stopRequested?`Остановлено. Сохранено ${completed}, пропущено ${skipped}.`:`Серия завершена. Сохранено ${completed}, пропущено ${skipped}.`);
    research=normalizeState((await chrome.storage.local.get('research')).research||research);refresh();
  }
}

$('start').onclick=async()=>{
  try{
    if(!research)throw Error('Сначала сохраните или импортируйте данные расширения');
    const queries=selectedQueries();if(!queries.length)throw Error('Выберите хотя бы один запрос');
    settings={...searchScanSettings({firstPage:$('firstPage').value,lastPage:$('lastPage').value,interval:$('interval').value,timeout:$('timeout').value,sort:$('sort').value}),scanId:crypto.randomUUID()};
    const existing=new Set((research.captures||[]).filter(c=>c.kind==='search').map(captureKey));
    queue=[];
    for(const query of queries)for(let page=settings.firstPage;page<=settings.lastPage;page++){
      const target={query,page:String(page),sort:settings.sort,region:research.region,url:searchPageURL(query,research.region,page,settings.sort)};
      if(!$('skipExisting').checked||!existing.has(targetKey(target)))queue.push(target);
    }
    if(!queue.length)throw Error('Все выбранные страницы уже сохранены. Отключите пропуск для нового снимка.');
    completed=0;skipped=0;stopRequested=false;userPaused=false;endedQueries.clear();$('log').replaceChildren();refresh();await run();
  }catch(error){setStatus(error?.message||String(error));}
};
$('pause').onclick=()=>{userPaused=!userPaused;$('pause').textContent=userPaused?'Продолжить':'Пауза';};
$('stop').onclick=()=>{stopRequested=true;if(decision)decision('stop');};
$('retry').onclick=()=>{if(decision)decision('retry');};
$('skip').onclick=()=>{if(decision)decision('skip');};
$('selectAll').onclick=()=>[...$('queries').querySelectorAll('input')].forEach(x=>x.checked=true);
$('selectNone').onclick=()=>[...$('queries').querySelectorAll('input')].forEach(x=>x.checked=false);
renderQueries();refresh();
