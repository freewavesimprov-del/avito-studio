import test from 'node:test';
import assert from 'node:assert/strict';
import {fresh, normalizeState, updateQueries, setQueryMeta, enabledQueries, mergeCapture, observations, listingRows, pendingListings, automationSettings, searchScanSettings, hasUsableDetail, validateBackup, csv, searchURL, searchPageURL, avitoURL} from '../browser-extension/core.js';
import {parseRegionIds, wordstatSettings, fetchTopRequests, wordstatCandidates, filterWordstatCandidates, WORDSTAT_URL} from '../browser-extension/wordstat.js';
const card = {id:'123',title:'Инъектирование',url:'https://www.avito.ru/moskva/uslugi/injection_123',price:null,position:1};
const capture = (query,kind='search') => ({kind,captureId:query,at:'2026-10-17T10:00:00Z',url:'https://www.avito.ru/moskva_i_mo/predlozheniya_uslug?q='+encodeURIComponent(query),query,region:'moskva_i_mo',page:'1',sort:'default',items:[card]});
test('different queries preserve observations but share a unique listing',()=>{
  const state=mergeCapture(mergeCapture(fresh(),capture('инъектирование')),capture('гидроизоляция'));
  assert.equal(Object.keys(state.listings).length,1);
  assert.deepEqual(observations(state).map(r=>r.query),['инъектирование','гидроизоляция']);
  assert.equal(fresh().captures.length,0);
});
test('search snapshots do not overwrite details',()=>{
  const detailed={...capture('detail','detail'),items:[{...card,description:'Полное описание',images:['https://img.example/a.jpg'],missingFields:[]}]};
  const state=mergeCapture(mergeCapture(fresh(),detailed),capture('запрос'));
  assert.equal(listingRows(state)[0].description,'Полное описание');
  assert.equal(listingRows(state)[0].detail_saved,true);
  assert.equal(state.captures.length,2);
});
test('CSV preserves unknown prices, escapes text and formulas',()=>{
  const result=csv([{title:'=HYPERLINK("url")',price:null,description:'строка 1\nстрока 2'}],['title','price','description']);
  assert.ok(result.startsWith('\uFEFF'));
  assert.ok(result.includes('"\'=HYPERLINK(""url"")"'));
  assert.ok(result.includes(',"",'));
});
test('only Avito HTTPS pages can be captured',()=>{
  assert.equal(avitoURL('https://www.avito.ru/'),true);
  assert.equal(avitoURL('https://avito.ru.attacker.example/'),false);
  assert.equal(avitoURL('javascript:alert(1)'),false);
  assert.throws(()=>mergeCapture(fresh(),{...capture('x'),url:'https://example.test/'}));
  assert.throws(()=>searchURL('q','../../bad'));
  assert.equal(new URL(searchURL('швы & трещины','moskva_i_mo')).searchParams.get('q'),'швы & трещины');
});
test('automation queue contains only unique listings without details',()=>{
  let state=mergeCapture(fresh(),capture('поиск'));
  state.listings['999']={id:'999',url:'https://www.avito.ru/moskva/uslugi/detail_999',firstSeen:'2026-10-17T09:00:00Z',card:{title:'Сохранено'},detail:{title:'Сохранено'}};
  state.listings['bad']={id:'bad',url:'https://example.test/bad',firstSeen:'2026-10-17T08:00:00Z',card:{title:'Чужой сайт'}};
  assert.deepEqual(pendingListings(state).map(x=>x.id),['123']);
  assert.deepEqual(automationSettings({interval:'15',timeout:'60',limit:25}),{interval:15,timeout:60,limit:25});
  assert.throws(()=>automationSettings({interval:4,timeout:60,limit:25}));
  assert.throws(()=>automationSettings({interval:15,timeout:10,limit:25}));
  assert.throws(()=>automationSettings({interval:15,timeout:60,limit:501}));
});
test('full JSON backup is validated before restore',()=>{
  const state=mergeCapture(fresh(),capture('поиск'));
  const restored=validateBackup(state);
  assert.notEqual(restored,state);
  assert.equal(Object.keys(restored.listings).length,1);
  assert.throws(()=>validateBackup({...state,listings:{'123':{...state.listings['123'],url:'https://example.test/'}}}));
  assert.throws(()=>validateBackup({...state,captures:[{kind:'search',url:'javascript:bad',items:[]}]}));
});
test('search scan URLs and settings preserve page and sort',()=>{
  const url=new URL(searchPageURL('трещины & швы','moskva_i_mo',4,'104'));
  assert.equal(url.searchParams.get('q'),'трещины & швы');
  assert.equal(url.searchParams.get('p'),'4');
  assert.equal(url.searchParams.get('s'),'104');
  assert.deepEqual(searchScanSettings({firstPage:'1',lastPage:'4',interval:'15',timeout:'60',sort:'default'}),{firstPage:1,lastPage:4,interval:15,timeout:60,sort:'default'});
  assert.throws(()=>searchScanSettings({firstPage:4,lastPage:2,interval:15,timeout:60,sort:'default'}));
  const empty={kind:'search',captureId:'empty',at:'2026-10-17T12:00:00Z',url:'https://www.avito.ru/moskva_i_mo/predlozheniya_uslug?q=x&p=9',query:'x',region:'moskva_i_mo',page:'9',sort:'default',items:[]};
  assert.equal(mergeCapture(fresh(),empty).captures.length,1);
});
test('unavailable legacy details return to pending queue',()=>{
  const state=mergeCapture(fresh(),capture('поиск'));
  state.listings['123'].detail={...card,title:'Объявление не посмотреть'};
  assert.equal(hasUsableDetail(state.listings['123']),false);
  assert.deepEqual(pendingListings(state).map(x=>x.id),['123']);
  assert.equal(listingRows(state)[0].detail_saved,false);
});
test('legacy backups gain a query catalog without losing data',()=>{
  const legacy={version:1,queries:['первый','второй','первый'],region:'moskva_i_mo',listings:{},captures:[]};
  let state=normalizeState(legacy);
  assert.deepEqual(state.queries,['первый','второй']);
  assert.deepEqual(enabledQueries(state,'avito'),['первый','второй']);
  state=setQueryMeta(state,'второй',{avito:false});
  assert.deepEqual(enabledQueries(state,'avito'),['первый']);
  state=updateQueries(state,['второй','новый']);
  assert.equal(state.queryMeta['второй'].avito,false);
  assert.equal(state.queryMeta['новый'].source,'manual');
});
test('Wordstat settings and response use the Yandex Cloud v2 contract',async()=>{
  const settings=wordstatSettings({apiKey:'secret',folderId:'folder',regionIds:'1, 213;1',numPhrases:'50'});
  assert.deepEqual(settings.regionIds,['1','213']);
  let request;
  const result=await fetchTopRequests(settings,'гидроизоляция',async(url,options)=>{request={url,options};return new Response(JSON.stringify({totalCount:'123',results:[{phrase:'гидроизоляция подвала',count:'45'}],associations:[]}),{status:200});});
  assert.equal(request.url,WORDSTAT_URL);
  assert.equal(request.options.headers.Authorization,'Api-Key secret');
  assert.deepEqual(JSON.parse(request.options.body).regions,['1','213']);
  assert.equal(result.totalCount,123);
  assert.equal(result.results[0].count,45);
  assert.throws(()=>parseRegionIds('Москва'));
});
test('Wordstat suggestions exclude catalog phrases and merge duplicates',()=>{
  const suggestions=wordstatCandidates({results:{a:{results:[{phrase:'Новая фраза',count:10},{phrase:'ядро',count:99}],associations:[{phrase:'Подкожная инъекция',count:3000}]},b:{results:[{phrase:'новая фраза',count:20}],associations:[]}}},['ядро']);
  assert.equal(suggestions.length,2);
  const merged=suggestions.find(x=>x.phrase.toLocaleLowerCase('ru')==='новая фраза');
  assert.equal(merged.count,20);
  assert.equal(merged.seeds,2);
  assert.deepEqual(merged.kinds,['results']);
  const filtered=filterWordstatCandidates(suggestions,{excluded:'подкожная, hydra',min:'5',max:'100',kind:'results',sort:'countAsc'});
  assert.equal(filtered.length,1);
  assert.equal(filtered[0].phrase.toLocaleLowerCase('ru'),'новая фраза');
  assert.deepEqual(filterWordstatCandidates(suggestions,{seed:'b'}).map(x=>x.phrase.toLocaleLowerCase('ru')),['новая фраза']);
});
