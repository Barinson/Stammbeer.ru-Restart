from __future__ import annotations

import json
from html import escape
NAV_ITEMS = [
    ("/admin", "Dashboard"),
    ("/admin/catalog", "Каталог"),
    ("/admin/moysklad", "МойСклад"),
    ("/admin/b2b-orders", "B2B-заявки"),
    ("/admin/content", "Контент"),
    ("/admin/users", "Пользователи и роли"),
    ("/admin/profile", "Профиль"),
]


def page(title: str, body: str, user_email: str | None = None) -> str:
    auth = ""
    nav = ""
    if user_email:
        auth = f"<div class='user'>{escape(user_email)} · <a href='/admin/logout'>Выйти</a></div>"
        nav = "".join(f"<a href='{href}'>{label}</a>" for href, label in NAV_ITEMS)
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} · Stamm Brewing</title>
  <style>
    :root {{ --golden-malt:#C7B166; --noble-hop:#105859; --foam:#F6F1E3; --ink:#172625; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:Inter, system-ui, -apple-system, Segoe UI, sans-serif; background:var(--foam); color:var(--ink); }}
    a {{ color:var(--noble-hop); }}
    .shell {{ display:grid; grid-template-columns:260px 1fr; min-height:100vh; }}
    aside {{ background:var(--noble-hop); color:white; padding:28px 20px; }}
    aside h1 {{ font-size:20px; margin:0 0 28px; color:var(--golden-malt); }}
    nav a {{ display:block; padding:12px 14px; margin:4px 0; color:white; text-decoration:none; border-radius:12px; }}
    nav a:hover {{ background:rgba(255,255,255,.12); }}
    main {{ padding:32px; }}
    .topbar {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:24px; }}
    .card {{ background:white; border:1px solid rgba(16,88,89,.14); border-radius:20px; padding:24px; box-shadow:0 14px 40px rgba(16,88,89,.08); margin-bottom:18px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:18px; }}
    label {{ display:block; font-weight:700; margin:14px 0 6px; }}
    input, select, textarea {{ width:100%; padding:12px 14px; border:1px solid rgba(16,88,89,.25); border-radius:12px; font:inherit; }}
    input[type=checkbox] {{ width:auto; }}
    button, .button {{ border:0; background:var(--noble-hop); color:white; padding:12px 16px; border-radius:12px; font-weight:800; cursor:pointer; text-decoration:none; display:inline-block; }}
    button.secondary {{ background:var(--golden-malt); color:#172625; }}
    .muted {{ color:#64706f; }}
    .status {{ display:inline-flex; padding:6px 10px; border-radius:999px; background:rgba(199,177,102,.25); }}
    .login {{ max-width:420px; margin:10vh auto; }}
    .error {{ background:#fff0f0; border:1px solid #e9b0b0; color:#8a1f1f; padding:12px; border-radius:12px; }}
    .success {{ background:#eefaf4; border:1px solid #a7ddbf; color:#185c35; padding:12px; border-radius:12px; }}
  </style>
</head>
<body>
  {f"<div class='shell'><aside><h1>Stamm Admin</h1><nav>{nav}</nav></aside><main><div class='topbar'><h2>{escape(title)}</h2>{auth}</div>{body}</main></div>" if user_email else body}
</body>
</html>"""


def login_page(error: str | None = None) -> str:
    message = f"<div class='error'>{escape(error)}</div>" if error else ""
    return page(
        "Вход в админку",
        f"""
        <main class="login">
          <div class="card">
            <h1>Stamm Brewing Admin</h1>
            <p class="muted">Защищённая зона управления сайтом.</p>
            {message}
            <form method="post" action="/admin/login">
              <label>Логин</label>
              <input name="email" type="text" required autofocus>
              <label>Пароль</label>
              <input name="password" type="password" required>
              <p><button type="submit">Войти</button></p>
            </form>
          </div>
        </main>
        """,
    )



def format_price_minor(price_minor: object, currency: object = "RUB") -> str:
    if price_minor is None or price_minor == "":
        return "—"
    try:
        amount = int(price_minor) / 100
    except (TypeError, ValueError):
        return str(price_minor)
    currency_label = "₽" if (currency or "RUB") == "RUB" else str(currency)
    return f"{amount:,.2f} {currency_label}".replace(",", " ")


def format_quantity(value: object) -> str:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        return "0"
    if amount.is_integer():
        return str(int(amount))
    return f"{amount:.2f}"

def dashboard(user_email: str, stats: dict[str, object]) -> str:
    cards = "".join(
        f"<div class='card'><strong>{escape(str(label))}</strong><p class='status'>{escape(str(value))}</p></div>"
        for label, value in stats.items()
    )
    return page("Dashboard", f"<div class='grid'>{cards}</div>", user_email)


def placeholder(title: str, description: str, user_email: str) -> str:
    return page(title, f"<div class='card'><p>{escape(description)}</p><p class='muted'>Каркас раздела готов для следующего этапа реализации.</p></div>", user_email)


def admin_catalog_page(user_email: str, items: list[dict[str, object]], result: str | None = None, error: str | None = None) -> str:
    notice = ""
    if result:
        notice = f"<div class='success'>{escape(result)}</div>"
    if error:
        notice = f"<div class='error'>{escape(error)}</div>"
    if items:
        rows = "".join(
            f"""
            <tr>
              <td>{escape(str(item.get('public_name') or item.get('accounting_name') or ''))}</td>
              <td>{escape(str(item.get('container_type') or '—'))}</td>
              <td>{escape(format_price_minor(item.get('price_minor'), item.get('currency')))}</td>
              <td>{escape(format_quantity(item.get('available_quantity') if item.get('available_quantity') is not None else item.get('stock_quantity')))} · {escape(str(item.get('availability_status') or ''))}<br><small>остаток {escape(format_quantity(item.get('latest_stock') if item.get('latest_stock') is not None else item.get('stock_quantity')))}, резерв {escape(format_quantity(item.get('latest_reserve')))}</small></td>
              <td>МойСклад<br><small>{escape(str(item.get('sync_state') or ''))}</small></td>
              <td>{'Опубликовано' if item.get('is_published') else 'Скрыто'}</td>
              <td>{escape(str(item.get('last_synced_at') or '—'))}</td>
              <td>
                <form method="post" action="/admin/catalog/publication">
                  <input type="hidden" name="product_id" value="{escape(str(item.get('id')))}">
                  <input type="hidden" name="publish" value="{'0' if item.get('is_published') else '1'}">
                  <button type="submit">{'Скрыть' if item.get('is_published') else 'Опубликовать'}</button>
                </form>
              </td>
            </tr>
            """
            for item in items
        )
        table = f"""
          <table style="width:100%; border-collapse:collapse;">
            <thead><tr><th>Название</th><th>Тара</th><th>Цена продажи / 1 SKU</th><th>Доступно</th><th>Источник</th><th>Публикация</th><th>Sync</th><th></th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        """
    else:
        table = "<div class='card'><p>Локальный каталог пока пуст. Запустите ручную синхронизацию в разделе МойСклад.</p></div>"
    return page("Каталог", f"{notice}<div class='card'><h3>Локальный каталог админки</h3><p class='muted'>SKU из МойСклад сначала попадают сюда. В публичный магазин попадают только опубликованные позиции.</p>{table}</div>", user_email)


def moysklad_reference_select(name: str, label: str, options: list[dict[str, object]], selected_href: str | None) -> str:
    if not options:
        return f"""
            <label>{escape(label)}</label>
            <select name="{escape(name)}" disabled>
              <option value="">Сначала проверьте подключение</option>
            </select>
        """
    option_html = ['<option value="">Не выбрано</option>']
    for option in options:
        href = str(option.get("href") or "")
        name_text = str(option.get("name") or href)
        selected = " selected" if href == selected_href else ""
        option_html.append(f'<option value="{escape(href)}"{selected}>{escape(name_text)}</option>')
    return f"""
            <label>{escape(label)}</label>
            <select name="{escape(name)}">
              {''.join(option_html)}
            </select>
        """



def diagnostic_block(diagnostics: dict[str, object] | None) -> str:
    if not diagnostics:
        return ""
    sections = []
    for key, title in (
        ("folderCandidates", "1. SKU из выбранной папки"),
        ("stockReportRows", "2. Строки складского отчёта"),
        ("matching", "3. Matching SKU ↔ stock report"),
        ("dbWrites", "4. Запись в локальную БД"),
        ("localCatalogAfterSync", "5. Локальный каталог после sync"),
    ):
        payload = diagnostics.get(key) if isinstance(diagnostics, dict) else None
        pretty = json.dumps(payload or [], ensure_ascii=False, indent=2)
        sections.append(f"<h4>{escape(title)}</h4><pre style='white-space:pre-wrap; overflow:auto; max-height:340px; background:#f7f8f3; padding:14px; border-radius:12px;'>{escape(pretty)}</pre>")
    return f"<div class='card'><h3>Diagnostic mode: последний sync</h3><p class='muted'>Показывает фактическую цепочку: папка товаров → складской отчёт → matching → запись в БД.</p>{''.join(sections)}</div>"

def moysklad_settings_page(user_email: str, settings: dict[str, object], result: str | None = None, error: str | None = None, diagnostics: dict[str, object] | None = None) -> str:
    notice = ""
    if result:
        notice = f"<div class='success'>{escape(result)}</div>"
    if error:
        notice = f"<div class='error'>{escape(error)}</div>"
    checked_child = "checked" if settings.get("includeChildFolders") else ""
    checked_enabled = "checked" if settings.get("isEnabled") else ""
    token_help = "Токен сохранён" if settings.get("hasToken") else "Токен ещё не сохранён"
    return page(
        "МойСклад",
        f"""
        <div class="card">
          <h3>Настройки подключения JSON API 1.2</h3>
          <p class="muted">Экран сохраняет настройки интеграции. Полный sync worker будет подключён следующим этапом.</p>
          {notice}
          <form method="post" action="/admin/moysklad/save">
            <label>API base URL</label>
            <input name="api_base_url" value="{escape(str(settings.get('apiBaseUrl') or ''))}" required>
            <label>Bearer token</label>
            <input name="token" type="password" placeholder="{escape(str(settings.get('tokenMasked') or token_help))}">
            {moysklad_reference_select('store_href', 'Склад для остатков', settings.get('availableStores') or [], (settings.get('selectedStore') or {}).get('href'))}
            {moysklad_reference_select('source_product_folder_href', 'Папка-источник продукции', settings.get('availableProductFolders') or [], (settings.get('sourceProductFolder') or {}).get('href'))}
            <p class="muted">Списки складов и папок загружаются из МойСклад после успешной проверки подключения. Href сохраняется вместе с id и названием выбранной API-сущности.</p>
            <label><input type="checkbox" name="include_child_folders" {checked_child}> Включать дочерние папки при будущей синхронизации</label>
            <label>Full sync interval, минут</label>
            <input name="full_sync_interval_minutes" type="number" min="15" value="{escape(str(settings.get('fullSyncIntervalMinutes') or 360))}">
            <label>Stock sync interval, минут</label>
            <input name="stock_sync_interval_minutes" type="number" min="15" value="{escape(str(settings.get('stockSyncIntervalMinutes') or 120))}">
            <label><input type="checkbox" name="is_enabled" {checked_enabled}> Включить плановую синхронизацию после подключения worker</label>
            <p>
              <button type="submit">Сохранить</button>
              <button class="secondary" formaction="/admin/moysklad/test" formmethod="post">Проверить подключение</button>
              <button class="secondary" formaction="/admin/moysklad/sync-products" formmethod="post">Синхронизировать товары сейчас</button>
            </p>
            <label><input type="checkbox" name="diagnostic_mode"> Diagnostic mode: сохранить подробную отладку первых 10 SKU/stock rows</label>
          </form>
        </div>
        {diagnostic_block(diagnostics)}
        <div class="card">
          <h3>Текущее состояние</h3>
          <p>Последняя успешная синхронизация: <strong>{escape(str(settings.get('lastSuccessAt') or 'ещё не выполнялась'))}</strong></p>
          <p>Последняя ошибка: <strong>{escape(str(settings.get('lastErrorAt') or 'нет'))}</strong></p>
          <p>Справочники загружены: <strong>{escape(str(settings.get('referencesLoadedAt') or 'ещё не загружались'))}</strong></p>
          <p>Выбранный склад: <strong>{escape(str((settings.get('selectedStore') or {}).get('name') or 'не выбран'))}</strong></p>
          <p>Папка продукции: <strong>{escape(str((settings.get('sourceProductFolder') or {}).get('name') or 'не выбрана'))}</strong></p>
          <p class="muted">Публичный раздел «Бизнес» не использует эти настройки напрямую и будет читать только локальную read-model.</p>
        </div>
        """,
        user_email,
    )



def content_management_page(user_email: str, content: dict[str, object], result: str | None = None, error: str | None = None) -> str:
    notice = ""
    if result:
        notice = f"<div class='success'>{escape(result)}</div>"
    if error:
        notice = f"<div class='error'>{escape(error)}</div>"
    home = content.get("home") or {}
    business = content.get("business") or {}
    menu_items = content.get("menu") or []
    actions = content.get("actions") or []
    logo_url = str(home.get("home_logo_url") or "")
    content_bg_url = str(home.get("home_content_bg_url") or "")
    news_image_url = str(home.get("home_news_image_url") or "")
    title = str(home.get("home_hero_title") or "STAMM")
    subtitle = str(home.get("home_hero_subtitle") or "BREWING")
    title_size = str(home.get("home_hero_title_size_px") or "152")
    title_weight = str(home.get("home_hero_title_weight") or "950")
    subtitle_size = str(home.get("home_hero_subtitle_size_px") or "112")
    subtitle_weight = str(home.get("home_hero_subtitle_weight") or "950")
    line_gap = str(home.get("home_hero_line_gap_px") or "0")
    news_title = str(home.get("home_news_title") or "")
    news_text = str(home.get("home_news_text") or "")
    news_link_url = str(home.get("home_news_link_url") or "")
    news_link_label = str(home.get("home_news_link_label") or "")
    min_order_minor = str(business.get("business_min_order_amount_minor") or "1500000")
    logo_preview = f"<img class='cms-hero-preview__logo' src='{escape(logo_url)}' alt='Логотип главной'>" if logo_url else "<div class='cms-hero-preview__mark' aria-hidden='true'></div>"
    logo_admin_preview = f"<p><img src='{escape(logo_url)}' alt='Логотип главной' style='max-width:154px; max-height:154px; object-fit:contain;'></p>" if logo_url else "<p class='muted'>Логотип ещё не загружен. Будет показан фирменный знак-заглушка.</p>"
    content_bg_preview = f"<img class='cms-bg-preview__image' src='{escape(content_bg_url)}' alt='Фон контентной части'>" if content_bg_url else "<div class='cms-bg-preview__image cms-bg-preview__image--fallback' aria-hidden='true'></div>"
    news_image_inner = f"<img class='cms-news-preview__image' src='{escape(news_image_url)}' alt='Изображение новости'>" if news_image_url else "<div class='cms-news-preview__image cms-news-preview__image--fallback' aria-hidden='true'></div>"
    news_image_preview = f"<a class='cms-news-preview__image-link' href='{escape(news_link_url)}'>{news_image_inner}</a>" if news_link_url else news_image_inner
    menu_rows = "".join(
        f"""
        <tr>
          <td>{escape(str(item.get('key') or ''))}</td>
          <td><input name="menu_{escape(str(item.get('key')))}_label" value="{escape(str(item.get('label') or ''))}"></td>
          <td>{escape(str(item.get('href') or ''))}</td>
          <td><input name="menu_{escape(str(item.get('key')))}_sort_order" type="number" value="{escape(str(item.get('sort_order') or 100))}"></td>
          <td><input name="menu_{escape(str(item.get('key')))}_visible" type="checkbox" {'checked' if item.get('is_visible') else ''}></td>
        </tr>
        """
        for item in menu_items
    )
    action_rows = "".join(
        f"""
        <tr>
          <td>{escape(str(item.get('key') or ''))}</td>
          <td><input name="action_{escape(str(item.get('key')))}_label" value="{escape(str(item.get('label') or ''))}"></td>
          <td><input name="action_{escape(str(item.get('key')))}_href" value="{escape(str(item.get('href') or ''))}"></td>
          <td>
            {f"<img src='{escape(str(item.get('icon_url') or ''))}' alt='' style='width:36px; height:36px; object-fit:contain; display:block; margin-bottom:6px;'>" if item.get('icon_url') else "<span class='muted'>fallback text</span>"}
            <input type="hidden" name="action_{escape(str(item.get('key')))}_icon_url" value="{escape(str(item.get('icon_url') or ''))}">
            <input name="action_{escape(str(item.get('key')))}_icon_file" type="file" accept="image/*">
          </td>
          <td><input name="action_{escape(str(item.get('key')))}_sort_order" type="number" value="{escape(str(item.get('sort_order') or 100))}"></td>
          <td><input name="action_{escape(str(item.get('key')))}_visible" type="checkbox" {'checked' if item.get('is_visible') else ''}></td>
        </tr>
        """
        for item in actions
    )
    return page(
        "Контент",
        f"""
        <style>
          .cms-preview-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:18px; align-items:stretch; }}
          .cms-hero-preview {{ min-height:360px; display:grid; place-items:center; text-align:center; border-radius:22px; padding:32px; background:radial-gradient(circle at 50% 18%, rgba(199,177,102,.2), transparent 30%), linear-gradient(135deg, #105859, #0b3f40); }}
          .cms-hero-preview__inner {{ display:grid; justify-items:center; }}
          .cms-hero-preview__logo {{ max-width:154px; max-height:154px; object-fit:contain; margin-bottom:28px; }}
          .cms-hero-preview__mark {{ width:94px; height:94px; border-radius:999px; border:2px solid rgba(199,177,102,.5); margin-bottom:28px; background:radial-gradient(circle, rgba(199,177,102,.32), transparent 58%); }}
          .cms-hero-preview__title {{ margin:0; color:#F6F1E3; line-height:.78; letter-spacing:.08em; font-size:clamp(48px,9vw,{escape(title_size)}px); font-weight:{escape(title_weight)}; }}
          .cms-hero-preview__subtitle {{ margin:{escape(line_gap)}px 0 0; color:#C7B166; line-height:.8; letter-spacing:.08em; font-size:clamp(36px,7vw,{escape(subtitle_size)}px); font-weight:{escape(subtitle_weight)}; }}
          .cms-bg-preview {{ min-height:240px; border-radius:22px; overflow:hidden; position:relative; background:#0d4b4c; }}
          .cms-bg-preview__image {{ width:100%; height:100%; min-height:240px; object-fit:cover; display:block; }}
          .cms-bg-preview__image--fallback {{ background:linear-gradient(135deg, rgba(16,88,89,.9), rgba(11,63,64,.96)); }}
          .cms-bg-preview::after {{ content:""; position:absolute; inset:0; background:linear-gradient(180deg, rgba(16,88,89,.62), rgba(11,63,64,.78)); pointer-events:none; }}
          .cms-news-preview {{ display:grid; grid-template-columns:minmax(220px,360px) 1fr; gap:22px; align-items:center; border-radius:0; padding:0; background:transparent; color:#F6F1E3; }}
          .cms-news-preview__image-link {{ display:block; text-decoration:none; border-radius:18px; }}
          .cms-news-preview__image {{ width:100%; aspect-ratio:16/10; border-radius:18px; object-fit:cover; background:rgba(246,241,227,.08); display:block; }}
          .cms-news-preview__image--fallback {{ background:radial-gradient(circle, rgba(199,177,102,.32), transparent 38%), linear-gradient(135deg, rgba(246,241,227,.1), rgba(16,88,89,.45)); }}
          .cms-news-preview h4 {{ margin:0 0 8px; font-size:26px; }}
          .cms-news-preview p {{ margin:0; color:rgba(246,241,227,.78); }}
          @media (max-width:760px) {{ .cms-news-preview {{ grid-template-columns:1fr; }} }}
        </style>
        {notice}
        <form method="post" action="/admin/content/save" enctype="multipart/form-data">
          <div class="card">
            <h3>Главная / Hero</h3>
            <p class="muted">Управляет full screen welcome-экраном главной: логотип, верхняя надпись и нижняя золотая надпись.</p>
            <div class="cms-preview-grid">
              <div>
                <label>Основная большая надпись</label>
                <input name="home_hero_title" value="{escape(title)}">
                <label>Подзаголовок под ней</label>
                <input name="home_hero_subtitle" value="{escape(subtitle)}">
                <div class="grid">
                  <div>
                    <label>Размер STAMM, px</label>
                    <input name="home_hero_title_size_px" type="number" min="24" max="220" value="{escape(title_size)}">
                  </div>
                  <div>
                    <label>Толщина STAMM</label>
                    <input name="home_hero_title_weight" type="number" min="100" max="1000" step="50" value="{escape(title_weight)}">
                  </div>
                  <div>
                    <label>Размер BREWING, px</label>
                    <input name="home_hero_subtitle_size_px" type="number" min="24" max="220" value="{escape(subtitle_size)}">
                  </div>
                  <div>
                    <label>Толщина BREWING</label>
                    <input name="home_hero_subtitle_weight" type="number" min="100" max="1000" step="50" value="{escape(subtitle_weight)}">
                  </div>
                  <div>
                    <label>Отступ STAMM → BREWING, px</label>
                    <input name="home_hero_line_gap_px" type="number" min="0" max="140" value="{escape(line_gap)}">
                  </div>
                </div>
                <label>Logo asset главной</label>
                {logo_admin_preview}
                <input type="hidden" name="home_logo_url" value="{escape(logo_url)}">
                <input name="home_logo_file" type="file" accept="image/*">
                <p class="muted">Большие файлы сохраняются как media asset, а в preview и на сайте автоматически вписываются в безопасный размер через object-fit/max-size без потери пропорций.</p>
              </div>
              <div class="cms-hero-preview" aria-label="Preview hero главной">
                <div class="cms-hero-preview__inner">
                  {logo_preview}
                  <h4 class="cms-hero-preview__title">{escape(title)}</h4>
                  <div class="cms-hero-preview__subtitle">{escape(subtitle)}</div>
                </div>
              </div>
            </div>
          </div>
          <div class="card">
            <h3>Главная / Фон контентной части</h3>
            <p class="muted">Фото-подложка начинается ниже чистого hero-экрана и используется для контентных блоков главной с фирменным зелёным overlay.</p>
            <div class="cms-preview-grid">
              <div>
                <label>Фоновое изображение контентной части</label>
                {f"<p><img src='{escape(content_bg_url)}' alt='Фон контентной части' style='max-width:260px; max-height:170px; object-fit:cover; border-radius:12px;'></p>" if content_bg_url else "<p class='muted'>Фоновое изображение ещё не загружено. Будет использован фирменный зелёный fallback.</p>"}
                <input type="hidden" name="home_content_bg_url" value="{escape(content_bg_url)}">
                <input name="home_content_bg_file" type="file" accept="image/*">
                <p class="muted">Файл сохраняется в локальные media assets, масштабируется через cover и перекрывается полупрозрачным фирменным слоем для читаемости.</p>
              </div>
              <div class="cms-bg-preview" aria-label="Preview фоновой подложки">
                {content_bg_preview}
              </div>
            </div>
          </div>
          <div class="card">
            <h3>Главная / Новость</h3>
            <p class="muted">Этот блок идёт сразу после первого экрана и полностью управляется из админки.</p>
            <div class="cms-preview-grid">
              <div>
                <label>Заголовок новости</label>
                <input name="home_news_title" value="{escape(news_title)}">
                <label>Текст новости</label>
                <textarea name="home_news_text" rows="5">{escape(news_text)}</textarea>
                <label>Изображение новости</label>
                {f"<p><img src='{escape(news_image_url)}' alt='Изображение новости' style='max-width:220px; max-height:150px; object-fit:cover; border-radius:12px;'></p>" if news_image_url else "<p class='muted'>Изображение новости ещё не загружено.</p>"}
                <input type="hidden" name="home_news_image_url" value="{escape(news_image_url)}">
                <input name="home_news_image_file" type="file" accept="image/*">
                <label>Ссылка изображения новости</label>
                <input name="home_news_link_url" value="{escape(news_link_url)}">
                <label>Подпись ссылки для доступности</label>
                <input name="home_news_link_label" value="{escape(news_link_label)}">
              </div>
              <article class="cms-news-preview" aria-label="Preview новости">
                {news_image_preview}
                <div>
                  <h4>{escape(news_title)}</h4>
                  <p>{escape(news_text)}</p>
                </div>
              </article>
            </div>
          </div>
          <div class="card">
            <h3>Бизнес / Заказы</h3>
            <p class="muted">Настройки ограничений B2B-магазина. Стартовое правило: минимальный заказ 15 000 ₽.</p>
            <label>Минимальная сумма заказа, копейки</label>
            <input name="business_min_order_amount_minor" type="number" min="0" step="100" value="{escape(min_order_minor)}">
            <p class="muted">1500000 = 15 000 ₽. Значение применяется в публичной корзине и повторно проверяется backend при отправке заявки.</p>
          </div>
          <div class="card">
            <h3>Навигация / Верхнее меню</h3>
            <p class="muted">Отдельного пункта «Главная» здесь нет: переход на главную выполняет бренд Stamm Brewing слева сверху.</p>
            <table style="width:100%; border-collapse:collapse;">
              <thead><tr><th>Ключ</th><th>Название</th><th>Ссылка</th><th>Порядок</th><th>Показывать</th></tr></thead>
              <tbody>{menu_rows}</tbody>
            </table>
          </div>
          <div class="card">
            <h3>Навигация / Ярлыки справа</h3>
            <p class="muted">Управление ссылками TG, VK, Untappd, Корзина и Личный кабинет. Личный кабинет — только ярлык для будущего этапа.</p>
            <table style="width:100%; border-collapse:collapse;">
              <thead><tr><th>Ключ</th><th>Ярлык</th><th>Ссылка</th><th>Иконка</th><th>Порядок</th><th>Показывать</th></tr></thead>
              <tbody>{action_rows}</tbody>
            </table>
          </div>
          <p><button type="submit">Сохранить контент</button></p>
        </form>
        """,
        user_email,
    )

def profile_page(user_email: str, result: str | None = None, error: str | None = None) -> str:
    notice = ""
    if result:
        notice = f"<div class='success'>{escape(result)}</div>"
    if error:
        notice = f"<div class='error'>{escape(error)}</div>"
    return page(
        "Профиль",
        f"""
        <div class="card">
          <h3>Смена пароля</h3>
          <p class="muted">Локальный dev-admin может сменить пароль без изменения переменных окружения.</p>
          {notice}
          <form method="post" action="/admin/profile/password">
            <label>Текущий пароль</label>
            <input name="current_password" type="password" required>
            <label>Новый пароль</label>
            <input name="new_password" type="password" required>
            <label>Подтверждение нового пароля</label>
            <input name="new_password_confirm" type="password" required>
            <p><button type="submit">Сохранить пароль</button></p>
          </form>
        </div>
        """,
        user_email,
    )
