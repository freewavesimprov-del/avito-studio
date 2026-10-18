import {normalizeState,mergeSellerCapture,pendingSellerProfiles,automationSettings} from './core.js';

const $=id=>document.getElementById(id);const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let research=normalizeState((await chrome.storage.local.get('research')).research);let queue=[],current=null,workerTabId=null,settings=null;
let controllerTabId=(await chrome.tabs.getCurrent())?.id;let stopRequested=false,userPaused=false,completed=0,skipped=0;
if(controllerTabId)try{await chrome.tabs.update(controllerTabId,{autoDiscardable:false});}catch{}
class PageIssue extends Error{constructor(type,message){super(message);this.type=type;}}
const setStatus=value=>{$('status').textContent=value;};
const log=value=>{const item=document.createElement('li');item.textContent=`${new Date().toLocaleTimeString()} — ${value}`;$('log').prepend(item);};
const tabExists=async id=>{try{return await chrome.tabs.get(id);}catch{return null;}};
const bounded=(promise,milliseconds)=>new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('Chrome не ответил на чтение вкладки')),milliseconds);promise.then(value=>{clearTimeout(timer);resolve(value);},error=>{clearTimeout(timer);reject(error);});});
const focusController=async()=>{if(controllerTabId)try{await chrome.tabs.update(controllerTabId,{active:true});}catch{}};
const closeWorker=async()=>{if(workerTabId&&await tabExists(workerTabId))try{await chrome.tabs.remove(workerTabId);}catch{}workerTabId=null;await focusController();};
function refreshSummary(){
  const all=pendingSellerProfiles(research,true);const saved=all.filter(row=>row.profile_captured).length;
  $('summary').textContent=`Уникальных профилей: ${all.length} · Сохранено: ${saved} · Осталось без профиля: ${all.length-saved}`;
  $('bar').style.width=`${Math.min(100,100*(completed+skipped)/(queue.length||1))}%`;
}
async function readCapture(tabId){const result=await bounded(chrome.scripting.executeScript({target:{tabId},files:['seller-capture.js']}),5000);return result[0]?.result;}
async function waitForSeller(tabId,target,seconds){
  const deadline=Date.now()+seconds*1000;let lastError='Профиль ещё загружается';
  while(Date.now()<deadline&&!stopRequested){
    if(!await tabExists(tabId))throw new PageIssue('ordinary','Рабочая вкладка была закрыта');
    try{const capture=await readCapture(tabId);if(capture?.kind==='seller'&&capture.url===target.seller_url)return capture;if(capture?.kind==='status'&&capture.status==='challenge')throw new PageIssue('challenge',capture.reason);lastError=capture?.reason||'Профиль пока не распознан';}
    catch(error){if(error?.type==='challenge')throw error;lastError=error?.message||String(error);}
    setStatus(`Ждём профиль: ${target.seller||target.seller_url} · ${Math.max(1,Math.ceil((deadline-Date.now())/1000))} сек. · ${lastError}`);await sleep(Math.min(1000,Math.max(1,deadline-Date.now())));
  }
  if(stopRequested)throw new PageIssue('stop','Остановлено пользователем');throw new PageIssue('ordinary',lastError);
}
async function waitForChallenge(tabId,target){
  const deadline=Date.now()+settings.challengeTimeout*1000;$('problem').hidden=false;
  while(Date.now()<deadline&&!stopRequested){const left=Math.max(1,Math.ceil((deadline-Date.now())/1000));$('problemText').textContent=`Ожидаем решение для «${target.seller||target.seller_url}». Осталось ${left} сек.`;setStatus(`Нужна капча: осталось ${left} сек.`);if(!await tabExists(tabId))throw new PageIssue('ordinary','Рабочая вкладка была закрыта');try{const capture=await readCapture(tabId);if(capture?.kind==='seller'&&capture.url===target.seller_url)return capture;}catch{}await sleep(Math.min(1000,Math.max(1,deadline-Date.now())));}
  if(stopRequested)throw new PageIssue('stop','Остановлено пользователем');throw new PageIssue('challenge-timeout','Капча не пройдена за отведённое время');
}
async function saveCapture(capture){const stored=normalizeState((await chrome.storage.local.get('research')).research||research);research=mergeSellerCapture(stored,capture);await chrome.storage.local.set({research});}
async function waitCountdown(seconds,label){const until=Date.now()+seconds*1000;while(Date.now()<until&&!stopRequested){while(userPaused&&!stopRequested){setStatus('Пауза. Нажмите «Продолжить».');await sleep(250);}if(stopRequested)break;setStatus(`${label}: ${Math.max(1,Math.ceil((until-Date.now())/1000))} сек.`);await sleep(Math.min(500,Math.max(1,until-Date.now())));}}
async function openCurrent(){if(!workerTabId||!await tabExists(workerTabId)){const tab=await chrome.tabs.create({url:current.seller_url,active:true});workerTabId=tab.id;}else await chrome.tabs.update(workerTabId,{url:current.seller_url,active:true});}
async function finishCapture(capture){await saveCapture(capture);completed++;const profile=capture.profile;log(`Сохранено: ${profile.seller||current.seller}${profile.inn?` · ИНН ${profile.inn}`:profile.captureIssue?` · ${profile.captureIssue}`:''}`);$('problem').hidden=true;await closeWorker();refreshSummary();}
async function run(){
  $('start').disabled=true;$('pause').disabled=false;$('stop').disabled=false;
  try{for(const target of queue){if(stopRequested)break;current=target;let done=false,challengeRetries=0;while(userPaused&&!stopRequested)await sleep(250);while(!done&&!stopRequested){try{setStatus(`Открываем ${completed+skipped+1} из ${queue.length}: ${target.seller||target.seller_url}`);await openCurrent();const capture=await waitForSeller(workerTabId,target,settings.timeout);await finishCapture(capture);done=true;}catch(error){if(stopRequested||error?.type==='stop')break;if(error?.type==='challenge'){log(`Требуется капча: ${target.seller||target.seller_url}`);try{const capture=await waitForChallenge(workerTabId,target);await finishCapture(capture);done=true;continue;}catch(challengeError){if(stopRequested||challengeError?.type==='stop')break;$('problem').hidden=true;await closeWorker();if(challengeRetries<settings.challengeRetries){challengeRetries++;log(`Капча не пройдена. Повтор ${challengeRetries} из ${settings.challengeRetries} после паузы.`);await waitCountdown(settings.challengeCooldown,'Пауза после капчи');continue;}skipped++;done=true;log(`Автопропуск после капчи: ${target.seller||target.seller_url}`);refreshSummary();continue;}}skipped++;done=true;$('problem').hidden=true;log(`Автопропуск: ${target.seller||target.seller_url} · ${error?.message||String(error)}`);await closeWorker();refreshSummary();}}if(!stopRequested&&completed+skipped<queue.length)await waitCountdown(settings.interval,'Следующий профиль через');}}
  finally{await closeWorker();$('problem').hidden=true;$('start').disabled=false;$('pause').disabled=true;$('stop').disabled=true;$('pause').textContent='Пауза';userPaused=false;setStatus(stopRequested?`Остановлено. Сохранено ${completed}, пропущено ${skipped}.`:`Серия завершена. Сохранено ${completed}, автоматически пропущено ${skipped}.`);research=normalizeState((await chrome.storage.local.get('research')).research||research);refreshSummary();}
}
$('start').onclick=async()=>{try{settings=automationSettings({interval:$('interval').value,timeout:$('timeout').value,limit:$('limit').value,challengeTimeout:$('challengeTimeout').value,challengeCooldown:$('challengeCooldown').value,challengeRetries:$('challengeRetries').value});queue=pendingSellerProfiles(research,$('refresh').checked).slice(0,settings.limit);if(!queue.length)throw Error('В очереди нет профилей для сбора');completed=0;skipped=0;stopRequested=false;userPaused=false;$('log').replaceChildren();refreshSummary();await run();}catch(error){setStatus(error?.message||String(error));}};
$('pause').onclick=()=>{userPaused=!userPaused;$('pause').textContent=userPaused?'Продолжить':'Пауза';if(!userPaused)setStatus('Продолжаем.');};
$('stop').onclick=async()=>{stopRequested=true;await closeWorker();};$('refresh').onchange=refreshSummary;refreshSummary();
