import test from 'node:test';
import assert from 'node:assert/strict';
import {fresh, mergeCapture, observations, listingRows, csv, searchURL, avitoURL} from '../browser-extension/core.js';
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
