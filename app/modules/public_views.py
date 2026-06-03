from __future__ import annotations

from html import escape
from typing import Any

from app.modules.content.service import ACTION_DEFAULTS, HOME_DEFAULTS, MENU_DEFAULTS


PUBLIC_HEAD = """<meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\">
  <link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>
  <link href=\"https://fonts.googleapis.com/css2?family=Jost:wght@400;500;700;800;900&display=swap\" rel=\"stylesheet\">"""


BASE_CSS = """
    :root { --golden-malt:#C7B166; --noble-hop:#105859; --deep-hop:#0b3f40; --card-hop:#0d4b4c; --card-hop-soft:#145f60; --foam:#F6F1E3; --ink:#172625; --muted:#b8c7c4; --white:#fff; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:'Jost', system-ui, -apple-system, Segoe UI, sans-serif; background:var(--noble-hop); color:var(--foam); }
    a { color:inherit; }
    .top-nav { position:sticky; top:0; z-index:10; display:flex; align-items:center; justify-content:space-between; gap:18px; padding:14px min(6vw,72px); background:rgba(11,63,64,.94); border-bottom:1px solid rgba(199,177,102,.18); backdrop-filter:blur(12px); }
    .brand { color:var(--golden-malt); font-weight:900; letter-spacing:.12em; text-transform:uppercase; text-decoration:none; white-space:nowrap; }
    .nav-links { display:flex; align-items:center; justify-content:center; gap:30px; flex-wrap:wrap; font-size:14px; font-weight:700; }
    .nav-links a { color:rgba(246,241,227,.82); text-decoration:none; }
    .nav-links a.is-active, .nav-links a:hover { color:var(--golden-malt); }
    .nav-actions { display:flex; align-items:center; gap:9px; }
    .nav-icon { width:32px; height:32px; border:1px solid rgba(199,177,102,.28); border-radius:999px; display:grid; place-items:center; color:var(--foam); text-decoration:none; font-size:13px; font-weight:900; }
    .nav-icon--cart { background:var(--golden-malt); color:var(--ink); }
    @media (max-width:920px) { .top-nav { align-items:flex-start; flex-direction:column; } .nav-links { justify-content:flex-start; } }
"""


def public_content_or_defaults(content: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "home": {**HOME_DEFAULTS, **((content or {}).get("home") or {})},
        "menu": (content or {}).get("menu") or MENU_DEFAULTS,
        "actions": (content or {}).get("actions") or ACTION_DEFAULTS,
    }


def public_nav(active: str, content: dict[str, Any] | None = None) -> str:
    site_content = public_content_or_defaults(content)
    links = "".join(
        f'<a class="{"is-active" if item.get("key") == active else ""}" href="{escape(str(item.get("href") or "#"))}">{escape(str(item.get("label") or ""))}</a>'
        for item in site_content["menu"]
        if item.get("is_visible", True)
    )
    actions = "".join(
        f'<a class="nav-icon {"nav-icon--cart" if item.get("key") == "cart" else ""}" href="{escape(str(item.get("href") or "#"))}" aria-label="{escape(str(item.get("label") or ""))}">{escape(str(item.get("label") or ""))}</a>'
        for item in site_content["actions"]
        if item.get("is_visible", True)
    )
    return f"""
  <nav class="top-nav" aria-label="Главная навигация">
    <a class="brand" href="/">Stamm Brewing</a>
    <div class="nav-links">{links}</div>
    <div class="nav-actions" aria-label="Соцсети и корзина">{actions}</div>
  </nav>"""


