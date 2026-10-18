(async()=>{
  const text=el=>(el?.innerText||el?.textContent||'').trim().replace(/\u00a0/g,' ');
  const visible=el=>Boolean(el&&el.getClientRects().length&&getComputedStyle(el).visibility!=='hidden');
  const number=value=>{const parsed=Number(String(value||'').replace(/\s/g,'').replace(',','.'));return Number.isFinite(parsed)?parsed:null;};
  const pageText=text(document.body);const url=new URL(location.href);url.search='';url.hash='';
  const common={at:new Date().toISOString(),url:url.href};
  if(/доступ ограничен|проверка безопасности|проверка браузера|подтвердите, что (?:вы|это вы)|пройдите проверку|captcha|капч/i.test(`${document.title}\n${pageText.slice(0,5000)}`))return {...common,kind:'status',status:'challenge',reason:'Авито запрашивает проверку или капчу'};
  if(/попробуйте перезагрузить|выключите vpn|что-то пошло не так|временно недоступ/i.test(pageText.slice(0,5000)))return {...common,kind:'status',status:'transient',reason:'Авито показал временную ошибку страницы'};

  const requisitesPattern=/Реквизиты проверены|Профилем владеет компания/i;
  const parseRequisites=value=>{
    const legalMatch=value.match(/(?:^|\s)(ООО|ИП|АО|ПАО|ЗАО|ОАО)\s*[«"“]?([^\n|;]{2,120}?)(?=\s+(?:ИНН|ОГРН|КПП)(?:\s|:)|$)/i);
    const namedMatch=value.match(/(?:Наименование|Название организации|Юридическое лицо)\s*[:\n]\s*([^\n]{3,160})/i);
    const innMatch=value.match(/(?:^|\s)ИНН\s*[:№]?\s*(\d{12}|\d{10})(?!\d)/i);
    const ogrnMatch=value.match(/(?:^|\s)ОГРН(?:ИП)?\s*[:№]?\s*(\d{15}|\d{13})(?!\d)/i);
    const kppMatch=value.match(/(?:^|\s)КПП\s*[:№]?\s*(\d{9})(?!\d)/i);
    const addressMatch=value.match(/(?:Юридический адрес|Адрес регистрации)\s*[:\n]\s*([^\n]{5,250})/i);
    return {legalName:legalMatch?`${legalMatch[1].toUpperCase()} ${legalMatch[2].replace(/[»"”]+$/,'').trim()}`:(namedMatch?.[1]?.trim()||''),inn:innMatch?.[1]||'',ogrn:ogrnMatch?.[1]||'',kpp:kppMatch?.[1]||'',legalAddress:addressMatch?.[1]?.trim()||''};
  };
  const readRequisites=()=>{
    const verifiedRequisites=requisitesPattern.test(pageText);
    const legalCandidates=[...document.querySelectorAll('[role="dialog"], [data-marker*="modal"], [data-marker*="requisite"], [class*="modal"], div, section')]
      .filter(visible).map(el=>text(el)).filter(value=>/(?:^|\s)ИНН\s*[:№]?\s*\d{10,12}(?!\d)/i.test(value)&&value.length<6000)
      .sort((a,b)=>a.length-b.length);
    const requisitesText=legalCandidates[0]||'';
    if(verifiedRequisites&&!requisitesText){
      const root=document.documentElement;const started=Number(root.dataset.avitoResearchRequisitesStarted||0);
      if(!started){
        const candidates=[...document.querySelectorAll('button,[role="button"],a,div,span')].filter(el=>visible(el)&&requisitesPattern.test(text(el))&&text(el).length<500).sort((a,b)=>text(a).length-text(b).length);
        const label=candidates[0];const trigger=label?.closest('button,[role="button"],a')||label;
        if(trigger){root.dataset.avitoResearchRequisitesStarted=String(Date.now());trigger.click();return {status:{...common,kind:'status',status:'opening_requisites',reason:'Открываем проверенные реквизиты'}};}
      }else if(Date.now()-started<10000)return {status:{...common,kind:'status',status:'opening_requisites',reason:'Ждём окно с реквизитами'}};
    }
    const legal=parseRequisites(requisitesText);
    return {profile:{verifiedRequisites,requisitesCheckedAt:new Date().toISOString(),...legal,requisitesText,captureIssue:verifiedRequisites&&!legal.inn?'Авито подтвердил реквизиты, но ИНН не удалось прочитать':!verifiedRequisites?'В объявлении не найдена отметка проверенных реквизитов':''}};
  };

  const listingId=url.pathname.match(/_(\d+)\/?$/)?.[1]||'';
  if(listingId){
    const unavailable=pageText.match(/объявление (?:снято с публикации|не посмотреть|закрыто|удалено|завершено|больше не доступно|неактивно|не активно)|такого объявления (?:нет|не существует)|страница объявления не найдена/i)?.[0]||'';
    if(unavailable)return {...common,kind:'requisites',profile:{verifiedRequisites:false,requisitesCheckedAt:new Date().toISOString(),legalName:'',inn:'',ogrn:'',kpp:'',legalAddress:'',requisitesText:'',captureIssue:`Объявление для проверки реквизитов недоступно: ${unavailable}`}};
    if(pageText.length<100)return {...common,kind:'status',status:'loading',reason:'Объявление ещё загружается'};
    const result=readRequisites();return result.status||{...common,kind:'requisites',profile:result.profile};
  }

  if(!/^\/(?:user\/[^/]+\/profile|brands\/[^/]+)\/?$/.test(url.pathname))return {...common,kind:'status',status:'loading',reason:'Открыта не страница профиля продавца'};
  if(pageText.length<100)return {...common,kind:'status',status:'loading',reason:'Профиль ещё загружается'};
  const seller=text(document.querySelector('[data-marker="profile-title"], [data-marker="seller-info/name"], h1'))||document.title.split(/[—|]/)[0].trim();
  const profileType=(pageText.match(/(?:^|\n)\s*(Компания|Частный исполнитель|Самозанятый|ИП)\s*(?:\n|$)/im)||[])[1]||'';
  const years=[...pageText.matchAll(/На Авито\s+[cс](?:\s+[а-яё]+)?\s+(\d{4})(?:\s+года)?/gi)].map(match=>Number(match[1]));
  const totals=[...pageText.matchAll(/(\d[\d ]*)\s+объявлен(?:ие|ия|ий)(?:\s+пользователя)?/gi),...pageText.matchAll(/(?:Все\s+)?Объявления\s*(\d[\d ]*)/gi)].map(match=>number(match[1])).filter(value=>value!=null);
  const ratingMatch=pageText.match(/(?:^|\n)\s*(\d[,.]\d)\s*(?:\n|·|\s)+(\d[\d ]*)\s+отзыв/mi);
  const reviewsMatch=pageText.match(/(\d[\d ]*)\s+отзыв(?:а|ов)?(?:\s+клиент)/i)||pageText.match(/(\d[\d ]*)\s+отзыв(?:а|ов)?/i);
  const contactMatch=pageText.match(/Контактное лицо\s*\n+\s*([^\n]{2,100})/i);
  const responseMatch=pageText.match(/Отвечает\s+([^\n]{2,80})/i);
  const subscribersMatch=pageText.match(/(\d[\d ]*)\s+подписчик/i);
  const description=text(document.querySelector('[data-marker*="profile-description"], [data-marker*="seller-description"], [itemprop="description"]'));
  const locationText=text(document.querySelector('[data-marker*="location"], [data-marker*="address"], [itemprop="address"]'));
  const badgeLabels=['Документы проверены','Проверенный партнёр','Надёжный продавец'];
  const badges=badgeLabels.filter(label=>pageText.includes(label));
  return {...common,kind:'seller',profile:{url:url.href,seller,profileType,rating:ratingMatch?number(ratingMatch[1]):null,reviews:reviewsMatch?number(reviewsMatch[1]):null,avitoSinceYear:years.length?Math.min(...years):'',listingsTotal:totals.length?Math.max(...totals):null,contactPerson:contactMatch?.[1]?.trim()||'',responseTime:responseMatch?.[1]?.trim()||'',subscribers:subscribersMatch?number(subscribersMatch[1]):null,verifiedRequisites:false,legalName:'',inn:'',ogrn:'',kpp:'',legalAddress:'',location:locationText,description,badges,requisitesText:'',captureIssue:''}};
})()
