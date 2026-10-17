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
  for(const result of Object.values(wordstat?.results||{}))for(const row of [...(result.results||[]),...(result.associations||[])]){
    const key=row.phrase.toLocaleLowerCase("ru");
    if(existing.has(key))continue;
    const current=aggregate.get(key)||{phrase:row.phrase,count:0,seeds:0};
    current.count=Math.max(current.count,Number(row.count)||0);current.seeds++;aggregate.set(key,current);
  }
  return [...aggregate.values()].sort((a,b)=>b.count-a.count||b.seeds-a.seeds||a.phrase.localeCompare(b.phrase,"ru"));
}