def home_page(content: dict[str, Any] | None = None) -> str:
    site_content = public_content_or_defaults(content)
    home = site_content["home"]
    logo_url = str(home.get("home_logo_url") or "")
    logo_markup = f'<img class="home-logo" src="{escape(logo_url)}" alt="Stamm Brewing logo">' if logo_url else '<div class="home-logo-mark" aria-hidden="true"></div>'
    return f"""<!doctype html>
<html lang="ru">
<head>
  {PUBLIC_HEAD}
  <title>Stamm Brewing · Главная</title>
  <style>
{BASE_CSS}
    .home-hero {{ min-height:68vh; display:grid; place-items:center; text-align:center; padding:72px min(6vw,72px); background:radial-gradient(circle at 50% 16%, rgba(199,177,102,.18), transparent 28%), linear-gradient(135deg, var(--noble-hop), var(--deep-hop)); }}
    .home-hero__inner {{ display:grid; justify-items:center; gap:10px; }}
    .home-logo {{ max-width:118px; max-height:118px; object-fit:contain; margin-bottom:12px; }}
    .home-logo-mark {{ width:72px; height:72px; border:2px solid rgba(199,177,102,.5); border-radius:999px; margin-bottom:12px; background:radial-gradient(circle, rgba(199,177,102,.28), transparent 58%); }}
    .home-title {{ margin:0; font-size:clamp(58px,13vw,164px); line-height:.78; letter-spacing:.08em; color:var(--foam); font-weight:950; }}
    .home-subtitle {{ margin:0; font-size:clamp(42px,10vw,126px); line-height:.8; letter-spacing:.08em; color:var(--golden-malt); font-weight:950; }}
    .home-news {{ padding:34px min(6vw,72px) 64px; }}
    .news-card {{ max-width:920px; background:var(--card-hop); border:1px solid rgba(199,177,102,.2); border-radius:24px; padding:26px; box-shadow:0 18px 40px rgba(0,0,0,.16); }}
    .news-card__label {{ color:var(--golden-malt); font-weight:900; text-transform:uppercase; letter-spacing:.1em; font-size:13px; }}
    .news-card h2 {{ margin:10px 0; color:var(--white); font-size:clamp(24px,4vw,38px); }}
    .news-card p {{ margin:0; color:rgba(246,241,227,.78); line-height:1.55; font-size:18px; }}
  </style>
</head>
<body>
{public_nav("home", site_content)}
  <main>
    <section class="home-hero">
      <div class="home-hero__inner">
        {logo_markup}
        <h1 class="home-title">{escape(str(home.get('home_hero_title') or 'STAMM'))}</h1>
        <p class="home-subtitle">{escape(str(home.get('home_hero_subtitle') or 'BREWING'))}</p>
      </div>
    </section>
    <section class="home-news" aria-label="Новости">
      <article class="news-card">
        <div class="news-card__label">Новость</div>
        <h2>Готовим новую B2B-витрину Stamm Brewing</h2>
        <p>Готовим обновлённый сайт пивоварни: с чистой навигацией, B2B-витриной и фирменной подачей Stamm Brewing.</p>
      </article>
    </section>
  </main>
</body>
</html>"""


def public_placeholder_page(title: str, active: str, content: dict[str, Any] | None = None) -> str:
    return f"""<!doctype html>
<html lang="ru">
<head>
  {PUBLIC_HEAD}
  <title>{title} · Stamm Brewing</title>
  <style>
{BASE_CSS}
    .placeholder {{ min-height:54vh; display:grid; place-items:center; padding:72px min(6vw,72px); background:linear-gradient(135deg, var(--noble-hop), var(--deep-hop)); }}
    .placeholder__card {{ max-width:760px; background:var(--card-hop); border:1px solid rgba(199,177,102,.2); border-radius:24px; padding:30px; }}
    .placeholder__card h1 {{ margin:0 0 10px; color:var(--golden-malt); text-transform:uppercase; letter-spacing:.08em; }}
    .placeholder__card p {{ margin:0; color:rgba(246,241,227,.76); }}
  </style>
</head>
<body>
{public_nav(active, content)}
  <main class="placeholder"><section class="placeholder__card"><h1>{title}</h1><p>Раздел будет собираться после ядра B2B-магазина и админки.</p></section></main>
</body>
</html>"""


