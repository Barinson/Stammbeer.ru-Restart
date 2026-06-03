from __future__ import annotations

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
    input, select {{ width:100%; padding:12px 14px; border:1px solid rgba(16,88,89,.25); border-radius:12px; font:inherit; }}
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
              <td>{escape(str(item.get('stock_quantity') or 0))} · {escape(str(item.get('availability_status') or ''))}</td>
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


def moysklad_settings_page(user_email: str, settings: dict[str, object], result: str | None = None, error: str | None = None) -> str:
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
          </form>
        </div>
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
