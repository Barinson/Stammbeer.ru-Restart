from __future__ import annotations


def business_storefront_page() -> str:
    return """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Бизнес · Stamm Brewing</title>
  <style>
    :root { --golden-malt:#C7B166; --noble-hop:#105859; --foam:#F6F1E3; --ink:#172625; --muted:#667371; --white:#fff; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:Inter, system-ui, -apple-system, Segoe UI, sans-serif; background:var(--foam); color:var(--ink); }
    .hero { background:linear-gradient(135deg, var(--noble-hop), #0b3f40); color:white; padding:56px min(6vw,72px); }
    .hero__eyebrow { color:var(--golden-malt); font-weight:800; text-transform:uppercase; letter-spacing:.12em; font-size:12px; }
    .hero h1 { font-size:clamp(36px,6vw,72px); max-width:880px; margin:14px 0; line-height:.95; }
    .hero p { max-width:680px; color:rgba(255,255,255,.78); font-size:18px; line-height:1.55; }
    .wrap { padding:28px min(6vw,72px) 56px; }
    .toolbar { display:flex; flex-wrap:wrap; justify-content:space-between; gap:16px; align-items:center; margin-bottom:22px; }
    .filters { display:flex; gap:10px; flex-wrap:wrap; }
    .filter { border:1px solid rgba(16,88,89,.22); background:white; color:var(--noble-hop); padding:10px 16px; border-radius:999px; font-weight:800; cursor:pointer; }
    .filter.is-active { background:var(--golden-malt); color:var(--ink); border-color:var(--golden-malt); }
    .diagnostics { font-size:13px; color:var(--muted); background:rgba(255,255,255,.72); border:1px solid rgba(16,88,89,.12); border-radius:14px; padding:10px 14px; }
    .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(250px,1fr)); gap:18px; }
    .product { overflow:hidden; background:white; border:1px solid rgba(16,88,89,.14); border-radius:24px; box-shadow:0 18px 50px rgba(16,88,89,.08); display:flex; flex-direction:column; min-height:430px; }
    .product__image { height:180px; background:radial-gradient(circle at 30% 20%, rgba(199,177,102,.85), transparent 34%), linear-gradient(135deg, #fff7d8, #dfeae1); display:grid; place-items:center; color:var(--noble-hop); font-weight:900; font-size:42px; letter-spacing:.04em; }
    .product__body { padding:20px; display:flex; flex-direction:column; gap:12px; flex:1; }
    .badges { display:flex; gap:8px; flex-wrap:wrap; }
    .badge { font-size:12px; padding:6px 9px; border-radius:999px; background:rgba(16,88,89,.09); color:var(--noble-hop); font-weight:800; }
    .badge--availability { background:rgba(199,177,102,.28); color:#4b3f14; }
    h2 { margin:0; font-size:21px; line-height:1.1; }
    .subtitle { margin:0; color:var(--muted); line-height:1.45; min-height:42px; }
    .meta { display:flex; justify-content:space-between; gap:12px; font-weight:800; }
    .cta { margin-top:auto; border:0; background:var(--noble-hop); color:white; border-radius:14px; padding:12px 14px; font-weight:900; cursor:pointer; }
    .cta[disabled] { opacity:.48; cursor:not-allowed; }
    .state { background:white; border:1px solid rgba(16,88,89,.14); border-radius:24px; padding:34px; text-align:center; color:var(--muted); }
    .state strong { display:block; color:var(--ink); font-size:22px; margin-bottom:8px; }
  </style>
</head>
<body>
  <section class="hero">
    <div class="hero__eyebrow">Stamm Brewing · B2B</div>
    <h1>Каталог для баров, ресторанов и партнёров</h1>
    <p>Первый рабочий storefront читает локальный каталог сайта. Публичная страница работает только с локальными данными сайта.</p>
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
    <div id="state" class="state"><strong>Загружаем каталог</strong>Получаем товары из локального backend API сайта.</div>
    <section id="grid" class="grid" hidden></section>
  </main>
  <script>
    const stateEl = document.getElementById('state');
    const gridEl = document.getElementById('grid');
    const diagnosticsEl = document.getElementById('diagnostics');
    const filterButtons = [...document.querySelectorAll('.filter')];
    let activeFilter = 'all';

    function setState(title, text) {
      stateEl.hidden = false;
      gridEl.hidden = true;
      stateEl.innerHTML = `<strong>${title}</strong>${text}`;
    }

    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
    }

    function placeholder(name) {
      return (name || 'SB').trim().split(' ').slice(0, 2).map((part) => part[0]).join('').toUpperCase();
    }

    function renderCards(items) {
      gridEl.innerHTML = items.map((item) => {
        const safeName = escapeHtml(item.name);
        const safeSubtitle = escapeHtml(item.subtitle || '');
        const safeContainer = escapeHtml(item.containerLabel);
        const safeAvailability = escapeHtml(item.availability.label);
        const safeVolume = item.volumeLiters ? `${escapeHtml(item.volumeLiters)} л` : 'Объём уточняется';
        const safePrice = escapeHtml(item.price.label);
        const safeCta = escapeHtml(item.ctaLabel);
        return `
        <article class="product">
          <div class="product__image">${item.imageUrl ? `<img src="${escapeHtml(item.imageUrl)}" alt="${safeName}">` : placeholder(item.name)}</div>
          <div class="product__body">
            <div class="badges"><span class="badge">${safeContainer}</span><span class="badge badge--availability">${safeAvailability}</span></div>
            <h2>${safeName}</h2>
            <p class="subtitle">${safeSubtitle}</p>
            <div class="meta"><span>${safeVolume}</span><span>${safePrice}</span></div>
            <button class="cta" ${item.ctaLabel === 'Недоступно' ? 'disabled' : ''}>${safeCta}</button>
          </div>
        </article>
      `}).join('');
      stateEl.hidden = true;
      gridEl.hidden = false;
    }

    function updateDiagnostics(meta) {
      const updated = meta.lastCatalogSyncAt || 'ещё не обновлялся';
      diagnosticsEl.textContent = `Источник: ${meta.readModel} · товаров: ${meta.returnedItems}/${meta.totalLocalItems} · обновлено: ${updated}`;
    }

    async function loadCatalog() {
      setState('Загружаем каталог', 'Получаем товары из локального backend API сайта.');
      const suffix = activeFilter === 'all' ? '' : `?containerType=${encodeURIComponent(activeFilter)}`;
      try {
        const response = await fetch(`/api/public/business/catalog${suffix}`, { headers: { 'Accept': 'application/json' } });
        if (!response.ok) throw new Error(`Local API error: ${response.status}`);
        const data = await response.json();
        updateDiagnostics(data.meta);
        if (data.meta.totalLocalItems === 0) {
          setState('Каталог скоро появится', 'В локальном каталоге пока нет опубликованных товаров. Оставьте заявку менеджеру Stamm Brewing.');
          return;
        }
        if (data.items.length === 0) {
          const label = filterButtons.find((button) => button.dataset.filter === activeFilter)?.textContent || 'выбранному фильтру';
          setState('Ничего не найдено', `В локальном каталоге нет товаров по фильтру «${label}». Попробуйте другой фильтр.`);
          return;
        }
        renderCards(data.items);
      } catch (error) {
        diagnosticsEl.textContent = 'Источник: локальный каталог · ошибка API';
        setState('Не удалось загрузить каталог сайта', 'Попробуйте обновить страницу или свяжитесь с менеджером. Техническое обновление каталога выполняется на стороне сайта.');
      }
    }

    filterButtons.forEach((button) => {
      button.addEventListener('click', () => {
        activeFilter = button.dataset.filter;
        filterButtons.forEach((item) => item.classList.toggle('is-active', item === button));
        loadCatalog();
      });
    });

    loadCatalog();
  </script>
</body>
</html>"""