def business_storefront_page(content: dict[str, Any] | None = None) -> str:
    return f"""<!doctype html>
<html lang="ru">
<head>
  {PUBLIC_HEAD}
  <title>Бизнес · Stamm Brewing</title>
  <style>
{BASE_CSS}
    .hero {{ background:linear-gradient(135deg, var(--noble-hop), var(--deep-hop)); color:var(--golden-malt); padding:28px min(6vw,72px) 22px; text-align:center; }}
    .hero h1 {{ margin:0; font-size:clamp(28px,4vw,48px); line-height:.9; letter-spacing:.12em; text-transform:uppercase; font-weight:950; }}
    .wrap {{ padding:22px min(6vw,72px) 56px; }}
    .toolbar {{ display:flex; flex-wrap:wrap; justify-content:space-between; gap:16px; align-items:center; margin-bottom:18px; }}
    .filters {{ display:flex; gap:10px; flex-wrap:wrap; }}
    .filter {{ border:1px solid rgba(199,177,102,.34); background:rgba(11,63,64,.55); color:var(--foam); padding:9px 15px; border-radius:999px; font-weight:800; cursor:pointer; }}
    .filter.is-active {{ background:var(--golden-malt); color:var(--ink); border-color:var(--golden-malt); }}
    .diagnostics {{ font-size:12px; color:rgba(246,241,227,.72); background:rgba(11,63,64,.46); border:1px solid rgba(199,177,102,.18); border-radius:14px; padding:9px 12px; }}
    .shop-layout {{ display:grid; grid-template-columns:minmax(0,1fr) 360px; gap:18px; align-items:start; }}
    .grid {{ display:grid; grid-template-columns:1fr; gap:10px; }}
    .product {{ overflow:hidden; background:var(--card-hop); border:1px solid rgba(199,177,102,.18); border-radius:18px; box-shadow:0 14px 30px rgba(0,0,0,.14); display:grid; grid-template-columns:82px minmax(0,1fr) auto; align-items:center; gap:12px; min-height:98px; padding:9px 12px; }}
    .product__image {{ width:70px; height:70px; border-radius:14px; background:radial-gradient(circle at 34% 28%, rgba(199,177,102,.74), transparent 34%), linear-gradient(135deg, rgba(246,241,227,.92), rgba(199,177,102,.28)); display:block; overflow:hidden; flex-shrink:0; }}
    .product__image img {{ width:100%; height:100%; object-fit:cover; display:block; }}
    .product__image-fallback {{ width:100%; height:100%; background:radial-gradient(circle at 50% 36%, rgba(199,177,102,.78), transparent 32%), linear-gradient(135deg, rgba(246,241,227,.18), rgba(199,177,102,.22)); }}
    .product__body {{ min-width:0; display:flex; flex-direction:column; gap:7px; justify-content:center; }}
    .badges {{ display:flex; gap:6px; flex-wrap:wrap; }}
    .badge {{ font-size:11px; padding:4px 8px; border-radius:999px; background:rgba(246,241,227,.1); color:var(--foam); font-weight:800; line-height:1; }}
    h2 {{ margin:0; font-size:16px; line-height:1.15; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; color:var(--white); }}
    .meta {{ display:flex; align-items:center; justify-content:flex-start; gap:14px; font-weight:900; font-size:13px; }}
    .price {{ font-size:17px; color:var(--golden-malt); }}
    .product__order {{ display:grid; place-items:center; min-width:116px; }}
    .quantity {{ display:grid; grid-template-columns:30px 38px 30px; align-items:center; border:1px solid rgba(199,177,102,.28); border-radius:999px; overflow:hidden; background:rgba(11,63,64,.42); }}
    .quantity__button {{ border:0; width:30px; height:30px; background:var(--golden-malt); color:var(--ink); font-weight:950; cursor:pointer; }}
    .quantity__button:hover {{ filter:brightness(1.06); }}
    .quantity__value {{ text-align:center; font-weight:950; color:var(--foam); font-size:13px; }}
    .cart {{ position:sticky; top:86px; background:var(--card-hop); border:1px solid rgba(199,177,102,.22); border-radius:20px; box-shadow:0 14px 34px rgba(0,0,0,.16); overflow:hidden; }}
    .cart__header {{ display:flex; align-items:center; justify-content:space-between; gap:12px; padding:16px 18px; border-bottom:1px solid rgba(199,177,102,.14); }}
    .cart__title {{ margin:0; color:var(--golden-malt); font-size:18px; text-transform:uppercase; letter-spacing:.08em; }}
    .cart__counter {{ min-width:30px; height:30px; border-radius:999px; display:grid; place-items:center; background:var(--golden-malt); color:var(--ink); font-weight:950; }}
    .cart__body {{ padding:14px 18px 18px; }}
    .cart__empty {{ min-height:12px; }}
    .cart__items {{ display:grid; gap:10px; margin-bottom:14px; }}
    .cart-item {{ display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px 10px; padding:10px 0; border-bottom:1px solid rgba(246,241,227,.1); }}
    .cart-item__name {{ font-weight:900; color:var(--white); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
    .cart-item__meta {{ color:rgba(246,241,227,.68); font-size:12px; margin-top:3px; }}
    .cart-item__sum {{ color:var(--golden-malt); font-weight:950; white-space:nowrap; }}
    .cart-item__controls {{ grid-column:1 / -1; display:flex; align-items:center; justify-content:space-between; gap:8px; }}
    .cart-remove {{ border:0; background:transparent; color:rgba(246,241,227,.72); cursor:pointer; text-decoration:underline; padding:0; }}
    .cart__total {{ display:flex; justify-content:space-between; align-items:center; padding-top:12px; border-top:1px solid rgba(199,177,102,.18); font-weight:950; }}
    .cart__total strong {{ color:var(--golden-malt); font-size:20px; }}
    .cart__submit {{ width:100%; margin-top:14px; border:0; border-radius:14px; padding:12px 14px; background:var(--golden-malt); color:var(--ink); font-weight:950; cursor:pointer; }}
    .cart__submit:disabled {{ opacity:.48; cursor:not-allowed; }}
    .state {{ background:var(--card-hop); border:1px solid rgba(199,177,102,.18); border-radius:20px; padding:34px; text-align:center; color:rgba(246,241,227,.76); }}
    .state strong {{ display:block; color:var(--golden-malt); font-size:22px; margin-bottom:8px; }}
    @media (max-width:920px) {{ .shop-layout {{ grid-template-columns:1fr; }} .cart {{ position:static; }} }}
    @media (max-width:720px) {{ .hero {{ padding:22px min(5vw,28px) 16px; }} .wrap {{ padding:16px min(5vw,28px) 36px; }} .product {{ grid-template-columns:60px minmax(0,1fr); gap:10px; min-height:86px; padding:9px; }} .product__image {{ width:56px; height:56px; border-radius:12px; }} .product__order {{ grid-column:2; justify-self:start; min-width:0; margin-top:2px; }} h2 {{ font-size:15px; }} .price {{ font-size:15px; }} .quantity {{ grid-template-columns:28px 36px 28px; }} .quantity__button {{ width:28px; height:28px; }} }}
  </style>
</head>
<body>
{public_nav("business", content)}
  <section class="hero">
    <h1>БИЗНЕС</h1>
  </section>
  <main class="wrap">
    <div class="toolbar">
      <div class="filters" aria-label="Фильтры каталога">
        <button class="filter is-active" data-filter="all">Все</button>
        <button class="filter" data-filter="keg">Кеги</button>
        <button class="filter" data-filter="can">Банки</button>
      </div>
      <div class="diagnostics" id="diagnostics">Источник: локальный каталог · загрузка…</div>
    </div>
    <div class="shop-layout">
      <div class="catalog-column">
        <div id="state" class="state"><strong>Загружаем каталог</strong>Получаем товары из локального backend API сайта.</div>
        <section id="grid" class="grid" hidden></section>
      </div>
      <aside class="cart" id="cart" aria-live="polite">
        <div class="cart__header">
          <h2 class="cart__title">Корзина</h2>
          <span class="cart__counter" id="cartCounter">0</span>
        </div>
        <div class="cart__body" id="cartBody"><div class="cart__empty" aria-label="Корзина пуста"></div></div>
      </aside>
    </div>
  </main>
  <script>
    const stateEl = document.getElementById('state');
    const gridEl = document.getElementById('grid');
    const diagnosticsEl = document.getElementById('diagnostics');
    const cartCounterEl = document.getElementById('cartCounter');
    const cartBodyEl = document.getElementById('cartBody');
    const filterButtons = [...document.querySelectorAll('.filter')];
    let activeFilter = 'all';
    let currentItems = [];
    const cart = new Map();

    function setState(title, text) {{
      stateEl.hidden = false;
      gridEl.hidden = true;
      stateEl.innerHTML = `<strong>${{title}}</strong>${{text}}`;
    }}

    function escapeHtml(value) {{
      return String(value ?? '').replace(/[&<>"']/g, (char) => ({{ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }}[char]));
    }}

    function formatMoney(amountMinor, currency = 'RUB') {{
      if (amountMinor === null || amountMinor === undefined) return 'Цена по запросу';
      return `${{Number(amountMinor / 100).toLocaleString('ru-RU')}} ₽`;
    }}

    function cartQuantity(productId) {{
      return cart.get(String(productId))?.quantity || 0;
    }}

    function renderCards(items) {{
      currentItems = items;
      gridEl.innerHTML = items.map((item) => {{
        const safeName = escapeHtml(item.name);
        const safeContainer = escapeHtml(item.containerLabel);
        const safePrice = escapeHtml(item.price.label);
        const fallback = `<div class="product__image-fallback" aria-label="Фото скоро появится"></div>`;
        const imageMarkup = item.imageUrl
          ? `<img src="${{escapeHtml(item.imageUrl)}}" alt="${{safeName}}" loading="lazy" onerror="this.hidden=true; this.nextElementSibling.hidden=false"><div class="product__image-fallback" aria-label="Фото скоро появится" hidden></div>`
          : fallback;
        const quantity = cartQuantity(item.productId);
        return `
        <article class="product">
          <div class="product__image">${{imageMarkup}}</div>
          <div class="product__body">
            <div class="badges"><span class="badge">${{safeContainer}}</span></div>
            <h2>${{safeName}}</h2>
            <div class="meta"><span class="price">${{safePrice}}</span></div>
          </div>
          <div class="product__order" aria-label="Количество для ${{safeName}}">
            <div class="quantity" data-product-id="${{escapeHtml(item.productId)}}">
              <button class="quantity__button" type="button" data-action="decrease" aria-label="Уменьшить">−</button>
              <span class="quantity__value" data-quantity-for="${{escapeHtml(item.productId)}}">${{escapeHtml(quantity)}}</span>
              <button class="quantity__button" type="button" data-action="increase" aria-label="Увеличить">+</button>
            </div>
          </div>
        </article>
      `}}).join('');
      stateEl.hidden = true;
      gridEl.hidden = false;
    }}

    function updateDiagnostics(meta) {{
      const updated = meta.lastCatalogSyncAt || 'ещё не обновлялся';
      diagnosticsEl.textContent = `Источник: ${{meta.readModel}} · товаров: ${{meta.returnedItems}}/${{meta.totalLocalItems}} · обновлено: ${{updated}}`;
    }}

    function updateQuantityControls(productId) {{
      document.querySelectorAll('[data-quantity-for]').forEach((node) => {{
        if (node.dataset.quantityFor === String(productId)) node.textContent = cartQuantity(productId);
      }});
    }}

    function setCartQuantity(item, nextQuantity) {{
      const productId = String(item.productId);
      const quantity = Math.max(0, nextQuantity);
      if (quantity === 0) {{
        cart.delete(productId);
      }} else {{
        cart.set(productId, {{ item, quantity }});
      }}
      updateQuantityControls(productId);
      renderCart();
    }}

    function changeCartQuantity(productId, delta) {{
      const item = currentItems.find((entry) => String(entry.productId) === String(productId)) || cart.get(String(productId))?.item;
      if (!item) return;
      setCartQuantity(item, cartQuantity(productId) + delta);
    }}

    function renderCart() {{
      const entries = [...cart.values()];
      const totalQuantity = entries.reduce((sum, entry) => sum + entry.quantity, 0);
      const totalMinor = entries.reduce((sum, entry) => sum + (entry.item.price.amountMinor || 0) * entry.quantity, 0);
      cartCounterEl.textContent = totalQuantity;
      if (entries.length === 0) {{
        cartBodyEl.innerHTML = '<div class="cart__empty" aria-label="Корзина пуста"></div>';
        return;
      }}
      const rows = entries.map(({{ item, quantity }}) => {{
        const lineTotal = (item.price.amountMinor || 0) * quantity;
        return `
          <div class="cart-item">
            <div>
              <div class="cart-item__name">${{escapeHtml(item.name)}}</div>
              <div class="cart-item__meta">${{escapeHtml(item.containerLabel)}} · ${{escapeHtml(item.price.label)}} × ${{escapeHtml(quantity)}}</div>
            </div>
            <div class="cart-item__sum">${{escapeHtml(formatMoney(lineTotal, item.price.currency))}}</div>
            <div class="cart-item__controls">
              <div class="quantity" data-product-id="${{escapeHtml(item.productId)}}">
                <button class="quantity__button" type="button" data-action="decrease" aria-label="Уменьшить">−</button>
                <span class="quantity__value">${{escapeHtml(quantity)}}</span>
                <button class="quantity__button" type="button" data-action="increase" aria-label="Увеличить">+</button>
              </div>
              <button class="cart-remove" type="button" data-action="remove" data-product-id="${{escapeHtml(item.productId)}}">Удалить</button>
            </div>
          </div>`;
      }}).join('');
      cartBodyEl.innerHTML = `
        <div class="cart__items">${{rows}}</div>
        <div class="cart__total"><span>Итого</span><strong>${{escapeHtml(formatMoney(totalMinor))}}</strong></div>
        <button class="cart__submit" type="button">Оформить заявку</button>`;
    }}

    async function loadCatalog() {{
      setState('Загружаем каталог', 'Получаем товары из локального backend API сайта.');
      const suffix = activeFilter === 'all' ? '' : `?containerType=${{encodeURIComponent(activeFilter)}}`;
      try {{
        const response = await fetch(`/api/public/business/catalog${{suffix}}`, {{ headers: {{ 'Accept': 'application/json' }} }});
        if (!response.ok) throw new Error(`Local API error: ${{response.status}}`);
        const data = await response.json();
        updateDiagnostics(data.meta);
        if (data.meta.totalLocalItems === 0) {{
          setState('Каталог скоро появится', 'В локальном каталоге пока нет опубликованных товаров. Оставьте заявку менеджеру Stamm Brewing.');
          return;
        }}
        if (data.items.length === 0) {{
          const label = filterButtons.find((button) => button.dataset.filter === activeFilter)?.textContent || 'выбранному фильтру';
          setState('Ничего не найдено', `В локальном каталоге нет товаров по фильтру «${{label}}». Попробуйте другой фильтр.`);
          return;
        }}
        renderCards(data.items);
        renderCart();
      }} catch (error) {{
        diagnosticsEl.textContent = 'Источник: локальный каталог · ошибка API';
        setState('Не удалось загрузить каталог сайта', 'Попробуйте обновить страницу или свяжитесь с менеджером. Техническое обновление каталога выполняется на стороне сайта.');
      }}
    }}

    document.addEventListener('click', (event) => {{
      const actionButton = event.target.closest('[data-action]');
      if (!actionButton) return;
      const action = actionButton.dataset.action;
      const productId = actionButton.dataset.productId || actionButton.closest('[data-product-id]')?.dataset.productId;
      if (!productId) return;
      if (action === 'increase') changeCartQuantity(productId, 1);
      if (action === 'decrease') changeCartQuantity(productId, -1);
      if (action === 'remove') {{
        const entry = cart.get(String(productId));
        if (entry) setCartQuantity(entry.item, 0);
      }}
    }});

    filterButtons.forEach((button) => {{
      button.addEventListener('click', () => {{
        activeFilter = button.dataset.filter;
        filterButtons.forEach((item) => item.classList.toggle('is-active', item === button));
        loadCatalog();
      }});
    }});

    renderCart();
    loadCatalog();
  </script>
</body>
</html>"""
