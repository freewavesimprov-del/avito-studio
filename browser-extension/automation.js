import {mergeCapture, normalizeState, pendingListings, automationSettings, hasUsableDetail} from './core.js';

const $ = id => document.getElementById(id);
let research = normalizeState((await chrome.storage.local.get('research')).research);
let queue = [];
let current = null;
let workerTabId = null;
let controllerTabId = (await chrome.tabs.getCurrent())?.id;
let stopRequested = false;
let userPaused = false;
let decision = null;
let completed = 0;
let skipped = 0;
let settings = null;

if (controllerTabId) {
  try {await chrome.tabs.update(controllerTabId, {autoDiscardable:false});} catch {}
}

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const log = text => {
  const item=document.createElement('li');
  item.textContent=`${new Date().toLocaleTimeString()} — ${text}`;
  $('log').prepend(item);
};
const setStatus = text => {$('status').textContent=text;};
const tabExists = async id => {try {return await chrome.tabs.get(id);} catch {return null;}};
const focusController = async () => {if(controllerTabId) try {await chrome.tabs.update(controllerTabId,{active:true});} catch {}};
const closeWorker = async () => {
  if(workerTabId && await tabExists(workerTabId)) try {await chrome.tabs.remove(workerTabId);} catch {}
  workerTabId=null;
  await focusController();
};

function refreshSummary() {
  const entries=Object.values(research?.listings || {});
  const pending=pendingListings(research || {listings:{}}).length;
  $('summary').textContent=`Уникальных объявлений: ${entries.length} · Подробно сохранено: ${entries.filter(hasUsableDetail).length} · В очереди: ${pending}`;
  const total=queue.length || 1;
  $('bar').style.width=`${Math.min(100,100*(completed+skipped)/total)}%`;
}

async function waitForDetail(tabId, listing, seconds) {
  const deadline=Date.now()+seconds*1000;
  let lastError='Страница ещё загружается';
  while(Date.now()<deadline && !stopRequested) {
    const tab=await tabExists(tabId);
    if(!tab) throw Error('Рабочая вкладка была закрыта');
    try {
      const result=await chrome.scripting.executeScript({target:{tabId},files:['capture.js']});
      const capture=result[0]?.result;
      if(capture?.kind==='detail' && capture.items?.[0]?.id===listing.id) return capture;
      lastError='Открыта другая страница или объявление ещё не готово';
    } catch(error) {lastError=error?.message || String(error);}
    await sleep(1000);
  }
  if(stopRequested) throw Error('Остановлено пользователем');
  throw Error(lastError);
}

async function saveCapture(capture) {
  const stored=normalizeState((await chrome.storage.local.get('research')).research || research);
  const next=mergeCapture(stored,capture);
  await chrome.storage.local.set({research:next});
  research=next;
}

async function waitBetween(seconds) {
  const until=Date.now()+seconds*1000;
  while(Date.now()<until && !stopRequested) {
    while(userPaused && !stopRequested) {setStatus('Пауза. Нажмите «Продолжить».');await sleep(250);}
    if(stopRequested) break;
    const left=Math.max(0,Math.ceil((until-Date.now())/1000));
    setStatus(`Следующая карточка через ${left} сек.`);
    await sleep(Math.min(500,Math.max(1,until-Date.now())));
  }
}

function waitForDecision(error) {
  $('problem').hidden=false;
  $('problemText').textContent=error;
  setStatus('Автосбор приостановлен: проверьте рабочую вкладку.');
  return new Promise(resolve => {decision=resolve;});
}

async function openCurrent() {
  const existing=workerTabId && await tabExists(workerTabId);
  if(!existing) {
    const tab=await chrome.tabs.create({url:current.url,active:true});
    workerTabId=tab.id;
  } else {
    await chrome.tabs.update(workerTabId,{active:true});
  }
}

async function collectCurrent() {
  await openCurrent();
  return waitForDetail(workerTabId,current,settings.timeout);
}

async function run() {
  $('start').disabled=true;$('pause').disabled=false;$('stop').disabled=false;
  try {
    for(const listing of queue) {
      if(stopRequested) break;
      current=listing;
      while(userPaused && !stopRequested) await sleep(250);
      setStatus(`Открываем ${completed+skipped+1} из ${queue.length}: ${(listing.card?.title || listing.id)}`);
      let saved=false;
      while(!saved && !stopRequested) {
        try {
          const capture=await collectCurrent();
          await saveCapture(capture);
          completed+=1;saved=true;
          log(`Сохранено: ${capture.items[0].title}`);
          $('problem').hidden=true;
          await closeWorker();
          refreshSummary();
        } catch(error) {
          if(stopRequested) break;
          const action=await waitForDecision(error?.message || String(error));
          decision=null;$('problem').hidden=true;
          if(action==='skip') {skipped+=1;log(`Пропущено: ${listing.card?.title || listing.id}`);await closeWorker();break;}
          if(action==='stop') {stopRequested=true;break;}
        }
      }
      if(!stopRequested && completed+skipped<queue.length) await waitBetween(settings.interval);
    }
  } finally {
    await closeWorker();
    $('start').disabled=false;$('pause').disabled=true;$('stop').disabled=true;$('pause').textContent='Пауза';
    userPaused=false;
    setStatus(stopRequested ? `Остановлено. Сохранено ${completed}, пропущено ${skipped}.` : `Серия завершена. Сохранено ${completed}, пропущено ${skipped}.`);
    research=normalizeState((await chrome.storage.local.get('research')).research || research);
    refreshSummary();
  }
}

$('start').onclick=async()=>{
  try {
    if(!research) throw Error('Сначала сохраните хотя бы одну страницу выдачи');
    settings=automationSettings({interval:$('interval').value,timeout:$('timeout').value,limit:Number($('limit').value)});
    queue=pendingListings(research).slice(0,settings.limit);
    if(!queue.length) throw Error('В очереди нет объявлений без подробной карточки');
    completed=0;skipped=0;stopRequested=false;userPaused=false;
    $('log').replaceChildren();refreshSummary();
    await run();
  } catch(error) {setStatus(error?.message || String(error));}
};
$('pause').onclick=()=>{userPaused=!userPaused;$('pause').textContent=userPaused?'Продолжить':'Пауза';if(!userPaused)setStatus('Продолжаем.');};
$('stop').onclick=()=>{stopRequested=true;if(decision)decision('stop');};
$('retry').onclick=()=>{if(decision)decision('retry');};
$('skip').onclick=()=>{if(decision)decision('skip');};

refreshSummary();
