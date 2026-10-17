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
    const n = content && content.trim() ? Number(content.replace(/\s/g, "").replace(",", ".")) : NaN;
    return {price: Number.isFinite(n) ? n : null, priceText, priceFrom: /(?:^|\s)от\s*\d/i.test(priceText),
      priceUnit: /м²|м2|кв\.?\s*м/i.test(priceText) ? "m2" : /пог\.?\s*м|погонн/i.test(priceText) ? "linear_m" : /за\s*час/i.test(priceText) ? "hour" : /за\s*выезд/i.test(priceText) ? "visit" : "unspecified"};
  };
  const seller = el => {
    const a = find(el, 'a[href*="/user/"], a[href*="/brands/"]');
    return {seller: text(a), sellerURL: a ? href(a) : ""};
  };
  const common = {captureId: crypto.randomUUID(), at: new Date().toISOString(), url: location.href, title: document.title};
  const cards = [...document.querySelectorAll('[data-marker="item"]')].filter(el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden');
  if (cards.length && !idOf(location.href)) {
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
    const u = new URL(location.href);
    return {...common, kind: "search", query: u.searchParams.get("q") || "", region: u.pathname.split("/").filter(Boolean)[0] || "", page: u.searchParams.get("p") || "1", sort: u.searchParams.get("s") || "default", totalText: text(find(document, '[data-marker="page-title/count"]')), items};
  }
  const id = idOf(location.href);
  const title = text(find(document, '[data-marker="item-view/title-info"], h1[itemprop="name"], h1'));
  if (/доступ ограничен|проверка безопасности|проверка браузера/i.test(document.title) || !id || !title) {
    throw Error("Выдача или объявление ещё не распознаны. Дождитесь загрузки, завершите проверку сайта и нажмите «Сохранить» снова.");
  }
  const body = find(document, 'main, [data-marker="item-view"]') || document;
  const description = text(find(body, '[data-marker="item-view/item-description"], [itemprop="description"]'));
  const parametersText = text(find(body, '[data-marker="item-view/item-params"], [data-marker="item-view/item-parameters"]'));
  const images = [...new Set([...body.querySelectorAll('[data-marker*="image-frame"] img, [data-marker*="gallery"] img, [data-marker*="image-slider"] img')].map(i => i.currentSrc || i.src).filter(u => /^https:\/\//.test(u)))];
  const row = {id, url: location.origin + location.pathname, title, ...price(body), ...seller(body), description, parametersText,
    location: text(find(body, '[data-marker="item-view/item-address"], [itemprop="address"]')), images,
    rawText: body === document ? "" : text(body), missingFields: []};
  row.missingFields = ["description", "parametersText", "location", "seller"].filter(k => !row[k]);
  if (!images.length) row.missingFields.push("images");
  return {...common, kind: "detail", items: [row]};
})()
