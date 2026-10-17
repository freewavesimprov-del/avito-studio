import {fresh, normalizeState, updateQueries, setQueryMeta, enabledQueries, avitoURL, searchURL, mergeCapture, observations, listingRows, sellerRows, hasUsableDetail, validateBackup, csv} from './core.js';
import {wordstatSettings, fetchTopRequests, wordstatCandidates, filterWordstatCandidates} from './wordstat.js';

const $ = id => document.getElementById(id);
const stored=await chrome.storage.local.get(['research','wordstatCredentials']);
let state=normalizeState(stored.research||fresh());
let credentials=stored.wordstatCredentials||{};
let limit=40;
const selectedSuggestions=new Set();
const message=(text,error=false)=>{$('message').textContent=text;$('message').style.color=error?'#a11d2c':'#006b66';};
const wordstatMessage=(text,error=false)=>{$('wordstatStatus').textContent=text;$('wordstatStatus').style.color=error?'#a11d2c':'#006b66';};
const saveState=async next=>{state=normalizeState(next);await chrome.storage.local.set({research:state});};

function row(title,subtitle,url,label='Открыть') {
  const div=document.createElement('div');div.className='row';
  const span=document.createElement('span');span.textContent=title;
  const small=document.createElement('small');small.textContent=subtitle;span.append(small);
  const button=document.createElement('button');button.textContent=label;button.onclick=()=>chrome.tabs.create({url});
  div.append(span,button);return div;
}

function renderQuery(query) {
  const div=document.createElement('div');div.className='query-row';
  const text=document.createElement('span');text.textContent=query;
  const captures=state.captures.filter(c=>c.kind==='search'&&c.query===query&&c.region===state.region);
  const pages=[...new Set(captures.map(c=>`${c.page} (${c.sort})`))];
  const small=document.createElement('small');small.textContent=pages.length?`Страницы: ${pages.join(', ')}`:'Ещё не сохранено';text.append(small);
  const toggle=channel=>{
    const label=document.createElement('label');const input=document.createElement('input');input.type='checkbox';input.checked=state.queryMeta[query][channel]!==false;input.title=channel==='avito'?'Использовать в Авито':'Использовать в Wordstat';
    input.onchange=async()=>{await saveState(setQueryMeta(state,query,{[channel]:input.checked}));render();};label.append(input);return label;
  };
  const open=document.createElement('button');open.textContent='Открыть';open.onclick=()=>chrome.tabs.create({url:searchURL(query,state.region)});
  div.append(text,toggle('avito'),toggle('wordstat'),open);return div;
}

function renderWordstat() {
  const results=state.wordstat?.results||{};
  const seedQueries=enabledQueries(state,'wordstat');
  if($('seedSort').value==='countDesc')seedQueries.sort((a,b)=>(results[b]?.totalCount||0)-(results[a]?.totalCount||0));
  if($('seedSort').value==='countAsc')seedQueries.sort((a,b)=>(results[a]?.totalCount||0)-(results[b]?.totalCount||0));
  $('wordstatSeeds').replaceChildren(...seedQueries.map(query=>{
    const div=document.createElement('div');div.className='seed-row';
    const name=document.createElement('span');name.textContent=query;
    const value=document.createElement('span');const result=results[query];value.textContent=result?Number(result.totalCount||0).toLocaleString('ru-RU'):'нет данных';
    div.append(name,value);return div;
  }));
  const allCandidates=wordstatCandidates(state.wordstat,state.queries);
  const seedSelect=$('suggestionSeed');const selectedSeed=seedSelect.value;
  seedSelect.replaceChildren(Object.assign(document.createElement('option'),{value:'all',textContent:'Все исходные запросы'}),...Object.keys(results).map(seed=>Object.assign(document.createElement('option'),{value:seed,textContent:seed})));
  if([...seedSelect.options].some(option=>option.value===selectedSeed))seedSelect.value=selectedSeed;
  const candidates=filterWordstatCandidates(allCandidates,{query:$('suggestionSearch').value,excluded:$('suggestionExclude').value,min:$('suggestionMin').value,max:$('suggestionMax').value,kind:$('suggestionKind').value,seed:seedSelect.value,sort:$('suggestionSort').value});
  const visible=candidates.slice(0,500);
  $('wordstatSuggestions').replaceChildren(...visible.map(candidate=>{
    const div=document.createElement('label');div.className='suggestion-row';
    const input=document.createElement('input');input.type='checkbox';input.dataset.phrase=candidate.phrase;input.checked=selectedSuggestions.has(candidate.phrase);input.onchange=()=>{if(input.checked)selectedSuggestions.add(candidate.phrase);else selectedSuggestions.delete(candidate.phrase);renderSuggestionSummary(candidates.length,allCandidates.length);};
    const text=document.createElement('span');text.textContent=candidate.phrase;
    const kind=document.createElement('span');kind.className='suggestion-kind';kind.textContent=candidate.kinds.length>1?'уточнение + похожая':candidate.kinds[0]==='results'?'уточнение':'похожая';
    const count=document.createElement('small');count.textContent=Number(candidate.count).toLocaleString('ru-RU');
    div.append(input,text,kind,count);return div;
  }));
  renderSuggestionSummary(candidates.length,allCandidates.length);
  $('addSuggestions').disabled=!selectedSuggestions.size;
}

