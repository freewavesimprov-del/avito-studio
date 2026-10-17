"""Run with .venv/bin/python tests/check_extension_browser.py."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / 'browser-extension/capture.js').read_text()
with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, executable_path='/usr/bin/chromium')
    page = browser.new_page()
    def fixture(url, html):
        page.route('https://www.avito.ru/**', lambda route: route.fulfill(body=html, content_type='text/html; charset=utf-8'))
        page.goto(url)
        data = page.evaluate(SCRIPT)
        page.unroute_all()
        return data
    data = fixture('https://www.avito.ru/moskva_i_mo/predlozheniya_uslug?q=швы&p=2', '''<div data-marker="page-title/count">150 объявлений</div>
    <article data-marker="item"><a data-marker="item-title" href="/moskva/uslugi/shvy_123"><h3 itemprop="name">Инъектирование швов</h3></a>
    <div data-marker="item-price">от <span itemprop="price" content="1500">1500 ₽</span> за пог. м</div><a href="/user/profile1">Исполнитель</a></article>''')
    assert data['kind'] == 'search' and data['query'] == 'швы' and data['page'] == '2'
    assert data['items'][0]['priceUnit'] == 'linear_m' and data['items'][0]['priceFrom']
    assert data['items'][0]['sellerURL'] == 'https://www.avito.ru/user/profile1'
    data = fixture('https://www.avito.ru/moskva_i_mo/remont_i_stroitelstvo/stroymaterialy/izolyaciya/gidroizolyaciya-ASgBAgICAUSmAbs?context=H4sIAAAAAAAA&p=2', '''
    <input data-marker="search-form/suggest" value="отсечная гидроизоляция">
    <h1>«Отсечная гидроизоляция»: объявления для Москвы</h1>
    <article data-marker="item"><a data-marker="item-title" href="/moskva/remont_i_stroitelstvo/material_987"><h3 itemprop="name">Отсечная гидроизоляция</h3></a></article>''')
    assert data['kind'] == 'search' and data['query'] == 'отсечная гидроизоляция' and data['page'] == '2'
    assert data['items'][0]['id'] == '987'
    data = fixture('https://www.avito.ru/moskva/uslugi/shvy_123', '''<main><h1 itemprop="name">Инъектирование швов</h1>
    <div data-marker="item-view/item-price">Цена договорная</div><div itemprop="description">Герметизация швов. Гарантия по договору.</div>
    <div data-marker="item-view/item-params">Материал: бетон</div><div data-marker="item-view/item-address">Москва</div>
    <div data-marker="gallery"><img src="https://images.example/photo.jpg"></div>
    <article data-marker="item"><a data-marker="item-title" href="/moskva/uslugi/other_456">Рекомендованное</a></article></main>''')
    assert data['kind'] == 'detail' and data['items'][0]['id'] == '123'
    assert data['items'][0]['description'].startswith('Герметизация')
    assert data['items'][0]['price'] is None and data['items'][0]['priceUnit'] == 'unspecified'
    assert data['items'][0]['images'] == ['https://images.example/photo.jpg']
    assert data['items'][0]['rawText']
    data = fixture('https://www.avito.ru/moskva/uslugi/price_789', '''<main><h1>Инъектирование</h1><div data-marker="item-view/item-price">от 5 500 ₽</div><div itemprop="description">Описание</div><div data-marker="item-view/item-params">Подробности</div></main>''')
    assert data['items'][0]['price'] == 5500 and data['items'][0]['priceFrom']
    try:
        fixture('https://www.avito.ru/moskva/uslugi/shvy_123','<title>Доступ ограничен: проверка безопасности</title><h1>Проверка</h1>')
        raise AssertionError('Blocked page must not be saved')
    except Exception as e:
        assert 'ещё не распознаны' in str(e)
    try:
        fixture('https://www.avito.ru/moskva/uslugi/unavailable_456','<h1>Объявление не посмотреть</h1>')
        raise AssertionError('Unavailable page must not be saved as details')
    except Exception as e:
        assert 'ещё не распознаны' in str(e)
    browser.close()
print('Browser fixtures passed: search, details with recommendations, blocked page')
