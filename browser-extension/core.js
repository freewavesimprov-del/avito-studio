export const DEFAULT_QUERIES = ["инъекционная гидроизоляция", "гидроизоляционное инъектирование", "инъектирование трещин", "инъектирование швов", "инъектирование фундамента", "инъектирование подвала", "устранение течей в подвале", "отсечная гидроизоляция"];
const defaultQueryMeta = () => ({avito: true, wordstat: true, cluster: "ядро", source: "preset"});
export const fresh = () => normalizeState({version: 3, queries: [...DEFAULT_QUERIES], region: "moskva_i_mo", listings: {}, sellerProfiles: {}, captures: []});
export function normalizeState(value) {
  const source=value && typeof value==="object" ? value : {};
  const queries=[...new Set((Array.isArray(source.queries)?source.queries:DEFAULT_QUERIES).map(q=>String(q).trim()).filter(Boolean))];
  const oldMeta=source.queryMeta && typeof source.queryMeta==="object" ? source.queryMeta : {};
  const queryMeta={};
  for(const query of queries){
    const meta=oldMeta[query] && typeof oldMeta[query]==="object" ? oldMeta[query] : {};
    queryMeta[query]={...defaultQueryMeta(),...meta,avito:meta.avito!==false,wordstat:meta.wordstat!==false,cluster:String(meta.cluster||"ядро"),source:String(meta.source||"manual")};
  }
  return {...source,version:3,queries,queryMeta,region:typeof source.region==="string"?source.region:"moskva_i_mo",listings:source.listings&&typeof source.listings==="object"?source.listings:{},sellerProfiles:source.sellerProfiles&&typeof source.sellerProfiles==="object"?source.sellerProfiles:{},captures:Array.isArray(source.captures)?source.captures:[]};
}
export function enabledQueries(state, channel) {
  const normalized=normalizeState(state);
  if(!["avito","wordstat"].includes(channel))throw Error("Неизвестный источник запросов");
  return normalized.queries.filter(query=>normalized.queryMeta[query]?.[channel]!==false);
}
export function updateQueries(state, queries) {
  const normalized=normalizeState(state);
  const clean=[...new Set(queries.map(q=>String(q).trim()).filter(Boolean))];
  if(!clean.length)throw Error("Введите хотя бы один запрос");
  const queryMeta={};
  for(const query of clean)queryMeta[query]=normalized.queryMeta[query]||{...defaultQueryMeta(),source:"manual"};
  return {...normalized,queries:clean,queryMeta};
}
export function setQueryMeta(state, query, patch) {
  const normalized=normalizeState(state);
  if(!normalized.queries.includes(query))throw Error("Запрос не найден");
  return {...normalized,queryMeta:{...normalized.queryMeta,[query]:{...normalized.queryMeta[query],...patch}}};
}
export function avitoURL(value) {
  try {const u = new URL(value); return u.protocol === "https:" && (u.hostname === "avito.ru" || u.hostname === "www.avito.ru");} catch {return false;}
}
export function searchURL(query, region) {
  if (!/^[a-z0-9_]+$/.test(region)) throw Error("Регион должен быть slug Авито, например moskva_i_mo");
  return `https://www.avito.ru/${region}/predlozheniya_uslug?q=${encodeURIComponent(query)}`;
}
export function searchPageURL(query, region, page=1, sort="default") {
  const url=new URL(searchURL(query,region));
  url.searchParams.set("p",String(page));
  if(sort!=="default")url.searchParams.set("s",String(sort));
  return url.href;
}
export function mergeCapture(state, capture) {
  if (!capture || !avitoURL(capture.url) || !["search", "detail"].includes(capture.kind) || !Array.isArray(capture.items) || (capture.kind === "detail" && !capture.items.length)) throw Error("Нет распознанных карточек для сохранения");
  const next = structuredClone(state);
  for (const row of capture.items) {
    if (!/^\d+$/.test(row.id) || !avitoURL(row.url)) throw Error("Некорректная ссылка на объявление");
    const prev = next.listings[row.id] || {id: row.id, firstSeen: capture.at};
    // Отдельные поля сохраняют источник: краткая карточка не затирает полное объявление.
    next.listings[row.id] = {...prev, url: row.url, lastSeen: capture.at,
      ...(capture.kind === "detail" ? {detail: row, detailAt: capture.at} : {card: row})};
  }
  next.captures.push(capture);
  return next;
}
export function sellerProfileURL(value) {
  if(!avitoURL(value))return false;
  const path=new URL(value).pathname;
  return /^\/(?:user\/[^/]+\/profile|brands\/[^/]+)\/?$/.test(path);
}
export function mergeSellerCapture(state,capture){
  if(!capture||capture.kind!=="seller"||!sellerProfileURL(capture.url)||!capture.profile||capture.profile.url!==capture.url)throw Error("Профиль продавца не распознан");
  const next=structuredClone(normalizeState(state));
  next.sellerProfiles[capture.url]={...(next.sellerProfiles[capture.url]||{}),...capture.profile,capturedAt:capture.at};
  return next;
}
export function observations(state) {
  return state.captures.filter(c => c.kind === "search").flatMap(c => c.items.map(i => ({capture_id: c.captureId, captured_at: c.at, query: c.query, region: c.region, page: c.page, sort: c.sort, search_url: c.url, id: i.id, position_on_page: i.position, title: i.title, price: i.price, price_text: i.priceText, price_unit: i.priceUnit, promoted: i.promoted, url: i.url})));
}
export function hasUsableDetail(listing) {
  return Boolean(listing?.detail && !terminalDetailStatus(listing.detail));
}
export function terminalDetailStatus(detail) {
  if(!detail)return "";
  if(detail.availability==="unavailable")return detail.availabilityText||"Объявление недоступно";
  const text=`${detail.title||""}\n${detail.rawText||""}`;
  const match=text.match(/объявление (?:снято с публикации|не посмотреть|закрыто|удалено|завершено|больше не доступно|неактивно|не активно)|такого объявления (?:нет|не существует)|страница объявления не найдена/i);
  return match?.[0]||"";
}
export function hasTerminalDetail(listing) {
  return Boolean(terminalDetailStatus(listing?.detail));
}
export function listingRows(state) {
  return Object.values(state.listings).map(l => {
    const detail=hasUsableDetail(l) ? l.detail : null;
    const terminal=terminalDetailStatus(l.detail);
    const r = detail || l.card;
    return {id: l.id, title: r.title, url: l.url, description: detail?.description ?? "", price: r.price, price_text: r.priceText, price_unit: r.priceUnit, price_from: r.priceFrom, seller: r.seller, seller_url: r.sellerURL, location: r.location, parameters: detail?.parametersText ?? "", images: (detail?.images || []).join("\n"), detail_saved: Boolean(detail), unavailable: Boolean(terminal), unavailable_reason: terminal, first_seen: l.firstSeen, last_seen: l.lastSeen, detail_at: l.detail ? (l.detailAt ?? "") : "", card_text: l.card?.rawText ?? ""};
  });
}
export function pendingListings(state) {
  return Object.values(state.listings)
    .filter(listing => !hasUsableDetail(listing) && !hasTerminalDetail(listing) && avitoURL(listing.url))
    .sort((a, b) => String(a.firstSeen || "").localeCompare(String(b.firstSeen || "")));
}
export function automationSettings(input) {
  const interval = Number(input.interval);
  const timeout = Number(input.timeout);
  const limit = Number(input.limit);
  const challengeTimeout = Number(input.challengeTimeout ?? 120);
  const challengeCooldown = Number(input.challengeCooldown ?? 300);
  const challengeRetries = Number(input.challengeRetries ?? 1);
  if (!Number.isFinite(interval) || interval < 1 || interval > 3600) throw Error("Интервал должен быть от 1 до 3600 секунд");
  if (!Number.isFinite(timeout) || timeout < 5 || timeout > 180) throw Error("Ожидание страницы должно быть от 5 до 180 секунд");
  if (!Number.isInteger(limit) || limit < 1 || limit > 500) throw Error("Размер серии должен быть от 1 до 500");
  if (!Number.isFinite(challengeTimeout) || challengeTimeout < 30 || challengeTimeout > 600) throw Error("Ожидание капчи должно быть от 30 до 600 секунд");
  if (!Number.isFinite(challengeCooldown) || challengeCooldown < 30 || challengeCooldown > 3600) throw Error("Пауза после капчи должна быть от 30 до 3600 секунд");
  if (!Number.isInteger(challengeRetries) || challengeRetries < 0 || challengeRetries > 3) throw Error("Повторов после капчи должно быть от 0 до 3");
  return {interval, timeout, limit, challengeTimeout, challengeCooldown, challengeRetries};
}
export function searchScanSettings(input) {
  const firstPage=Number(input.firstPage);
  const lastPage=Number(input.lastPage);
  const interval=Number(input.interval);
  const timeout=Number(input.timeout);
  const challengeTimeout=Number(input.challengeTimeout ?? 120);
  const challengeCooldown=Number(input.challengeCooldown ?? 300);
  const challengeRetries=Number(input.challengeRetries ?? 1);
  if(!Number.isInteger(firstPage) || firstPage<1 || firstPage>100)throw Error("Начальная страница должна быть от 1 до 100");
  if(!Number.isInteger(lastPage) || lastPage<firstPage || lastPage>100)throw Error("Конечная страница должна быть не меньше начальной и не больше 100");
  if(!Number.isFinite(interval) || interval<1 || interval>3600)throw Error("Интервал должен быть от 1 до 3600 секунд");
  if(!Number.isFinite(timeout) || timeout<5 || timeout>180)throw Error("Ожидание страницы должно быть от 5 до 180 секунд");
  if(!Number.isFinite(challengeTimeout) || challengeTimeout<30 || challengeTimeout>600)throw Error("Ожидание капчи должно быть от 30 до 600 секунд");
  if(!Number.isFinite(challengeCooldown) || challengeCooldown<30 || challengeCooldown>3600)throw Error("Пауза после капчи должна быть от 30 до 3600 секунд");
  if(!Number.isInteger(challengeRetries) || challengeRetries<0 || challengeRetries>3)throw Error("Повторов после капчи должно быть от 0 до 3");
  if(!["default","104"].includes(input.sort))throw Error("Неизвестная сортировка");
  return {firstPage,lastPage,interval,timeout,sort:input.sort,challengeTimeout,challengeCooldown,challengeRetries};
}
const normalizedQuery=value=>String(value||"").trim().replace(/\s+/g," ").toLocaleLowerCase("ru");
export function checkSearchCapture(capture,target) {
  if(!capture||capture.kind!=="search")return {ok:false,reason:"На странице пока не распознана выдача"};
  if(normalizedQuery(capture.query)!==normalizedQuery(target.query))return {ok:false,reason:`Открыт другой запрос: «${capture.query||"пустой запрос"}»`};
  if(String(capture.page)!==String(target.page))return {ok:false,reason:`Открыта страница ${capture.page}, ожидалась ${target.page}`};
  if(capture.sort!==target.sort)return {ok:false,reason:`Открыта другая сортировка: ${capture.sort}`};
  return {ok:true,reason:""};
}
export function validateBackup(value) {
  if (!value || typeof value !== "object" || !Array.isArray(value.queries) || !Array.isArray(value.captures) || !value.listings || typeof value.listings !== "object") {
    throw Error("Файл не похож на полную JSON-копию расширения");
  }
  if (!value.queries.every(q => typeof q === "string") || typeof value.region !== "string") throw Error("В копии повреждены настройки запросов");
  for (const [id, listing] of Object.entries(value.listings)) {
    if (!/^\d+$/.test(id) || listing?.id !== id || !avitoURL(listing?.url)) throw Error(`Некорректное объявление в копии: ${id}`);
  }
  for (const capture of value.captures) {
    if (!capture || !["search", "detail"].includes(capture.kind) || !Array.isArray(capture.items) || !avitoURL(capture.url)) throw Error("В копии повреждена история сохранений");
  }
  if(value.sellerProfiles!=null&&(!value.sellerProfiles||typeof value.sellerProfiles!=="object"||Array.isArray(value.sellerProfiles)))throw Error("В копии повреждены профили продавцов");
  for(const [url,profile] of Object.entries(value.sellerProfiles||{}))if(!sellerProfileURL(url)||profile?.url!==url)throw Error(`Некорректный профиль продавца: ${url}`);
  return normalizeState(structuredClone(value));
}
const utf8Size=value=>new TextEncoder().encode(value).length;
export function splitResearchBackup(value,maxBytes,options={}) {
  const state=validateBackup(value);
  if(!Number.isInteger(maxBytes)||maxBytes<1024*1024||maxBytes>20*1024*1024)throw Error("Размер части должен быть от 1 до 20 МБ");
  const exportId=String(options.exportId||crypto.randomUUID());
  const exportedAt=String(options.exportedAt||new Date().toISOString());
  const common=Object.fromEntries(Object.entries(state).filter(([key])=>!['listings','captures'].includes(key)));
  const records=[{type:'common',value:common},...Object.entries(state.listings).map(([id,item])=>({type:'listing',id,value:item})),...state.captures.map(value=>({type:'capture',value}))];
  const wrapperBytes=utf8Size(JSON.stringify({format:'avito-research-parts-v1',exportId,exportedAt,part:999999,parts:999999,records:[]}))+1024;
  const groups=[];let group=[],bytes=wrapperBytes;
  for(const record of records){
    const recordBytes=utf8Size(JSON.stringify(record))+1;
    if(recordBytes+wrapperBytes>maxBytes)throw Error(`Одна запись занимает больше лимита части (${Math.ceil(recordBytes/1024/1024)} МБ). Увеличьте размер части.`);
    if(group.length&&bytes+recordBytes>maxBytes){groups.push(group);group=[];bytes=wrapperBytes;}
    group.push(record);bytes+=recordBytes;
  }
  if(group.length)groups.push(group);
  return groups.map((records,index)=>{
    const part={format:'avito-research-parts-v1',exportId,exportedAt,part:index+1,parts:groups.length,records};
    const json=JSON.stringify(part);if(utf8Size(json)>maxBytes)throw Error("Не удалось уложить часть в заданный размер");return json;
  });
}
export function combineResearchBackupParts(values) {
  if(!Array.isArray(values)||!values.length)throw Error("Не выбраны части JSON-копии");
  const parts=values.map(value=>typeof value==='string'?JSON.parse(value):value);
  const first=parts[0];
  if(parts.some(part=>part?.format!=='avito-research-parts-v1'||part.exportId!==first.exportId||part.parts!==first.parts))throw Error("Выбраны части разных JSON-копий");
  if(parts.length!==first.parts)throw Error(`Выбрано частей: ${parts.length}, требуется: ${first.parts}`);
  parts.sort((a,b)=>a.part-b.part);
  if(parts.some((part,index)=>part.part!==index+1))throw Error("Номера частей повторяются или часть отсутствует");
  let common=null;const listings={},captures=[];
  for(const part of parts)for(const record of part.records||[]){
    if(record.type==='common'){if(common)throw Error("В частях повторяется служебная запись");common=record.value;}
    else if(record.type==='listing'){if(listings[record.id])throw Error(`Объявление ${record.id} повторяется в частях`);listings[record.id]=record.value;}
    else if(record.type==='capture')captures.push(record.value);
    else throw Error("В части найден неизвестный тип записи");
  }
  if(!common)throw Error("В частях отсутствуют общие настройки исследования");
  return validateBackup({...common,listings,captures});
}
export function csv(rows, columns) {
  const cell = v => {
    let s = v == null ? "" : String(v);
    if (/^[\s]*[=+@-]/.test(s)) s = "'" + s;
    return '"' + s.replaceAll('"', '""') + '"';
  };
  return "\uFEFF" + [columns, ...rows.map(r => columns.map(k => r[k]))].map(r => r.map(cell).join(",")).join("\r\n");
}
export function sellerRows(state) {
  state=normalizeState(state);
  const groups=new Map();
  for(const listing of Object.values(state.listings)) {
    const row=hasUsableDetail(listing) ? listing.detail : listing.card;
    const url=row.sellerURL || listing.card?.sellerURL;
    if(!url) continue;
    const group=groups.get(url) || {seller_url:url,seller:row.seller || listing.card?.seller || '',listing_ids:[],titles:[],detail_saved:0,unavailable:0,company_hint:false,representative_listing_url:'',requisites_listing_url:''};
    group.listing_ids.push(listing.id);group.titles.push(row.title);group.representative_listing_url ||= row.url||listing.card?.url||listing.url||'';
    if(hasUsableDetail(listing)){group.detail_saved++;if(/Реквизиты проверены|Профилем владеет компания/i.test(row.rawText||'')){group.company_hint=true;group.requisites_listing_url ||= row.url||listing.url||'';}}
    if(hasTerminalDetail(listing))group.unavailable++;groups.set(url,group);
  }
  const observationsBySeller=new Map();
  const sellerByListing=new Map();
  for(const [id,listing] of Object.entries(state.listings)){
    const row=hasUsableDetail(listing)?listing.detail:listing.card;
    const url=row?.sellerURL||listing.card?.sellerURL;if(url)sellerByListing.set(id,url);
  }
  for(const observation of observations(state)){
    const url=sellerByListing.get(observation.id);if(!url)continue;
    const rows=observationsBySeller.get(url)||[];rows.push(observation);observationsBySeller.set(url,rows);
  }
  return [...groups.values()].map(g=>{
    const profile=state.sellerProfiles[g.seller_url]||{};const seen=observationsBySeller.get(g.seller_url)||[];
    const queries=[...new Set(seen.map(row=>row.query).filter(Boolean))];const positions=seen.map(row=>Number(row.position_on_page)).filter(Number.isFinite);
    const published=Number(profile.listingsTotal);const coverage=Number.isFinite(published)&&published>0?Math.min(100,100*g.listing_ids.length/published):null;
    return {...g,listing_count:g.listing_ids.length,search_appearances:seen.length,queries_count:queries.length,queries:queries.join('\n'),first_page_appearances:seen.filter(row=>Number(row.position_on_page)<=50).length,best_position:positions.length?Math.min(...positions):'',promoted_appearances:seen.filter(row=>row.promoted).length,
      profile_captured:Boolean(profile.capturedAt),profile_captured_at:profile.capturedAt||'',profile_type:profile.profileType||'',rating:profile.rating??'',reviews:profile.reviews??'',avito_since_year:profile.avitoSinceYear||'',profile_listings_total:profile.listingsTotal??'',coverage_pct:coverage==null?'':coverage.toFixed(1),contact_person:profile.contactPerson||'',response_time:profile.responseTime||'',subscribers:profile.subscribers??'',verified_requisites:Boolean(profile.verifiedRequisites),requisites_checked_at:profile.requisitesCheckedAt||'',legal_name:profile.legalName||'',inn:profile.inn||'',ogrn:profile.ogrn||'',kpp:profile.kpp||'',legal_address:profile.legalAddress||'',profile_location:profile.location||'',profile_description:profile.description||'',badges:(profile.badges||[]).join('; '),requisites_text:profile.requisitesText||'',profile_capture_issue:profile.captureIssue||'',listing_ids:g.listing_ids.join(';'),titles:g.titles.join('\n')};
  });
}
export function sellerProfileTargets(state){
  return sellerRows(state).filter(row=>sellerProfileURL(row.seller_url)).sort((a,b)=>Number(b.company_hint)-Number(a.company_hint)||b.listing_count-a.listing_count||a.seller.localeCompare(b.seller,'ru'));
}
export function pendingSellerProfiles(state,refresh=false){
  return sellerProfileTargets(state).filter(row=>refresh||!row.profile_captured||(row.company_hint&&row.requisites_listing_url&&!row.requisites_checked_at));
}