function renderSuggestionSummary(filtered,total){
  const limited=filtered>500?' · видны первые 500':'';
  $('suggestionSummary').textContent=`Показано: ${filtered} из ${total}${limited} · выбрано: ${selectedSuggestions.size}`;
  $('addSuggestions').disabled=!selectedSuggestions.size;
}

function render() {
  const entries=Object.values(state.listings);
  $('stats').textContent=`Объявлений: ${entries.length} · Полных карточек: ${entries.filter(hasUsableDetail).length} · Сохранений выдачи: ${state.captures.filter(c=>c.kind==='search').length}`;
  $('queryList').replaceChildren(...state.queries.map(renderQuery));
  const list=entries.filter(l=>!$('pendingOnly').checked||!hasUsableDetail(l));
  $('listingList').replaceChildren(...list.slice(0,limit).map(l=>{const detail=hasUsableDetail(l)?l.detail:null;return row((detail||l.card).title,detail?`Карточка сохранена; не найдены поля: ${detail.missingFields.join(', ')||'нет'}`:'Есть только выдача',l.url);}));
  $('more').hidden=list.length<=limit;renderWordstat();
}

$('region').value=state.region;$('queries').value=state.queries.join('\n');
$('wordstatKey').value=credentials.apiKey||'';$('wordstatFolder').value=credentials.folderId||'';
$('wordstatRegions').value=(state.wordstat?.regionIds||['1']).join(', ');$('wordstatLimit').value=state.wordstat?.numPhrases||50;render();
for(const name of ['search','wordstat','detail','export']) $(`${name}Tab`).onclick=()=>{for(const n of ['search','wordstat','detail','export'])$(n).hidden=n!==name;};
$('more').onclick=()=>{limit+=40;render();};$('pendingOnly').onchange=()=>{limit=40;render();};
$('automation').onclick=()=>chrome.tabs.create({url:chrome.runtime.getURL('automation.html')});
$('searchAutomation').onclick=()=>chrome.tabs.create({url:chrome.runtime.getURL('search-automation.html')});

$('saveSettings').onclick=async()=>{
  try{
    const queries=$('queries').value.split('\n');const region=$('region').value.trim();searchURL(queries.map(x=>x.trim()).find(Boolean)||'',region);
    await saveState({...updateQueries(state,queries),region});$('queries').value=state.queries.join('\n');render();message('Общий каталог сохранён.');
  }catch(error){message(error.message,true);}
};

$('capture').onclick=async()=>{
  $('capture').disabled=true;
  try{
    const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
    if(!avitoURL(tab?.url))throw Error('Откройте вкладку Авито, затем нажмите значок расширения.');
    const results=await chrome.scripting.executeScript({target:{tabId:tab.id},files:['capture.js']});const capture=results[0]?.result;
    await saveState(mergeCapture(state,capture));render();
    message(capture.kind==='search'?`Сохранено ${capture.items.length} карточек. Запрос: ${capture.query||'(в адресе не указан)'}. Страница: ${capture.page}.`:`Объявление сохранено. Не найдены поля: ${capture.items[0].missingFields.join(', ')||'нет'}.`);
  }catch(error){message(error.message||String(error),true);}finally{$('capture').disabled=false;}
};

