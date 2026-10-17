import {fresh, avitoURL, searchURL, mergeCapture, observations, listingRows, sellerRows, hasUsableDetail, validateBackup, csv} from './core.js';
const $ = id => document.getElementById(id);
let state = (await chrome.storage.local.get('research')).research || fresh();
let limit = 40;
const message = (text, error=false) => { $('message').textContent = text; $('message').style.color = error ? '#a11d2c' : '#006b66'; };
function row(title, subtitle, url, label='Открыть') {
  const div=document.createElement('div'); div.className='row';
  const span=document.createElement('span'); span.textContent=title;
  const small=document.createElement('small'); small.textContent=subtitle;span.append(small);
  const button=document.createElement('button');button.textContent=label;button.onclick=()=>chrome.tabs.create({url});
  div.append(span,button);return div;
}
function render() {
  const entries=Object.values(state.listings);
  $('stats').textContent=`Объявлений: ${entries.length} · Полных карточек: ${entries.filter(hasUsableDetail).length} · Сохранений выдачи: ${state.captures.filter(c=>c.kind==='search').length}`;
  $('queryList').replaceChildren(...state.queries.map(q=>{
    const captures=state.captures.filter(c=>c.kind==='search' && c.query===q && c.region===state.region);
    const pages=[...new Set(captures.map(c=>`${c.page} (${c.sort})`))];
    return row(q, pages.length ? `Сохранены страницы: ${pages.join(', ')}` : 'Ещё не сохранено',searchURL(q,state.region));
  }));
  const list=entries.filter(l=>!$('pendingOnly').checked || !hasUsableDetail(l));
  $('listingList').replaceChildren(...list.slice(0,limit).map(l=>{const detail=hasUsableDetail(l)?l.detail:null;return row((detail||l.card).title, detail ? `Карточка сохранена; не найдены поля: ${detail.missingFields.join(', ') || 'нет'}` : 'Есть только выдача',l.url);}));
  $('more').hidden=list.length<=limit;
}
$('region').value=state.region;$('queries').value=state.queries.join('\n');render();
for(const name of ['search','detail','export']) $(`${name}Tab`).onclick=()=>{for(const n of ['search','detail','export']) $(n).hidden=n!==name;};
$('more').onclick=()=>{limit+=40;render();};$('pendingOnly').onchange=()=>{limit=40;render();};
$('automation').onclick=()=>chrome.tabs.create({url:chrome.runtime.getURL('automation.html')});
$('searchAutomation').onclick=()=>chrome.tabs.create({url:chrome.runtime.getURL('search-automation.html')});
$('saveSettings').onclick=async()=>{
  try {
    const queries=[...new Set($('queries').value.split('\n').map(s=>s.trim()).filter(Boolean))];
    if(!queries.length)throw Error('Введите хотя бы один запрос');
    const region=$('region').value.trim();searchURL(queries[0],region);
    const next={...state,queries,region};await chrome.storage.local.set({research:next});state=next;$('queries').value=state.queries.join('\n');render();message('Список сохранён.');
  }catch(e){message(e.message,true);}
};
$('capture').onclick=async()=>{
  $('capture').disabled=true;
  try {
    const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
    if(!avitoURL(tab?.url))throw Error('Откройте вкладку Авито, затем нажмите значок расширения.');
    const results=await chrome.scripting.executeScript({target:{tabId:tab.id},files:['capture.js']});
    const capture=results[0]?.result;
    const next=mergeCapture(state,capture);
    await chrome.storage.local.set({research:next});state=next;render();
    message(capture.kind==='search' ? `Сохранено ${capture.items.length} карточек. Запрос: ${capture.query || '(в адресе не указан)'}. Страница: ${capture.page}.` : `Объявление сохранено. Не найдены поля: ${capture.items[0].missingFields.join(', ') || 'нет'}.`);
  }catch(e){message(e.message || String(e),true);}finally{$('capture').disabled=false;}
};
function download(text,name,type) {
  const url=URL.createObjectURL(new Blob([text],{type}));
  const a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();
  setTimeout(()=>URL.revokeObjectURL(url),30000);
}
const stamp=()=>new Date().toISOString().replace(/[:.]/g,'-');
$('json').onclick=()=>download(JSON.stringify(state,null,2),`avito-research-${stamp()}.json`,'application/json');
$('listingsCSV').onclick=()=>download(csv(listingRows(state),['id','title','url','description','price','price_text','price_unit','price_from','seller','seller_url','location','parameters','images','detail_saved','first_seen','last_seen','detail_at','card_text']),`avito-listings-${stamp()}.csv`,'text/csv;charset=utf-8');
$('observationsCSV').onclick=()=>download(csv(observations(state),['capture_id','captured_at','query','region','page','sort','search_url','id','position_on_page','title','price','price_text','price_unit','promoted','url']),`avito-searches-${stamp()}.csv`,'text/csv;charset=utf-8');

$('sellersCSV').onclick=()=>download(csv(sellerRows(state),['seller_url','seller','listing_count','listing_ids','titles']),`avito-sellers-${stamp()}.csv`,'text/csv;charset=utf-8');
$('importJSON').onchange=async event=>{
  try {
    const file=event.target.files?.[0];
    if(!file)return;
    const restored=validateBackup(JSON.parse(await file.text()));
    const details=Object.values(restored.listings).filter(hasUsableDetail).length;
    if(!confirm(`Заменить текущие данные? В копии: ${Object.keys(restored.listings).length} объявлений, подробных карточек: ${details}, сохранений: ${restored.captures.length}.`))return;
    await chrome.storage.local.set({research:restored});state=restored;
    $('region').value=state.region;$('queries').value=state.queries.join('\n');render();message('JSON-копия восстановлена.');
  }catch(error){message(error?.message || String(error),true);}finally{event.target.value='';}
};
