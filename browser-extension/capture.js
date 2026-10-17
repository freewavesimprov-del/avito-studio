(() => {
  const text = el => (el?.innerText || el?.textContent || "").trim().replace(/\u00a0/g, " ");
  const find = (el, selectors) => el.querySelector(selectors);
  const href = a => {try {const u = new URL(a?.getAttribute("href") || "", location.href); u.search = ""; u.hash = ""; return u.href;} catch {return "";}};
  const idOf = url => new URL(url).pathname.match(/_(\d+)\/?$/)?.[1] || "";
  const price = el => {
    const p = find(el, '[data-marker="item-price"], [data-marker="item-view/item-price"], [itemprop="offers"]') || find(el, '[itemprop="price"]')?.parentElement;
    const priceText = text(p);
    const meta = find(el, '[itemprop="price"]');
    const content = meta?.getAttribute("content");
    const fallback = priceText.match(/(?:^|\s)(\d[\d\s]*(?:[,.]\d+)?)(?=\s*₽)/)?.[1] || "";
    const rawNumber = content && content.trim() ? content : fallback;
    const n = rawNumber ? Number(rawNumber.replace(/\s/g, "").replace(",", ".")) : NaN;
    return {price: Number.isFinite(n) ? n : null, priceText, priceFrom: /(?:^|\s)от\s*\d/i.test(priceText),
      priceUnit: /м²|м2|кв\.?\s*м/i.test(priceText) ? "m2" : /пог\.?\s*м|погонн/i.test(priceText) ? "linear_m" : /за\s*час/i.test(priceText) ? "hour" : /за\s*выезд/i.test(priceText) ? "visit" : "unspecified"};
  };
  const seller = el => {
    const a = find(el, '[data-marker="seller-info/name"] a, [data-marker="seller-link/link"], [data-marker="item-view/seller-info"] a, a[href*="/user/"], a[href*="/brands/"]');
    const name = text(a) || text(find(el, '[data-marker="seller-info/name"], [data-marker="seller-link/link"]'));
    return {seller: name, sellerURL: a ? href(a) : ""};
  };
  const common = {captureId: crypto.randomUUID(), at: new Date().toISOString(), url: location.href, title: document.title};
  const currentURL = new URL(location.href);
  const cards = [...document.querySelectorAll('[data-marker="item"]')].filter(el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden');
  const listingId=idOf(location.href);
  const searchInput=find(document, 'input[data-marker="search-form/suggest"], input[name="q"], input[placeholder*="Поиск"]');
  const headingQuery=text(find(document, 'h1')).match(/^[«"]([^»"]+)[»"]/)?.[1] || "";
  const searchQuery=currentURL.searchParams.get("q") || searchInput?.value?.trim() || headingQuery;
  // Авито может перенаправить текстовый поиск из раздела услуг в товарную
  // категорию. Такая страница всё равно остаётся поисковой выдачей.
  const isSearch=!listingId && (cards.length > 0 || Boolean(searchQuery) || /\/predlozheniya_uslug\/?$/.test(location.pathname));
  if (cards.length && isSearch) {
    const items = cards.map((el, index) => {
      const link = find(el, 'a[data-marker="item-title"]') || [...el.querySelectorAll('a[href]')].find(a => /_\d+(?:\?|$)/.test(a.getAttribute("href")));
      const url = link ? href(link) : "";
      const rawText = text(el);
      return {id: url ? idOf(url) : "", url, title: text(find(el, '[itemprop="name"], [data-marker="item-title"]')), position: index + 1,
        ...price(el), ...seller(el), description: text(find(el, '[data-marker="item-description"]')),
        location: text(find(el, '[data-marker="item-address"], [data-marker="item-location"]')),
        promoted: /Продвинуто|Реклама/i.test(rawText), rawText};
    }).filter(i => i.id && i.title);
    if (!items.length) throw Error("Карточки есть, но их ссылки не распознаны. Сохранение отменено.");
    return {...common, kind: "search", query: searchQuery, region: currentURL.pathname.split("/").filter(Boolean)[0] || "", page: currentURL.searchParams.get("p") || "1", sort: currentURL.searchParams.get("s") || "default", totalText: text(find(document, '[data-marker="page-title/count"]')), items};
  }
  if (isSearch && /ничего не найдено|нет объявлений|по вашему запросу ничего/i.test(text(document.body))) {
    return {...common, kind:"search",query:searchQuery,region:currentURL.pathname.split("/").filter(Boolean)[0]||"",page:currentURL.searchParams.get("p")||"1",sort:currentURL.searchParams.get("s")||"default",totalText:"0",items:[]};
  }
  const id = listingId;
  const title = text(find(document, '[data-marker="item-view/title-info"], h1[itemprop="name"], h1'));
  if (/доступ ограничен|проверка безопасности|проверка браузера/i.test(document.title) || /объявление не посмотреть/i.test(title) || !id || !title) {
    throw Error("Выдача или объявление ещё не распознаны. Дождитесь загрузки, завершите проверку сайта и нажмите «Сохранить» снова.");
  }
  const body = find(document, 'main, [data-marker="item-view"]') || document;
  const description = text(find(body, '[data-marker="item-view/item-description"], [itemprop="description"]'));
  const parametersText = text(find(body, '[data-marker="item-view/item-params"], [data-marker="item-view/item-parameters"]'));
  const images = [...new Set([...body.querySelectorAll('[data-marker*="image-frame"] img, [data-marker*="gallery"] img, [data-marker*="image-slider"] img')].flatMap(i => {
    const srcset=(i.getAttribute('srcset')||i.getAttribute('data-srcset')||'').split(',').map(x=>x.trim().split(/\s+/)[0]);
    return [i.currentSrc,i.src,i.getAttribute('data-src'),...srcset];
  }).filter(u => /^https:\/\//.test(u)))];
  const row = {id, url: location.origin + location.pathname, title, ...price(body), ...seller(body), description, parametersText,
    location: text(find(body, '[data-marker="item-view/location"], [data-marker="item-view/item-address"], [data-marker*="address"], [itemprop="address"]')), images,
    rawText: text(body === document ? document.body : body), missingFields: []};
  row.missingFields = ["description", "parametersText", "location", "seller"].filter(k => !row[k]);
  if (!images.length) row.missingFields.push("images");
  return {...common, kind: "detail", items: [row]};
})()