function getWordstatSettings(numPhrases=$('wordstatLimit').value){return wordstatSettings({apiKey:$('wordstatKey').value,folderId:$('wordstatFolder').value,regionIds:$('wordstatRegions').value,numPhrases});}
async function saveCredentials(settings){credentials={apiKey:settings.apiKey,folderId:settings.folderId};await chrome.storage.local.set({wordstatCredentials:credentials});}
$('saveWordstat').onclick=async()=>{try{const settings=getWordstatSettings();await saveCredentials(settings);wordstatMessage('Ключ и folder ID сохранены только в этом профиле Chrome.');}catch(error){wordstatMessage(error.message,true);}};
$('removeWordstat').onclick=async()=>{await chrome.storage.local.remove('wordstatCredentials');credentials={};$('wordstatKey').value='';$('wordstatFolder').value='';wordstatMessage('Ключ и folder ID удалены из Chrome.');};
$('checkWordstat').onclick=async()=>{
  $('checkWordstat').disabled=true;
  try{const settings=getWordstatSettings(1);const query=enabledQueries(state,'wordstat')[0];if(!query)throw Error('Отметьте хотя бы один запрос для Wordstat');await fetchTopRequests(settings,query);await saveCredentials(settings);wordstatMessage('Доступ к Wordstat работает.');}
  catch(error){wordstatMessage(error.message||String(error),true);}finally{$('checkWordstat').disabled=false;}
};
$('collectWordstat').onclick=async()=>{
  $('collectWordstat').disabled=true;
  try{
    const settings=getWordstatSettings();const queries=enabledQueries(state,'wordstat');if(!queries.length)throw Error('Отметьте хотя бы один запрос для Wordstat');await saveCredentials(settings);
    const nextResults={...(state.wordstat?.results||{})};
    for(let index=0;index<queries.length;index++){
      wordstatMessage(`Wordstat: ${index+1} из ${queries.length} — ${queries[index]}`);nextResults[queries[index]]=await fetchTopRequests(settings,queries[index]);
      await saveState({...state,wordstat:{...(state.wordstat||{}),updatedAt:new Date().toISOString(),regionIds:settings.regionIds,numPhrases:settings.numPhrases,results:nextResults}});renderWordstat();
    }
    selectedSuggestions.clear();renderWordstat();wordstatMessage(`Готово: получены данные для ${queries.length} запросов.`);
  }catch(error){wordstatMessage(error.message||String(error),true);}finally{$('collectWordstat').disabled=false;}
};
$('addSuggestions').onclick=async()=>{
  try{
    const selected=[...selectedSuggestions];if(!selected.length)throw Error('Выберите хотя бы одну новую фразу');
    let next=updateQueries(state,[...state.queries,...selected]);for(const query of selected)next=setQueryMeta(next,query,{avito:false,wordstat:true,cluster:'кандидат',source:'wordstat'});
    await saveState(next);selectedSuggestions.clear();$('queries').value=state.queries.join('\n');render();wordstatMessage(`Добавлено фраз: ${selected.length}. Включите подходящие для Авито во вкладке «Запросы».`);
  }catch(error){wordstatMessage(error.message,true);}
};
for(const id of ['seedSort','suggestionSearch','suggestionExclude','suggestionMin','suggestionMax','suggestionKind','suggestionSeed','suggestionSort'])$(id).oninput=renderWordstat;
$('selectVisible').onclick=()=>{for(const input of $('wordstatSuggestions').querySelectorAll('input'))selectedSuggestions.add(input.dataset.phrase);renderWordstat();};
$('clearSuggestions').onclick=()=>{selectedSuggestions.clear();renderWordstat();};

function download(text,name,type){const url=URL.createObjectURL(new Blob([text],{type}));const a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);}
const stamp=()=>new Date().toISOString().replace(/[:.]/g,'-');
$('json').onclick=()=>download(JSON.stringify(state,null,2),`avito-research-${stamp()}.json`,'application/json');
$('listingsCSV').onclick=()=>download(csv(listingRows(state),['id','title','url','description','price','price_text','price_unit','price_from','seller','seller_url','location','parameters','images','detail_saved','first_seen','last_seen','detail_at','card_text']),`avito-listings-${stamp()}.csv`,'text/csv;charset=utf-8');
$('observationsCSV').onclick=()=>download(csv(observations(state),['capture_id','captured_at','query','region','page','sort','search_url','id','position_on_page','title','price','price_text','price_unit','promoted','url']),`avito-searches-${stamp()}.csv`,'text/csv;charset=utf-8');
$('sellersCSV').onclick=()=>download(csv(sellerRows(state),['seller_url','seller','listing_count','listing_ids','titles']),`avito-sellers-${stamp()}.csv`,'text/csv;charset=utf-8');
$('importJSON').onchange=async event=>{
  try{
    const file=event.target.files?.[0];if(!file)return;const restored=normalizeState(validateBackup(JSON.parse(await file.text())));const details=Object.values(restored.listings).filter(hasUsableDetail).length;
    if(!confirm(`Заменить текущие данные? В копии: ${Object.keys(restored.listings).length} объявлений, подробных карточек: ${details}, сохранений: ${restored.captures.length}.`))return;
    await saveState(restored);$('region').value=state.region;$('queries').value=state.queries.join('\n');$('wordstatRegions').value=(state.wordstat?.regionIds||['1']).join(', ');$('wordstatLimit').value=state.wordstat?.numPhrases||50;render();message('JSON-копия восстановлена.');
  }catch(error){message(error?.message||String(error),true);}finally{event.target.value='';}
};
