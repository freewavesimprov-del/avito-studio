export const WORDSTAT_URL="https://searchapi.api.cloud.yandex.net/v2/wordstat/topRequests";

export function parseRegionIds(value) {
  const ids=[...new Set(String(value||"").split(/[\s,;]+/).map(x=>x.trim()).filter(Boolean))];
  if(!ids.length)throw Error("Укажите хотя бы один ID региона Wordstat");
  if(!ids.every(id=>/^\d+$/.test(id)))throw Error("ID регионов Wordstat должны быть числами через запятую");
  return ids;
}

export function wordstatSettings(input) {
  const apiKey=String(input.apiKey||"").trim();
  const folderId=String(input.folderId||"").trim();
  const numPhrases=Number(input.numPhrases);
  if(!apiKey)throw Error("Введите API-ключ Yandex Cloud");
  if(!folderId)throw Error("Введите folder ID каталога Yandex Cloud");
  if(!Number.isInteger(numPhrases)||numPhrases<1||numPhrases>2000)throw Error("Число фраз должно быть от 1 до 2000");
  return {apiKey,folderId,regionIds:parseRegionIds(input.regionIds),numPhrases};
}

const rows=value=>(Array.isArray(value)?value:[]).map(row=>({phrase:String(row?.phrase||"").trim(),count:Number(row?.count||0)})).filter(row=>row.phrase&&Number.isFinite(row.count));

export async function fetchTopRequests(settings, phrase, fetchImpl=fetch) {
  const response=await fetchImpl(WORDSTAT_URL,{
    method:"POST",
    headers:{"Content-Type":"application/json; charset=utf-8",Authorization:`Api-Key ${settings.apiKey}`},
    body:JSON.stringify({folderId:settings.folderId,phrase,numPhrases:settings.numPhrases,regions:settings.regionIds})
  });
  const text=await response.text();
  let data={};try{data=text?JSON.parse(text):{};}catch{}
  if(!response.ok){
    const detail=String(data?.message||data?.error?.message||text||"").slice(0,300);
    if(response.status===401||response.status===403)throw Error(`Wordstat отклонил ключ или права (${response.status}). ${detail}`.trim());
    if(response.status===429)throw Error(`Wordstat превысил лимит запросов (429). ${detail}`.trim());
    throw Error(`Ошибка Wordstat API (${response.status}). ${detail}`.trim());
  }
  return {phrase,capturedAt:new Date().toISOString(),totalCount:Number(data.totalCount||0),results:rows(data.results),associations:rows(data.associations)};
}

export function wordstatCandidates(wordstat, existingQueries=[]) {
  const existing=new Set(existingQueries.map(q=>q.toLocaleLowerCase("ru")));
  const aggregate=new Map();
  const add=(row,kind,seed)=>{
    const key=row.phrase.toLocaleLowerCase("ru");if(existing.has(key))return;
    const current=aggregate.get(key)||{phrase:row.phrase,count:0,kinds:new Set(),seedQueries:new Set()};
    current.count=Math.max(current.count,Number(row.count)||0);current.kinds.add(kind);current.seedQueries.add(seed);aggregate.set(key,current);
  };
  for(const [seed,result] of Object.entries(wordstat?.results||{})){
    for(const row of result.results||[])add(row,"results",seed);
    for(const row of result.associations||[])add(row,"associations",seed);
  }
  return [...aggregate.values()].map(row=>({...row,kinds:[...row.kinds],seedQueries:[...row.seedQueries],seeds:row.seedQueries.size})).sort((a,b)=>b.count-a.count||b.seeds-a.seeds||a.phrase.localeCompare(b.phrase,"ru"));
}

const terms=value=>String(value||"").toLocaleLowerCase("ru").split(/[\n,;]+/).map(x=>x.trim()).filter(Boolean);
export function filterWordstatCandidates(candidates, filters={}) {
  const query=String(filters.query||"").trim().toLocaleLowerCase("ru");
  const excluded=terms(filters.excluded);
  const min=filters.min===""||filters.min==null?null:Number(filters.min);
  const max=filters.max===""||filters.max==null?null:Number(filters.max);
  const kind=filters.kind||"all";
  const seed=filters.seed||"all";
  const rows=candidates.filter(row=>{
    const phrase=row.phrase.toLocaleLowerCase("ru");
    return (!query||phrase.includes(query))&&!excluded.some(term=>phrase.includes(term))&&(min==null||row.count>=min)&&(max==null||row.count<=max)&&(kind==="all"||row.kinds.includes(kind))&&(seed==="all"||row.seedQueries.includes(seed));
  });
  const alpha=(a,b)=>a.phrase.localeCompare(b.phrase,"ru");
  if(filters.sort==="countAsc")rows.sort((a,b)=>a.count-b.count||alpha(a,b));
  else if(filters.sort==="alpha")rows.sort(alpha);
  else rows.sort((a,b)=>b.count-a.count||alpha(a,b));
  return rows;
}
