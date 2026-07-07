from __future__ import annotations

import json
from html import escape
from urllib.parse import quote
from typing import Any

from app.modules.content.service import ACTION_DEFAULTS, BUSINESS_DEFAULTS, CONTACT_DEFAULTS, GALLERY_DEFAULTS, HOME_DEFAULTS, LAYOUT_DEFAULTS, MENU_DEFAULTS, SITE_DEFAULTS, TYPOGRAPHY_DEFAULTS


PUBLIC_HEAD = """<meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\">
  <link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>
  <link href=\"https://fonts.googleapis.com/css2?family=Jost:wght@400;500;700;800;900&display=swap\" rel=\"stylesheet\">"""

SEO_DEFAULTS = {
    "home": ("Stamm Brewing — крафтовая пивоварня", "Stamm Brewing: крафтовая пивоварня, новости, партнёры и контакты."),
    "beer": ("Пиво Stamm Brewing", "Раздел пива Stamm Brewing: новинки, постоянная линейка, сезонные сорта и точки продаж."),
    "business": ("Бизнес · Stamm Brewing", "B2B-раздел Stamm Brewing для партнёров, заказов и сотрудничества."),
    "contacts": ("Контакты Stamm Brewing", "Контакты Stamm Brewing: e-mail, телефоны, адрес производства и карта."),
    "visit": ("Stammhaus · Посетить пивоварню", "Информация о посещении пивоварни Stamm Brewing и будущих гостевых разделах."),
    "gallery": ("Галерея Stamm Brewing", "Фотогалерея Stamm Brewing: производство, команда, события и атмосфера пивоварни."),
    "maintenance": ("Технические работы · Stamm Brewing", "Сайт Stamm Brewing временно находится на технических работах."),
}


def _absolute_url(base_url: str, path_or_url: object) -> str:
    value = str(path_or_url or "").strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        return value
    if not value.startswith("/"):
        value = "/" + value
    return base_url.rstrip("/") + value


def _site_default(key: str, fallback: str) -> str:
    value = SITE_DEFAULTS.get(key, fallback)
    return str(value if value is not None else fallback)


def _site_default_int(key: str, fallback: int) -> int:
    try:
        return int(str(SITE_DEFAULTS.get(key, fallback) or fallback))
    except (TypeError, ValueError):
        return fallback


def seo_head(content: dict[str, Any] | None, page_key: str, path: str, title: str | None = None, description: str | None = None, robots: str = "index,follow") -> str:
    site_content = public_content_or_defaults(content)
    site = site_content.get("site") or {}
    default_title, default_description = SEO_DEFAULTS.get(page_key, (str(site.get("site_title") or "Stamm Brewing"), str(site.get("site_description") or "")))
    title_value = str(title or default_title or site.get("site_title") or "Stamm Brewing")
    description_value = str(description or default_description or site.get("site_description") or "Stamm Brewing")
    base_url = str(site.get("site_public_base_url") or _site_default("site_public_base_url", "https://stammbeer.ru")).rstrip("/")
    canonical = _absolute_url(base_url, path)
    og_image = _absolute_url(base_url, site.get("site_og_image_url") or site.get("site_favicon_url") or "")
    favicon = str(site.get("site_favicon_url") or SITE_DEFAULTS.get("site_favicon_url") or "").strip()
    favicon_link = f'\n  <link rel="icon" href="{escape(favicon)}">' if favicon else ""
    image_meta = f'\n  <meta property="og:image" content="{escape(og_image)}">' if og_image else ""
    return f"""{PUBLIC_HEAD}
  <title>{escape(title_value)}</title>
  <meta name="description" content="{escape(description_value)}">
  <meta name="robots" content="{escape(robots)}">
  <link rel="canonical" href="{escape(canonical)}">{favicon_link}
  <meta property="og:title" content="{escape(title_value)}">
  <meta property="og:description" content="{escape(description_value)}">
  <meta property="og:type" content="website">
  <meta property="og:url" content="{escape(canonical)}">{image_meta}"""


BASE_CSS = """
    :root { --golden-malt:#C7B166; --noble-hop:#105859; --deep-hop:#0b3f40; --card-hop:#0d4b4c; --card-hop-soft:#145f60; --foam:#F6F1E3; --ink:#172625; --muted:#b8c7c4; --white:#fff; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:'Jost', system-ui, -apple-system, Segoe UI, sans-serif; background:var(--noble-hop); color:var(--foam); font-size:var(--stamm-body-font-size,16px); }
    a { color:inherit; }
    .top-nav { position:fixed; top:0; left:0; right:0; z-index:50; display:flex; align-items:center; justify-content:space-between; gap:18px; padding:14px min(6vw,72px); background:rgba(11,63,64,.94); border-bottom:1px solid rgba(199,177,102,.18); backdrop-filter:blur(12px); }
    .brand { color:var(--golden-malt); font-weight:900; letter-spacing:.12em; text-transform:uppercase; text-decoration:none; white-space:nowrap; }
    .nav-links { display:flex; align-items:center; justify-content:center; gap:clamp(34px,4vw,64px); flex-wrap:wrap; font-size:var(--stamm-nav-font-size,14px); font-weight:700; }
    .nav-links a { color:rgba(246,241,227,.82); text-decoration:none; }
    .nav-links a.is-active, .nav-links a:hover { color:var(--golden-malt); }
    .nav-actions { display:flex; align-items:center; gap:9px; }
    .nav-icon { width:32px; height:32px; border:0; border-radius:999px; display:grid; place-items:center; background:var(--golden-malt); color:var(--ink); text-decoration:none; font-size:11px; font-weight:900; line-height:1; overflow:hidden; padding:0; }
    .nav-icon img { width:100%; height:100%; padding:0; object-fit:contain; display:block; border-radius:inherit; }
    .mobile-menu-toggle, .mobile-drawer { display:none; }
    .mobile-menu-toggle { border:1px solid rgba(199,177,102,.36); border-radius:12px; width:34px; height:34px; padding:0; background:rgba(246,241,227,.08); color:var(--golden-malt); cursor:pointer; place-items:center; }
    .mobile-menu-toggle span, .mobile-menu-toggle::before, .mobile-menu-toggle::after { content:""; display:block; width:15px; height:2px; border-radius:999px; background:currentColor; }
    .mobile-menu-toggle span { margin:4px 0; }
    .mobile-menu-toggle--image { border-color:rgba(199,177,102,.28); background:transparent; overflow:hidden; }
    .mobile-menu-toggle--image span, .mobile-menu-toggle--image::before, .mobile-menu-toggle--image::after { display:none; }
    .mobile-menu-toggle img { width:100%; height:100%; object-fit:contain; display:block; }
    .mobile-drawer__backdrop { position:absolute; inset:0; background:rgba(7,34,35,.54); opacity:0; transition:opacity .18s ease; }
    .mobile-drawer__panel { position:absolute; top:0; bottom:0; left:0; width:min(64vw,220px); padding:78px 16px 22px; background:linear-gradient(180deg, rgba(13,75,76,.98), rgba(11,63,64,.98)); border-right:1px solid rgba(199,177,102,.22); box-shadow:18px 0 50px rgba(0,0,0,.28); transform:translateX(-104%); transition:transform .22s ease; }
    .mobile-drawer__close { position:absolute; top:18px; right:18px; width:32px; height:32px; border:1px solid rgba(199,177,102,.34); border-radius:999px; background:rgba(246,241,227,.08); color:var(--golden-malt); font-size:20px; line-height:1; cursor:pointer; }
    .mobile-drawer__links { display:grid; gap:8px; }
    .mobile-drawer__links a { display:block; padding:12px 0; border-bottom:1px solid rgba(199,177,102,.14); color:rgba(246,241,227,.88); text-decoration:none; font-weight:800; letter-spacing:.04em; text-transform:uppercase; }
    .mobile-drawer__links a.is-active, .mobile-drawer__links a:hover { color:var(--golden-malt); }
    body.mobile-nav-open { overflow:hidden; }
    body.mobile-nav-open .mobile-drawer { pointer-events:auto; }
    body.mobile-nav-open .mobile-drawer__backdrop { opacity:1; }
    body.mobile-nav-open .mobile-drawer__panel { transform:translateX(0); }
    .top-nav + main { padding-top:var(--menu-offset,176px); }
    body.age-gate-pending { overflow:hidden; }
    .age-gate { position:fixed; inset:0; z-index:1000; display:grid; place-items:center; padding:24px; background:radial-gradient(circle at 50% 25%, rgba(199,177,102,.16), transparent 30%), rgba(11,63,64,.96); backdrop-filter:blur(14px); }
    .age-gate.is-hidden { display:none; }
    .age-gate__card { width:min(520px,100%); border-radius:28px; padding:34px; background:var(--card-hop); box-shadow:0 30px 90px rgba(0,0,0,.32); text-align:center; color:var(--foam); }
    .age-gate__card h2 { margin:0 0 12px; color:var(--golden-malt); font-size:var(--age-gate-title-size, clamp(34px,6vw,56px)); font-weight:var(--age-gate-title-weight,900); line-height:.95; letter-spacing:.06em; text-transform:uppercase; }
    .age-gate__card p { margin:0; color:rgba(246,241,227,.8); font-size:var(--age-gate-text-size, var(--stamm-lead-font-size,18px)); font-weight:var(--age-gate-text-weight,500); line-height:1.45; white-space:pre-line; }
    .age-gate__actions { display:flex; justify-content:center; gap:12px; flex-wrap:wrap; margin-top:24px; }
    .age-gate__card button { border:0; border-radius:999px; padding:14px 22px; background:var(--golden-malt); color:var(--ink); font:inherit; font-weight:900; cursor:pointer; }
    .age-gate__card .age-gate__deny { background:transparent; color:var(--foam); border:1px solid rgba(199,177,102,.42); }
    @media (max-width:920px) {
      :root { --mobile-menu-offset:112px; --stamm-nav-font-size:12px; --stamm-body-font-size:15px; --stamm-lead-font-size:16px; --stamm-page-title-font-size:34px; --stamm-section-title-font-size:24px; }
      .top-nav { position:fixed; align-items:center; flex-direction:row; flex-wrap:wrap; gap:8px 12px; padding:10px 16px; }
      .brand { font-size:12px; letter-spacing:.08em; }
      .nav-links { order:3; width:100%; justify-content:space-between; gap:10px 18px; font-size:var(--stamm-nav-font-size,12px); line-height:1.15; }
      .nav-links a { flex:1 1 max-content; min-width:max-content; text-align:center; }
      .nav-actions { margin-left:auto; gap:6px; }
      .nav-icon { width:28px; height:28px; font-size:9px; }
      .top-nav + main { padding-top:var(--mobile-menu-offset); }
    }
    @media (max-width:560px) {
      :root { --mobile-menu-offset:104px; --stamm-nav-font-size:11px; --stamm-body-font-size:14px; --stamm-lead-font-size:15px; --stamm-page-title-font-size:30px; --stamm-section-title-font-size:22px; }
      .top-nav { display:grid; grid-template-columns:34px minmax(0,1fr) auto; padding:8px 12px; gap:8px; }
      .mobile-menu-toggle { display:grid; }
      .brand { justify-self:center; max-width:142px; overflow:hidden; text-overflow:ellipsis; font-size:11px; letter-spacing:.07em; }
      .nav-links { display:none; }
      .nav-actions { justify-self:end; }
      .nav-icon { width:26px; height:26px; }
      .mobile-drawer { display:block; position:fixed; inset:0; z-index:80; pointer-events:none; }
      .age-gate { padding:16px; }
      .age-gate__card { border-radius:22px; padding:24px 18px; }
      .age-gate__card h2 { font-size:clamp(30px,12vw,42px); }
      .age-gate__card p { font-size:15px; }
      .age-gate__card button { padding:11px 16px; font-size:14px; }
    }
"""


def public_content_or_defaults(content: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "home": {**HOME_DEFAULTS, **((content or {}).get("home") or {})},
        "business": {**BUSINESS_DEFAULTS, **((content or {}).get("business") or {})},
        "contacts": {**CONTACT_DEFAULTS, **((content or {}).get("contacts") or {})},
        "typography": {**TYPOGRAPHY_DEFAULTS, **((content or {}).get("typography") or {})},
        "layout": {**LAYOUT_DEFAULTS, **((content or {}).get("layout") or {})},
        "site": {**SITE_DEFAULTS, **((content or {}).get("site") or {})},
        "gallery": {**GALLERY_DEFAULTS, **((content or {}).get("gallery") or {})},
        "viewer": (content or {}).get("viewer") or {},
        "menu": (content or {}).get("menu") or MENU_DEFAULTS,
        "actions": (content or {}).get("actions") or ACTION_DEFAULTS,
    }


def typography_style(content: dict[str, Any] | None = None) -> str:
    site_content = public_content_or_defaults(content)
    typography = site_content.get("typography") or {}
    css_vars = {
        "--stamm-nav-font-size": typography.get("typography_nav_font_size_px"),
        "--stamm-page-title-font-size": typography.get("typography_page_title_font_size_px"),
        "--stamm-lead-font-size": typography.get("typography_lead_font_size_px"),
        "--stamm-section-title-font-size": typography.get("typography_section_title_font_size_px"),
        "--stamm-body-font-size": typography.get("typography_body_font_size_px"),
        "--stamm-label-font-size": typography.get("typography_label_font_size_px"),
        "--stamm-product-title-font-size": typography.get("typography_product_title_font_size_px"),
        "--stamm-price-font-size": typography.get("typography_price_font_size_px"),
        "--stamm-cart-font-size": typography.get("typography_cart_font_size_px"),
        "--stamm-contact-text-font-size": typography.get("typography_contact_text_font_size_px"),
    }
    declarations = []
    for name, raw_value in css_vars.items():
        try:
            value = max(8, min(96, int(str(raw_value or "").strip())))
        except ValueError:
            continue
        declarations.append(f"{name}:{value}px")
    return f":root{{{';'.join(declarations)}}}" if declarations else ""


def public_nav(active: str, content: dict[str, Any] | None = None) -> str:
    site_content = public_content_or_defaults(content)
    site = site_content.get("site") or {}
    mobile_menu_icon_url = str(site.get("mobile_menu_icon_url") or "").strip()
    mobile_menu_icon = f'<img src="{escape(mobile_menu_icon_url)}" alt="">' if mobile_menu_icon_url else "<span></span>"
    mobile_menu_class = "mobile-menu-toggle mobile-menu-toggle--image" if mobile_menu_icon_url else "mobile-menu-toggle"
    links = "".join(
        f'<a class="{"is-active" if item.get("key") == active else ""}" href="{escape(str(item.get("href") or "#"))}">{escape(str(item.get("label") or ""))}</a>'
        for item in site_content["menu"]
        if item.get("is_visible", True)
    )
    viewer_is_customer = bool((site_content.get("viewer") or {}).get("is_customer"))
    action_links = []
    for item in site_content["actions"]:
        if not item.get("is_visible", True):
            continue
        if item.get("key") == "cart" and not viewer_is_customer:
            continue
        label = escape(str(item.get("label") or ""))
        icon_url = str(item.get("icon_url") or "")
        icon_html = f'<img src="{escape(icon_url)}" alt="">' if icon_url else label
        action_links.append(
            f'<a class="nav-icon" href="{escape(str(item.get("href") or "#"))}" aria-label="{label}">{icon_html}</a>'
        )
    actions = "".join(action_links)
    return f"""
  <nav class="top-nav" aria-label="Главная навигация">
    <button class="{mobile_menu_class}" type="button" aria-label="Открыть меню" aria-controls="mobileNavDrawer" aria-expanded="false">{mobile_menu_icon}</button>
    <a class="brand" href="/">Stamm Brewing</a>
    <div class="nav-links">{links}</div>
    <div class="nav-actions" aria-label="Быстрые ссылки">{actions}</div>
  </nav>
  <div class="mobile-drawer" id="mobileNavDrawer" aria-hidden="true">
    <button class="mobile-drawer__backdrop" type="button" aria-label="Закрыть меню"></button>
    <aside class="mobile-drawer__panel" aria-label="Мобильное меню">
      <button class="mobile-drawer__close" type="button" aria-label="Закрыть меню">×</button>
      <div class="mobile-drawer__links">{links}</div>
    </aside>
  </div>
  <script>
    (function () {{
      const toggle = document.querySelector(".mobile-menu-toggle");
      const drawer = document.getElementById("mobileNavDrawer");
      if (!toggle || !drawer) return;
      const closeButtons = drawer.querySelectorAll(".mobile-drawer__backdrop, .mobile-drawer__close, .mobile-drawer__links a");
      function setOpen(isOpen) {{
        document.body.classList.toggle("mobile-nav-open", isOpen);
        toggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
        drawer.setAttribute("aria-hidden", isOpen ? "false" : "true");
      }}
      toggle.addEventListener("click", function () {{
        setOpen(!document.body.classList.contains("mobile-nav-open"));
      }});
      closeButtons.forEach(function (button) {{
        button.addEventListener("click", function () {{ setOpen(false); }});
      }});
      document.addEventListener("keydown", function (event) {{
        if (event.key === "Escape") setOpen(false);
      }});
    }})();
  </script>"""


def age_gate_markup(content: dict[str, Any] | None = None) -> str:
    site_content = public_content_or_defaults(content)
    if (site_content.get("viewer") or {}).get("is_customer"):
        return ""
    site = site_content.get("site") or {}
    title = escape(str(site.get("age_gate_title") or _site_default("age_gate_title", "Вам есть 18+?")))
    text = cms_text(site.get("age_gate_text") or _site_default("age_gate_text", "Сайт содержит информацию о продукции, предназначенной для лиц старше 18 лет"))
    title_size = css_font_px(site.get("age_gate_title_font_size_px"), _site_default_int("age_gate_title_font_size_px", 48), 18, 96)
    title_weight = css_weight(site.get("age_gate_title_font_weight"), _site_default_int("age_gate_title_font_weight", 900))
    text_size = css_font_px(site.get("age_gate_text_font_size_px"), _site_default_int("age_gate_text_font_size_px", 18), 12, 64)
    text_weight = css_weight(site.get("age_gate_text_font_weight"), _site_default_int("age_gate_text_font_weight", 500))
    confirm_label = escape(str(site.get("age_gate_confirm_label") or _site_default("age_gate_confirm_label", "Да, мне есть 18")))
    deny_label = escape(str(site.get("age_gate_deny_label") or _site_default("age_gate_deny_label", "Нет, мне нет 18")))
    return f"""
  <div class="age-gate" id="ageGate" role="dialog" aria-modal="true" aria-labelledby="ageGateTitle">
    <div class="age-gate__card" style="--age-gate-title-size:{title_size}; --age-gate-title-weight:{title_weight}; --age-gate-text-size:{text_size}; --age-gate-text-weight:{text_weight};">
      <h2 id="ageGateTitle">{title}</h2>
      <p>{text}</p>
      <div class="age-gate__actions">
        <button type="button" id="ageGateConfirm">{confirm_label}</button>
        <button type="button" class="age-gate__deny" id="ageGateReject">{deny_label}</button>
      </div>
    </div>
  </div>
  <script>
    (function () {{
      const storageKey = "stamm_age_confirmed_session";
      const gate = document.getElementById("ageGate");
      const button = document.getElementById("ageGateConfirm");
      const rejectButton = document.getElementById("ageGateReject");
      if (!gate || !button || !rejectButton) return;
      function unlock() {{
        gate.classList.add("is-hidden");
        document.body.classList.remove("age-gate-pending");
      }}
      try {{
        if (window.sessionStorage.getItem(storageKey) === "yes") {{
          unlock();
          return;
        }}
      }} catch (error) {{}}
      document.body.classList.add("age-gate-pending");
      button.addEventListener("click", function () {{
        try {{ window.sessionStorage.setItem(storageKey, "yes"); }} catch (error) {{}}
        unlock();
      }});
      rejectButton.addEventListener("click", function () {{
        if (window.history.length > 1) {{
          window.history.back();
          return;
        }}
        window.location.href = "about:blank";
      }});
    }})();
  </script>"""


def maintenance_page(content: dict[str, Any] | None = None) -> str:
    site_content = public_content_or_defaults(content)
    site = site_content.get("site") or {}
    raw_text = str(site.get("maintenance_text") or _site_default("maintenance_text", "Сайт находится на технических работах, по всем вопросам пишите marketing@stammbeer.ru"))
    text_html = cms_text(raw_text).replace(
        "marketing@stammbeer.ru",
        '<a href="mailto:marketing@stammbeer.ru">marketing@stammbeer.ru</a>',
    )
    message_size = css_font_px(site.get("maintenance_font_size_px"), _site_default_int("maintenance_font_size_px", 24), 12, 80)
    message_weight = css_weight(site.get("maintenance_font_weight"), _site_default_int("maintenance_font_weight", 500))
    image_url = str(site.get("maintenance_image_url") or _site_default("maintenance_image_url", "")).strip()
    image_html = f'<img class="maintenance-image" src="{escape(image_url)}" alt="">' if image_url else ""
    return f"""<!doctype html>
<html lang="ru">
<head>
  {seo_head(site_content, "maintenance", "/", robots="noindex,follow")}
  <style>
{BASE_CSS}
{typography_style(site_content)}
    .maintenance-shell {{ min-height:100vh; display:grid; place-items:start center; padding:clamp(56px,9vh,96px) min(6vw,72px) 72px; text-align:center; background:radial-gradient(circle at 50% 18%, rgba(199,177,102,.16), transparent 30%), linear-gradient(135deg, var(--noble-hop), var(--deep-hop)); }}
    .maintenance-content {{ width:min(800px,100%); display:grid; justify-items:center; gap:28px; }}
    .maintenance-image {{ max-width:min(520px,86vw); max-height:38vh; width:auto; height:auto; object-fit:contain; display:block; background:transparent; border-radius:0; box-shadow:none; }}
    .maintenance-message {{ width:min(760px,100%); margin:0; color:var(--foam); font-size:var(--maintenance-font-size); font-weight:var(--maintenance-font-weight); line-height:1.45; white-space:pre-line; }}
    .maintenance-message a {{ color:var(--golden-malt); text-decoration:none; }}
  </style>
</head>
<body>
  <main class="maintenance-shell" aria-label="Технические работы" style="--maintenance-font-size:{message_size}; --maintenance-font-weight:{message_weight};">
    <div class="maintenance-content">
      {image_html}
      <p class="maintenance-message">{text_html}</p>
    </div>
  </main>
</body>
</html>"""

def css_px(value: object, fallback: int) -> str:
    try:
        number = max(24, min(220, int(str(value))))
    except (TypeError, ValueError):
        number = fallback
    return f"{number}px"


def css_weight(value: object, fallback: int) -> str:
    try:
        number = max(100, min(1000, int(str(value))))
    except (TypeError, ValueError):
        number = fallback
    return str(number)


def css_font_px(value: object, fallback: int, min_value: int = 10, max_value: int = 96) -> str:
    try:
        number = max(min_value, min(max_value, int(str(value or "").strip())))
    except (TypeError, ValueError):
        number = fallback
    return f"{number}px"


def css_gap_px(value: object, fallback: int = 0) -> str:
    try:
        number = max(0, min(140, int(str(value))))
    except (TypeError, ValueError):
        number = fallback
    return f"{number}px"


def css_section_gap_px(value: object, fallback: int = 72) -> str:
    try:
        number = max(0, min(220, int(str(value))))
    except (TypeError, ValueError):
        number = fallback
    return f"{number}px"


def menu_offset_px(content: dict[str, Any] | None, section: str, fallback: int = 176) -> str:
    site_content = public_content_or_defaults(content)
    layout = site_content.get("layout") or {}
    raw_value = layout.get(f"menu_offset_{section}_px")
    try:
        number = max(0, min(420, int(str(raw_value or "").strip())))
    except (TypeError, ValueError):
        number = fallback
    return f"{number}px"


def section_background_style(content: dict[str, Any] | None, section: str, fallback_url: object = "") -> str:
    site_content = public_content_or_defaults(content)
    layout = site_content.get("layout") or {}
    enabled = str(layout.get(f"section_bg_{section}_enabled") or "1").strip().lower() not in {"0", "false", "off", "no"}
    if not enabled:
        return ""
    image_url = str(layout.get(f"section_bg_{section}_url") or fallback_url or "").strip()
    if not image_url:
        return ""
    return f"--section-bg:url('{escape(image_url)}');"


def cms_text(value: object) -> str:
    """Safely render CMS-managed plain text while preserving admin-entered line breaks."""
    return escape(str(value or ""))


def css_map_height(value: object, fallback: int = 240) -> str:
    try:
        number = max(180, min(420, int(str(value or "").strip())))
    except (TypeError, ValueError):
        number = fallback
    return f"{number}px"


def css_map_width(value: object, fallback: int = 420) -> str:
    try:
        number = max(280, min(640, int(str(value or "").strip())))
    except (TypeError, ValueError):
        number = fallback
    return f"{number}px"


def css_text_color(value: object, fallback: str) -> str:
    raw = str(value or "").strip()
    if len(raw) == 7 and raw.startswith("#") and all(char in "0123456789abcdefABCDEF" for char in raw[1:]):
        return raw
    return fallback


def css_hex_to_rgb(value: object, fallback: str = "#0b3f40") -> tuple[int, int, int]:
    color = css_text_color(value, fallback)
    return (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16))


def css_alpha(value: object, fallback_percent: int = 30) -> str:
    try:
        number = float(str(value or "").strip().replace(",", "."))
    except (TypeError, ValueError):
        number = float(fallback_percent)
    if number > 1:
        number = number / 100
    number = max(0, min(1, number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def is_enabled(value: object, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() not in {"0", "false", "off", "no"}

def home_page(content: dict[str, Any] | None = None) -> str:
    site_content = public_content_or_defaults(content)
    home = site_content["home"]
    title_size = css_px(home.get("home_hero_title_size_px"), 152)
    title_weight = css_weight(home.get("home_hero_title_weight"), 950)
    subtitle_size = css_px(home.get("home_hero_subtitle_size_px"), 112)
    subtitle_weight = css_weight(home.get("home_hero_subtitle_weight"), 950)
    line_gap = css_gap_px(home.get("home_hero_line_gap_px"), 0)
    logo_url = str(home.get("home_logo_url") or "")
    content_bg_url = str(home.get("home_content_bg_url") or "")
    content_bg_declarations = section_background_style(site_content, "home", content_bg_url)
    content_bg_style = f' style="{content_bg_declarations}"' if content_bg_declarations else ""
    logo_markup = f'<img class="home-logo" src="{escape(logo_url)}" alt="Stamm Brewing logo">' if logo_url else '<div class="home-logo-mark" aria-hidden="true"></div>'
    news_title = escape(str(home.get("home_news_title") or ""))
    news_text = cms_text(home.get("home_news_text"))
    news_image_url = str(home.get("home_news_image_url") or "")
    news_link_url = str(home.get("home_news_link_url") or "")
    news_link_label = escape(str(home.get("home_news_link_label") or ""))
    news_image_inner = f'<img class="news-card__image" src="{escape(news_image_url)}" alt="{news_title}">' if news_image_url else '<div class="news-card__image news-card__image--fallback" aria-hidden="true"></div>'
    news_image_markup = f'<a class="news-card__image-link" href="{escape(news_link_url)}" aria-label="{news_link_label or news_title}">{news_image_inner}</a>' if news_link_url else news_image_inner
    return f"""<!doctype html>
<html lang="ru">
<head>
  {seo_head(site_content, "home", "/")}
  <style>
{BASE_CSS}
{typography_style(site_content)}
    body.home-body .top-nav + main {{ padding-top:var(--menu-offset,176px); }}
    .home-hero {{ min-height:100vh; display:grid; place-items:center; text-align:center; padding:104px min(6vw,72px) 72px; background:radial-gradient(circle at 50% 16%, rgba(199,177,102,.18), transparent 28%), linear-gradient(135deg, var(--noble-hop), var(--deep-hop)); }}
    .home-hero__inner {{ display:grid; justify-items:center; gap:0; }}
    .home-logo {{ max-width:154px; max-height:154px; object-fit:contain; margin-bottom:28px; }}
    .home-logo-mark {{ width:94px; height:94px; border:2px solid rgba(199,177,102,.5); border-radius:999px; margin-bottom:28px; background:radial-gradient(circle, rgba(199,177,102,.28), transparent 58%); }}
    .home-title {{ margin:0; font-size:clamp(58px,13vw,var(--home-title-size)); line-height:.78; letter-spacing:.08em; color:var(--foam); font-weight:var(--home-title-weight); }}
    .home-subtitle {{ margin:var(--home-line-gap) 0 0; font-size:clamp(42px,10vw,var(--home-subtitle-size)); line-height:.8; letter-spacing:.08em; color:var(--golden-malt); font-weight:var(--home-subtitle-weight); }}
    .home-content {{ position:relative; min-height:100vh; background-image:linear-gradient(180deg, rgba(16,88,89,.84), rgba(11,63,64,.9)), var(--section-bg, linear-gradient(135deg, var(--noble-hop), var(--deep-hop))); background-size:cover; background-position:center; background-repeat:no-repeat; background-attachment:fixed; }}
    .home-content::before {{ content:""; position:absolute; inset:0; background:radial-gradient(circle at 20% 12%, rgba(199,177,102,.18), transparent 32%); pointer-events:none; }}
    .home-content > * {{ position:relative; z-index:1; }}
    .home-news {{ min-height:100vh; display:grid; place-items:center; padding:96px min(6vw,72px); background:transparent; }}
    .news-card {{ width:min(1120px,100%); display:grid; grid-template-columns:minmax(320px,560px) minmax(260px,1fr); gap:34px; align-items:center; background:transparent; border:0; border-radius:0; padding:0; box-shadow:none; }}
    .news-card__image-link {{ display:block; border-radius:24px; text-decoration:none; transition:transform .18s ease; }}
    .news-card__image-link:hover {{ transform:translateY(-2px); }}
    .news-card__image {{ width:100%; aspect-ratio:16/10; max-height:420px; object-fit:cover; border-radius:24px; background:rgba(246,241,227,.08); display:block; }}
    .news-card__image--fallback {{ background:radial-gradient(circle at 50% 40%, rgba(199,177,102,.35), transparent 35%), linear-gradient(135deg, rgba(246,241,227,.08), rgba(16,88,89,.4)); }}
    .news-card h2 {{ margin:0 0 14px; color:var(--white); font-size:var(--stamm-section-title-font-size,26px); line-height:1.08; }}
    .news-card p {{ margin:0; color:rgba(246,241,227,.78); line-height:1.55; font-size:var(--stamm-body-font-size,16px); white-space:pre-line; }}
    @media (max-width:760px) {{ body.home-body .top-nav + main {{ padding-top:0; }} .home-hero {{ min-height:88vh; padding:132px 18px 54px; }} .home-title {{ font-size:clamp(44px,16vw,66px); line-height:.82; }} .home-subtitle {{ font-size:clamp(18px,6vw,26px); letter-spacing:.14em; }} .home-content {{ background-size:cover, cover; background-position:center, center; background-attachment:scroll, fixed; }} .home-news {{ min-height:auto; padding:56px 18px; }} .news-card {{ grid-template-columns:1fr; gap:20px; }} .home-logo {{ max-width:96px; max-height:96px; margin-bottom:18px; }} .news-card__image {{ border-radius:18px; }} }}
  </style>
</head>
<body class="home-body">
{public_nav("home", site_content)}
  <main style="--menu-offset:{menu_offset_px(site_content, 'home')};">
    <section class="home-hero" style="--home-title-size:{title_size}; --home-title-weight:{title_weight}; --home-subtitle-size:{subtitle_size}; --home-subtitle-weight:{subtitle_weight}; --home-line-gap:{line_gap};">
      <div class="home-hero__inner">
        {logo_markup}
        <h1 class="home-title">{escape(str(home.get('home_hero_title') or 'STAMM'))}</h1>
        <p class="home-subtitle">{escape(str(home.get('home_hero_subtitle') or 'BREWING'))}</p>
      </div>
    </section>
    <section class="home-content"{content_bg_style}>
      <section class="home-news" aria-label="Новости">
        <article class="news-card">
          {news_image_markup}
          <div class="news-card__content">
            <h2>{news_title}</h2>
            <p>{news_text}</p>
          </div>
        </article>
      </section>
    </section>
  </main>
{age_gate_markup(site_content)}
</body>
</html>"""

ACCOUNT_CSS = """
    .account-shell { min-height:calc(100vh - 88px); padding:112px min(6vw,72px) 72px; background:radial-gradient(circle at 20% 20%, rgba(199,177,102,.14), transparent 30%), linear-gradient(135deg, var(--noble-hop), var(--deep-hop)); }
    .account-card { width:min(760px,100%); margin:0 auto; padding:34px; border-radius:28px; background:rgba(13,75,76,.94); box-shadow:0 30px 90px rgba(0,0,0,.24); }
    .account-card h1 { margin:0 0 10px; color:var(--golden-malt); font-size:var(--stamm-page-title-font-size,42px); line-height:.95; letter-spacing:.08em; text-transform:uppercase; }
    .account-card p { color:rgba(246,241,227,.78); font-size:var(--stamm-lead-font-size,18px); line-height:1.5; }
    .account-form { display:grid; gap:11px; margin-top:20px; }
    .account-form label { display:grid; gap:5px; color:rgba(246,241,227,.8); font-weight:600; font-size:12px; }
    .account-form input { width:100%; border:1px solid rgba(199,177,102,.32); border-radius:14px; padding:10px 12px; background:rgba(11,63,64,.82); color:var(--foam); font:inherit; font-size:14px; font-weight:400; }
    .account-form input:focus { outline:2px solid rgba(199,177,102,.44); outline-offset:2px; }
    .account-actions { display:flex; gap:9px; align-items:center; flex-wrap:wrap; margin-top:6px; }
    .account-actions--single-row { flex-wrap:nowrap; }
    @media (max-width:620px) { .account-actions--single-row { flex-wrap:wrap; } }
    .account-button { border:0; border-radius:999px; padding:9px 14px; background:var(--golden-malt); color:var(--ink); font:inherit; font-size:14px; line-height:1.15; font-weight:700; cursor:pointer; text-decoration:none; box-shadow:0 2px 7px rgba(199,177,102,.14); }
    .account-button--compact { padding:7px 11px; font-size:12.5px; font-weight:700; box-shadow:0 1px 4px rgba(199,177,102,.1); }
    .account-inline-form { margin:0; }
    .account-link { color:var(--golden-malt); font-weight:800; text-decoration:none; }
    .account-message { margin-top:18px; border-radius:16px; padding:12px 14px; background:rgba(199,177,102,.14); color:var(--foam); }
    .account-message.is-error { background:rgba(115,33,33,.42); color:#ffe6df; }
    .account-section { margin-top:28px; padding-top:22px; border-top:1px solid rgba(199,177,102,.16); }
    .account-section h2 { margin:0 0 14px; color:var(--golden-malt); font-size:24px; line-height:1.05; letter-spacing:.04em; text-transform:uppercase; }
    .account-details { display:grid; gap:12px; margin:26px 0; }
    .account-detail { display:flex; justify-content:space-between; gap:18px; padding:14px 0; border-bottom:1px solid rgba(199,177,102,.16); color:rgba(246,241,227,.82); }
    .account-detail strong { color:var(--foam); text-align:right; }
    .account-orders { display:grid; gap:12px; max-height:420px; overflow-y:auto; padding-right:6px; overscroll-behavior:contain; scrollbar-color:rgba(199,177,102,.62) rgba(11,63,64,.34); }
    .account-order { border:1px solid rgba(199,177,102,.18); border-radius:18px; padding:14px; background:rgba(11,63,64,.35); }
    .account-order__head, .account-order__meta { display:flex; justify-content:space-between; gap:14px; flex-wrap:wrap; }
    .account-order__head strong { color:var(--foam); }
    .account-order__head span, .account-order__meta { color:rgba(246,241,227,.72); font-size:13px; }
    .account-order ul { margin:10px 0 0; padding-left:18px; color:rgba(246,241,227,.78); }
    .account-empty { margin:0; color:rgba(246,241,227,.76); }
    .account-debug { margin:18px 0 24px; border-radius:18px; background:rgba(11,63,64,.42); padding:14px; }
    .account-debug summary { cursor:pointer; color:var(--golden-malt); font-weight:900; }
    .account-debug__rows { display:grid; gap:8px; margin:12px 0; }
    .account-debug__rows div { display:flex; justify-content:space-between; gap:16px; color:rgba(246,241,227,.72); }
    .account-debug pre { overflow:auto; max-height:260px; margin:0; color:rgba(246,241,227,.78); font-size:12px; white-space:pre-wrap; }
    @media (max-width:680px) { .account-shell { padding:124px 14px 42px; } .account-card { padding:20px; border-radius:22px; } .account-card h1 { font-size:30px; } .account-card p { font-size:15px; } .account-section { margin-top:22px; padding-top:18px; } .account-section h2 { font-size:20px; } .account-detail { display:grid; gap:4px; padding:11px 0; } .account-detail strong { text-align:left; } .account-orders { max-height:340px; } }
"""


def account_register_page(content: dict[str, Any] | None = None, error: str | None = None, values: dict[str, str] | None = None) -> str:
    site_content = public_content_or_defaults(content)
    values = values or {}
    message = f'<div class="account-message is-error">{escape(error)}</div>' if error else ""
    return f"""<!doctype html>
<html lang="ru">
<head>
  {PUBLIC_HEAD}
  <title>Регистрация · Stamm Brewing</title>
  <style>
{BASE_CSS}
{typography_style(site_content)}
{ACCOUNT_CSS}
  </style>
</head>
<body>
{public_nav('account', site_content)}
  <main class="account-shell">
    <section class="account-card">
      <h1>Регистрация</h1>
      <p>Создать B2B-аккаунт можно только для организации, которая уже заведена в МойСклад как контрагент Stamm Brewing.</p>
      {message}
      <form class="account-form" method="post" action="/account/register">
        <label>ИНН организации
          <input name="inn" inputmode="numeric" autocomplete="organization" value="{escape(values.get('inn', ''))}" required>
        </label>
        <label>E-mail
          <input name="email" type="email" autocomplete="email" value="{escape(values.get('email', ''))}" required>
        </label>
        <label>Пароль
          <input name="password" type="password" autocomplete="new-password" minlength="8" required>
        </label>
        <label>Подтверждение пароля
          <input name="password_confirm" type="password" autocomplete="new-password" minlength="8" required>
        </label>
        <div class="account-actions">
          <button class="account-button" type="submit">Зарегистрироваться</button>
          <a class="account-link" href="/account/login">Уже есть аккаунт?</a>
        </div>
      </form>
    </section>
  </main>
{age_gate_markup(site_content)}
</body>
</html>"""


def account_login_page(content: dict[str, Any] | None = None, error: str | None = None, values: dict[str, str] | None = None) -> str:
    site_content = public_content_or_defaults(content)
    values = values or {}
    message = f'<div class="account-message is-error">{escape(error)}</div>' if error else ""
    return f"""<!doctype html>
<html lang="ru">
<head>
  {PUBLIC_HEAD}
  <title>Вход · Stamm Brewing</title>
  <style>
{BASE_CSS}
{typography_style(site_content)}
{ACCOUNT_CSS}
  </style>
</head>
<body>
{public_nav('account', site_content)}
  <main class="account-shell">
    <section class="account-card">
      <h1>Вход</h1>
      <p>Войдите в личный кабинет B2B-партнёра Stamm Brewing.</p>
      {message}
      <form class="account-form" method="post" action="/account/login">
        <label>E-mail
          <input name="email" type="email" autocomplete="email" value="{escape(values.get('email', ''))}" required>
        </label>
        <label>Пароль
          <input name="password" type="password" autocomplete="current-password" required>
        </label>
        <div class="account-actions">
          <button class="account-button" type="submit">Войти</button>
          <a class="account-link" href="/account/register">Регистрация по ИНН</a>
          <a class="account-link" href="/account/password-reset">Забыли пароль?</a>
        </div>
      </form>
    </section>
  </main>
{age_gate_markup(site_content)}
</body>
</html>"""


def account_message_page(title: str, message: str, content: dict[str, Any] | None = None, is_error: bool = False) -> str:
    site_content = public_content_or_defaults(content)
    message_class = "account-message is-error" if is_error else "account-message"
    return f"""<!doctype html>
<html lang="ru">
<head>
  {PUBLIC_HEAD}
  <title>{escape(title)} · Stamm Brewing</title>
  <style>
{BASE_CSS}
{typography_style(site_content)}
{ACCOUNT_CSS}
  </style>
</head>
<body>
{public_nav('account', site_content)}
  <main class="account-shell">
    <section class="account-card">
      <h1>{escape(title)}</h1>
      <div class="{message_class}">{escape(message)}</div>
      <div class="account-actions">
        <a class="account-button" href="/account/login">Перейти ко входу</a>
        <a class="account-link" href="/">На главную</a>
      </div>
    </section>
  </main>
{age_gate_markup(site_content)}
</body>
</html>"""


def password_reset_request_page(content: dict[str, Any] | None = None, message: str | None = None, error: str | None = None, values: dict[str, str] | None = None) -> str:
    site_content = public_content_or_defaults(content)
    values = values or {}
    notice = ""
    if error:
        notice = f'<div class="account-message is-error">{escape(error)}</div>'
    elif message:
        notice = f'<div class="account-message">{escape(message)}</div>'
    return f"""<!doctype html>
<html lang="ru">
<head>
  {PUBLIC_HEAD}
  <title>Восстановление пароля · Stamm Brewing</title>
  <style>
{BASE_CSS}
{typography_style(site_content)}
{ACCOUNT_CSS}
  </style>
</head>
<body>
{public_nav('account', site_content)}
  <main class="account-shell">
    <section class="account-card">
      <h1>Восстановление пароля</h1>
      <p>Укажите e-mail B2B-аккаунта. Если аккаунт существует, мы отправим одноразовую ссылку для сброса пароля.</p>
      {notice}
      <form class="account-form" method="post" action="/account/password-reset">
        <label>E-mail
          <input name="email" type="email" autocomplete="email" value="{escape(values.get('email', ''))}" required>
        </label>
        <div class="account-actions">
          <button class="account-button" type="submit">Отправить ссылку</button>
          <a class="account-link" href="/account/login">Вернуться ко входу</a>
        </div>
      </form>
    </section>
  </main>
{age_gate_markup(site_content)}
</body>
</html>"""


def password_reset_confirm_page(token: str, content: dict[str, Any] | None = None, error: str | None = None) -> str:
    site_content = public_content_or_defaults(content)
    notice = f'<div class="account-message is-error">{escape(error)}</div>' if error else ""
    return f"""<!doctype html>
<html lang="ru">
<head>
  {PUBLIC_HEAD}
  <title>Новый пароль · Stamm Brewing</title>
  <style>
{BASE_CSS}
{typography_style(site_content)}
{ACCOUNT_CSS}
  </style>
</head>
<body>
{public_nav('account', site_content)}
  <main class="account-shell">
    <section class="account-card">
      <h1>Новый пароль</h1>
      <p>Введите новый пароль. Ссылка одноразовая и ограничена по времени.</p>
      {notice}
      <form class="account-form" method="post" action="/account/password-reset/confirm">
        <input type="hidden" name="token" value="{escape(token)}">
        <label>Новый пароль
          <input name="password" type="password" autocomplete="new-password" minlength="8" required>
        </label>
        <label>Подтверждение пароля
          <input name="password_confirm" type="password" autocomplete="new-password" minlength="8" required>
        </label>
        <div class="account-actions">
          <button class="account-button" type="submit">Сохранить пароль</button>
          <a class="account-link" href="/account/login">Вернуться ко входу</a>
        </div>
      </form>
    </section>
  </main>
{age_gate_markup(site_content)}
</body>
</html>"""


def _discount_debug_html(customer: Any) -> str:
    try:
        payload = json.loads(customer["discount_source_json"] or "{}")
    except Exception:
        payload = {"raw": customer["discount_source_json"] or ""}
    diagnostics = payload.get("moyskladDiscountDiagnostics") or {}
    local_account = payload.get("localAccount") or {}
    refresh = payload.get("refresh") or {}
    attempts = refresh.get("attempts") or []
    request_targets = ", ".join(
        f"{attempt.get('method')}={attempt.get('requestTarget')}" for attempt in attempts if attempt.get("requestTarget")
    )
    response_summaries = "; ".join(
        f"{attempt.get('method')}: ok={attempt.get('ok')} id={attempt.get('responseCounterpartyId') or '—'} "
        f"selected={attempt.get('selectedValue') if attempt.get('selectedValue') is not None else '—'} "
        f"error={attempt.get('error') or '—'}"
        for attempt in attempts
    )
    lines = [
        ("local user id", local_account.get("localAccountId")),
        ("linked counterparty id", local_account.get("linkedCounterpartyId") or payload.get("counterpartyId") or diagnostics.get("counterpartyId")),
        ("linked counterparty href", local_account.get("linkedCounterpartyHref") or payload.get("counterpartyHref")),
        ("linked counterparty meta", local_account.get("linkedCounterpartyMeta")),
        ("linked organization", local_account.get("linkedCounterpartyName") or payload.get("counterpartyName") or diagnostics.get("counterpartyName")),
        ("linked inn", local_account.get("linkedInn") or payload.get("counterpartyInn") or diagnostics.get("counterpartyInn")),
        ("linked priceType", local_account.get("linkedPriceTypeName") or (payload.get("counterpartyPriceType") or {}).get("priceTypeName")),
        ("linked priceType href", local_account.get("linkedPriceTypeHref") or (payload.get("counterpartyPriceType") or {}).get("priceTypeHref")),
        ("request target", request_targets or "—"),
        ("selected fetch", refresh.get("selectedAttempt")),
        ("response summary", response_summaries or "—"),
        ("local before", payload.get("previousLocalDiscountPercent")),
        ("raw selected path", diagnostics.get("selectedPath")),
        ("raw selected value", diagnostics.get("selectedValue")),
        ("local after", payload.get("resolvedDiscountPercent")),
    ]
    rows = "".join(f"<div><span>{escape(str(label))}</span><strong>{escape(str(value if value is not None else '—'))}</strong></div>" for label, value in lines)
    raw = escape(json.dumps(payload, ensure_ascii=False, indent=2))
    return f'<details class="account-debug"><summary>Диагностика скидки МойСклад</summary><div class="account-debug__rows">{rows}</div><pre>{raw}</pre></details>'


def account_money(value: object, currency: object = "RUB") -> str:
    try:
        amount = int(value or 0) / 100
    except (TypeError, ValueError):
        amount = 0
    suffix = "₽" if str(currency or "RUB").upper() == "RUB" else str(currency or "")
    return f"{amount:,.0f} {suffix}".replace(",", " ")


def account_date(value: object) -> str:
    raw = str(value or "")
    try:
        return raw[:10].split("T", 1)[0]
    except Exception:
        return raw or "—"


def account_dashboard_page(
    customer: Any,
    content: dict[str, Any] | None = None,
    orders: list[dict[str, Any]] | None = None,
    password_result: str | None = None,
    password_error: str | None = None,
) -> str:
    site_content = public_content_or_defaults(content)
    site_content["viewer"] = {"is_customer": True}
    orders = orders or []
    notice = ""
    if password_error:
        notice = f'<div class="account-message is-error">{escape(password_error)}</div>'
    elif password_result:
        notice = f'<div class="account-message">{escape(password_result)}</div>'
    if orders:
        order_cards = "".join(
            f"""
            <article class="account-order">
              <div class="account-order__head">
                <strong>Заказ {index}</strong>
                <span>{escape(account_date(order.get('created_at')))}</span>
              </div>
              <div class="account-order__meta">
                <span>Сумма: {escape(account_money(order.get('total_minor'), order.get('currency')))}</span>
              </div>
              <ul>{''.join(f"<li>{escape(str(item.get('name') or 'Позиция'))} · {escape(str(item.get('quantity') or 0))} шт.</li>" for item in (order.get('items') or [])[:4])}</ul>
            </article>
            """
            for index, order in enumerate(orders, start=1)
        )
    else:
        order_cards = '<p class="account-empty">Заказов пока нет. Оформите первый заказ в разделе «Бизнес».</p>'
    discount = float(customer["discount_percent"] or 0)
    discount_markup = f'<div class="account-detail"><span>Персональная скидка</span><strong>{discount:g}%</strong></div>' if discount > 0 else ""
    return f"""<!doctype html>
<html lang="ru">
<head>
  {PUBLIC_HEAD}
  <title>Личный кабинет · Stamm Brewing</title>
  <style>
{BASE_CSS}
{typography_style(site_content)}
{ACCOUNT_CSS}
  </style>
</head>
<body>
{public_nav('account', site_content)}
  <main class="account-shell">
    <section class="account-card">
      <h1>Кабинет</h1>
      {notice}
      <section class="account-section">
        <h2>Профиль</h2>
      <div class="account-details">
        <div class="account-detail"><span>E-mail</span><strong>{escape(str(customer['email']))}</strong></div>
        <div class="account-detail"><span>ИНН</span><strong>{escape(str(customer['inn']))}</strong></div>
        <div class="account-detail"><span>Организация</span><strong>{escape(str(customer['counterparty_name']))}</strong></div>
        {discount_markup}
      </div>
      </section>
      <section class="account-section">
        <h2>История заказов</h2>
        <div class="account-orders">{order_cards}</div>
      </section>
      <section class="account-section">
        <h2>Смена пароля</h2>
        <form class="account-form" method="post" action="/account/password">
          <label>Текущий пароль
            <input name="current_password" type="password" autocomplete="current-password" required>
          </label>
          <label>Новый пароль
            <input name="new_password" type="password" autocomplete="new-password" minlength="8" required>
          </label>
          <label>Подтверждение нового пароля
            <input name="new_password_confirm" type="password" autocomplete="new-password" minlength="8" required>
          </label>
          <div class="account-actions account-actions--single-row">
            <button class="account-button account-button--compact" type="submit">Сменить пароль</button>
            <button class="account-button account-button--compact" type="submit" form="forgotPasswordForm">Забыл пароль</button>
            <button class="account-button account-button--compact" type="submit" form="logoutForm">Выйти</button>
          </div>
        </form>
        <form id="forgotPasswordForm" class="account-inline-form" method="post" action="/account/password-reset">
          <input type="hidden" name="email" value="{escape(str(customer['email']))}">
        </form>
        <form id="logoutForm" class="account-inline-form" method="post" action="/account/logout"></form>
      </section>
    </section>
  </main>
{age_gate_markup(site_content)}
</body>
</html>"""



def contacts_page(content: dict[str, Any] | None = None) -> str:
    site_content = public_content_or_defaults(content)
    contacts = site_content.get("contacts") or {}
    emails = contacts.get("emails") or []
    phones = contacts.get("phones") or []
    if not emails:
        try:
            emails = json.loads(str(contacts.get("contacts_emails_json") or "[]"))
        except json.JSONDecodeError:
            emails = []
    if not phones:
        try:
            phones = json.loads(str(contacts.get("contacts_phones_json") or "[]"))
        except json.JSONDecodeError:
            phones = []
    address = str(contacts.get("contacts_address") or "")
    address_is_visible = is_enabled(contacts.get("contacts_address_is_visible"), True)
    description = str(contacts.get("contacts_description") or "")
    description_is_visible = is_enabled(contacts.get("contacts_description_is_visible"), True)
    description_color = css_text_color(contacts.get("contacts_description_color"), "rgba(246,241,227,.78)")
    lat = str(contacts.get("contacts_map_lat") or "55.7558")
    lng = str(contacts.get("contacts_map_lng") or "37.6173")
    zoom = str(contacts.get("contacts_map_zoom") or "13")
    title = str(contacts.get("contacts_map_title") or "Stamm Brewing")
    map_height = css_map_height(contacts.get("contacts_map_height_px"), 240)
    map_width = css_map_width(contacts.get("contacts_map_width_px"), 420)
    visible_emails = sorted(
        (item for item in emails if item.get("value") and item.get("is_visible", True)),
        key=lambda item: (int(item.get("sort_order") or 100), str(item.get("label") or "")),
    )
    visible_phones = sorted(
        (item for item in phones if item.get("value") and item.get("is_visible", True)),
        key=lambda item: (int(item.get("sort_order") or 100), str(item.get("label") or "")),
    )
    email_cards = "".join(
        f"<li><span>{escape(str(item.get('label') or 'E-mail'))}</span><a href='mailto:{escape(str(item.get('value') or ''))}'>{escape(str(item.get('value') or ''))}</a></li>"
        for item in visible_emails
    ) or "<li><span>E-mail</span><strong>Скоро появится</strong></li>"
    phone_cards = "".join(
        f"<li><span>{escape(str(item.get('label') or 'Телефон'))}</span><a href='tel:{escape(str(item.get('value') or ''))}'>{escape(str(item.get('value') or ''))}</a></li>"
        for item in visible_phones
    ) or "<li><span>Телефон</span><strong>Скоро появится</strong></li>"
    map_query = quote(title or "Stamm Brewing")
    map_src = f"https://yandex.ru/map-widget/v1/?ll={escape(lng)}%2C{escape(lat)}&z={escape(zoom)}&mode=search&text={map_query}&pt={escape(lng)}%2C{escape(lat)}%2Cpm2goldm"
    description_markup = f'<p style="color:{escape(description_color)}">{cms_text(description)}</p>' if description_is_visible and description else ""
    address_markup = f'<ul class="contact-list"><li><span>Адрес</span><strong>{cms_text(address)}</strong></li></ul>' if address_is_visible and address else ""
    contacts_bg_style = section_background_style(site_content, "contacts")
    return f"""<!doctype html>
<html lang="ru">
<head>
  {seo_head(site_content, "contacts", "/contacts")}
  <style>
{BASE_CSS}
{typography_style(site_content)}
    .contacts-page {{ min-height:calc(100vh - 88px); padding:104px min(6vw,72px) 64px; display:grid; place-items:start center; background-image:linear-gradient(135deg, rgba(16,88,89,.9), rgba(11,63,64,.94)), var(--section-bg, linear-gradient(135deg, var(--noble-hop), var(--deep-hop))); background-size:cover; background-position:center; background-repeat:no-repeat; background-attachment:fixed; }}
    .contacts-hero {{ width:min(100%,1040px); margin:0 auto; display:grid; grid-template-columns:1fr; gap:28px; align-items:start; justify-items:center; text-align:center; }}
    .contacts-card {{ background:var(--card-hop); border:1px solid rgba(199,177,102,.22); border-radius:24px; padding:28px; box-shadow:0 18px 44px rgba(0,0,0,.18); }}
    .contacts-info-card {{ width:min(760px,100%); border:0; background:transparent; box-shadow:none; padding:10px 0; justify-self:center; }}
    .contacts-card p {{ color:rgba(246,241,227,.78); line-height:1.55; font-size:var(--stamm-lead-font-size,18px); white-space:pre-line; }}
    .contact-list {{ list-style:none; margin:22px 0 0; padding:0; display:grid; gap:12px; }}
    .contact-list li {{ padding:12px 0; border-top:1px solid rgba(199,177,102,.16); display:grid; justify-items:center; gap:4px; }}
    .contact-list span {{ color:rgba(246,241,227,.58); font-size:var(--stamm-label-font-size,13px); text-transform:uppercase; letter-spacing:.08em; }}
    .contact-list a, .contact-list strong {{ color:var(--foam); text-decoration:none; font-size:var(--stamm-contact-text-font-size,18px); font-weight:500; white-space:pre-line; }}
    .map-card {{ width:min(100%, var(--contacts-map-width)); overflow:hidden; padding:0; display:block; line-height:0; align-self:start; justify-self:center; }}
    .map-card iframe {{ width:100%; height:var(--contacts-map-height); min-height:180px; max-height:420px; border:0; filter:saturate(.92); display:block; vertical-align:top; }}
    @media (max-width:880px) {{ .contacts-page {{ padding:128px 18px 46px; background-size:cover, cover; background-position:center, center; background-attachment:scroll, fixed; }} .contacts-hero {{ gap:20px; }} .contacts-info-card {{ justify-self:stretch; }} .contacts-card {{ border-radius:20px; padding:20px; }} .contacts-card p {{ font-size:15px; }} .contact-list {{ margin-top:16px; gap:8px; }} .contact-list li {{ padding:10px 0; }} .contact-list a, .contact-list strong {{ font-size:15px; }} .map-card {{ width:100%; justify-self:stretch; padding:0; }} .map-card iframe {{ min-height:220px; max-height:320px; }} }}
  </style>
</head>
<body>
{public_nav("contacts", site_content)}
  <main class="contacts-page" style="--menu-offset:{menu_offset_px(site_content, 'contacts')};{contacts_bg_style}">
    <section class="contacts-hero">
      <div class="contacts-card contacts-info-card">
        {description_markup}
        {address_markup}
        <ul class="contact-list">{email_cards}</ul>
        <ul class="contact-list">{phone_cards}</ul>
      </div>
      <div class="contacts-card map-card" style="--contacts-map-height:{map_height}; --contacts-map-width:{map_width}">
        <iframe title="Яндекс.Карта: {escape(title)}" src="{map_src}" loading="lazy" allowfullscreen></iframe>
      </div>
    </section>
  </main>
{age_gate_markup(site_content)}
</body>
</html>"""

def beer_page(content: dict[str, Any] | None = None) -> str:
    site_content = public_content_or_defaults(content)
    beer = ((content or {}).get("beer") or {})
    untappd_logo_url = str(beer.get("beer_untappd_logo_url") or "")
    backdrop_rgb = css_hex_to_rgb(beer.get("beer_popup_backdrop_color"), "#0b3f40")
    backdrop_alpha = css_alpha(beer.get("beer_popup_backdrop_opacity"), 30)
    backdrop_rgba = f"rgba({backdrop_rgb[0]},{backdrop_rgb[1]},{backdrop_rgb[2]},{backdrop_alpha})"
    card_rgb = css_hex_to_rgb(beer.get("beer_popup_card_color"), "#0d4b4c")
    card_alpha = css_alpha(beer.get("beer_popup_card_opacity"), 100)
    card_rgba = f"rgba({card_rgb[0]},{card_rgb[1]},{card_rgb[2]},{card_alpha})"
    partners = sorted([item for item in (beer.get("partners") or []) if item.get("is_visible", True)], key=lambda item: (int(item.get("sort_order") or 100), str(item.get("name") or "")))
    products = sorted([item for item in (beer.get("products") or []) if item.get("is_visible", True)], key=lambda item: int(item.get("sort_order") or 100))
    size_map = {"small": "86px", "medium": "118px", "large": "154px"}
    partner_cards = []
    for item in partners:
        name = escape(str(item.get("name") or "Партнёр"))
        logo = str(item.get("logo_url") or "")
        logo_html = f'<img src="{escape(logo)}" alt="{name}">' if logo else f'<span class="partner-card__fallback">{name}</span>'
        partner_cards.append(f'<a class="partner-card" href="{escape(str(item.get("url") or "#"))}" target="_blank" rel="noopener" style="--logo-size:{size_map.get(str(item.get("size") or "medium"), "118px")}">{logo_html}</a>')

    def product_card(item: dict[str, Any], featured: bool) -> str:
        payload = escape(json.dumps({"name": str(item.get("name") or ""), "style": str(item.get("style") or ""), "abv": str(item.get("abv") or ""), "imageUrl": str(item.get("image_url") or ""), "untappdUrl": str(item.get("untappd_url") or "")}, ensure_ascii=False))
        name = escape(str(item.get("name") or "Stamm Brewing"))
        image = str(item.get("image_url") or "")
        image_html = f'<img src="{escape(image)}" alt="{name}">' if image else '<div class="beer-can__fallback" aria-hidden="true"></div>'
        return f'<button class="beer-can {"beer-can--featured" if featured else "beer-can--seasonal"}" type="button" data-product="{payload}" aria-label="{name}">{image_html}</button>'

    new_cards = "".join(product_card(item, True) for item in [p for p in products if p.get("category") == "new"][:3])
    core_cards = "".join(product_card(item, False) for item in [p for p in products if p.get("category") == "core"])
    seasonal_cards = "".join(product_card(item, False) for item in [p for p in products if p.get("category") not in {"new", "core"}])
    partners_section = ""
    if is_enabled(beer.get("beer_partners_is_visible"), True):
        partners_section = f'<section class="beer-section" data-beer-block="partners"><h1>{escape(str(beer.get("beer_partners_title") or "Где найти Stamm Brewing"))}</h1><p>{cms_text(beer.get("beer_partners_description") or "")}</p><div class="partners-grid">{"".join(partner_cards)}</div></section>'
    products_inner = ""
    if is_enabled(beer.get("beer_new_is_visible"), True):
        products_inner += f'<div class="product-subsection"><h3>{escape(str(beer.get("beer_new_title") or "Новинки"))}</h3><div class="new-grid">{new_cards}</div></div>'
    if is_enabled(beer.get("beer_core_is_visible"), True):
        products_inner += f'<div class="product-subsection"><h3>{escape(str(beer.get("beer_core_title") or "Постоянная линейка"))}</h3><div class="seasonal-grid">{core_cards}</div></div>'
    if is_enabled(beer.get("beer_seasonal_is_visible"), True):
        products_inner += f'<div class="product-subsection"><h3>{escape(str(beer.get("beer_seasonal_title") or "Сезонные сорта"))}</h3><div class="seasonal-grid">{seasonal_cards}</div></div>'
    products_section = f'<section class="beer-section" data-beer-block="products"><h2>{escape(str(beer.get("beer_products_title") or "Наша продукция"))}</h2>{products_inner}</section>' if is_enabled(beer.get("beer_products_is_visible"), True) else ""

    def beer_block_order(key: str, default: int) -> int:
        try:
            return int(str(beer.get(key) or default))
        except (TypeError, ValueError):
            return default

    beer_sections = sorted(
        [("partners", beer_block_order("beer_partners_sort_order", 10), partners_section), ("products", beer_block_order("beer_products_sort_order", 20), products_section)],
        key=lambda item: (item[1], 0 if item[0] == "partners" else 1),
    )
    beer_sections_html = "".join(section for _, _, section in beer_sections if section)
    beer_bg_url = str(site_content.get("home", {}).get("home_content_bg_url") or "")
    beer_style_values = [f"--menu-offset:{menu_offset_px(site_content, 'beer')}"]
    beer_section_gap = css_section_gap_px(beer.get("beer_section_gap_px"), 72)
    beer_bg_style = section_background_style(site_content, "beer", beer_bg_url)
    if beer_bg_style:
        beer_style_values.append(beer_bg_style)
    beer_page_style = f' style="{";".join(beer_style_values)}"'
    return f"""<!doctype html>
<html lang="ru">
<head>
  {seo_head(site_content, "beer", "/beer")}
  <style>
{BASE_CSS}
{typography_style(site_content)}
    .beer-page {{ min-height:calc(100vh - 88px); padding:120px min(6vw,72px) 72px; background-image:linear-gradient(180deg, rgba(16,88,89,.78), rgba(11,63,64,.86)), var(--section-bg, linear-gradient(135deg, var(--noble-hop), var(--deep-hop))); background-size:cover; background-position:center; background-repeat:no-repeat; background-attachment:fixed; }}
    .beer-shell {{ width:100%; max-width:1440px; margin:0 auto; display:grid; gap:{beer_section_gap}; justify-items:center; text-align:center; }}
    .beer-section {{ width:100%; display:grid; justify-items:center; }}
    .beer-section h1, .beer-section h2 {{ margin:0 0 12px; color:var(--golden-malt); text-transform:uppercase; letter-spacing:.08em; font-size:var(--stamm-page-title-font-size,42px); }}
    .beer-section p {{ margin:0 auto 24px; max-width:720px; color:rgba(246,241,227,.78); font-size:var(--stamm-lead-font-size,18px); line-height:1.55; white-space:pre-line; }}
    .partners-grid {{ width:min(920px,100%); display:flex; flex-wrap:wrap; justify-content:center; align-items:center; gap:18px 28px; margin:0 auto; }}
    .partner-card {{ display:inline-grid; place-items:center; justify-self:center; width:max-content; max-width:100%; text-decoration:none; line-height:0; }}
    .partner-card img {{ max-width:var(--logo-size); max-height:86px; object-fit:contain; display:block; transition:transform .18s ease, filter .18s ease; }}
    .partner-card:hover img {{ transform:scale(1.045); filter:brightness(1.12) drop-shadow(0 8px 18px rgba(199,177,102,.18)); }}
    .partner-card__fallback {{ color:var(--foam); font-weight:800; text-align:center; padding:4px 0; line-height:1.2; transition:transform .18s ease, color .18s ease; }}
    .partner-card:hover .partner-card__fallback {{ transform:scale(1.045); color:var(--golden-malt); }}
    .product-subsection {{ margin-top:28px; }}
    .product-subsection h3 {{ margin:0 0 18px; color:var(--foam); font-size:var(--stamm-section-title-font-size,28px); }}
    .new-grid {{ width:min(860px,100%); display:grid; grid-template-columns:repeat(3,minmax(180px,1fr)); gap:28px; align-items:end; justify-items:center; margin:0 auto; }}
    .seasonal-grid {{ width:min(1320px,100%); display:grid; grid-template-columns:repeat(auto-fit,minmax(72px,132px)); justify-content:center; align-items:end; gap:16px; margin:0 auto; }}
    .beer-can {{ border:0; background:transparent; color:var(--foam); cursor:pointer; display:grid; justify-items:center; gap:10px; font:inherit; font-weight:800; transition:transform .18s ease; }}
    .seasonal-grid .beer-can {{ width:100%; max-width:132px; min-width:0; justify-self:center; }}
    .beer-can:hover {{ transform:scale(1.045); }}
    .beer-can img {{ width:100%; object-fit:contain; filter:drop-shadow(0 22px 28px rgba(0,0,0,.28)); }}
    .beer-can--featured img, .beer-can--featured .beer-can__fallback {{ max-height:360px; }}
    .beer-can--seasonal img, .beer-can--seasonal .beer-can__fallback {{ max-height:138px; }}
    .beer-can__fallback {{ width:82px; aspect-ratio:1/2.2; border-radius:18px; background:linear-gradient(180deg, var(--foam), var(--golden-malt)); }}
    .beer-modal {{ position:fixed; inset:0; z-index:1001; display:none; place-items:center; padding:24px; background:{backdrop_rgba}; backdrop-filter:blur(8px); }}
    .beer-modal.is-open {{ display:grid; }}
    .beer-modal__card {{ position:relative; width:min(520px,100%); border:1px solid rgba(199,177,102,.28); border-radius:26px; padding:30px; background:{card_rgba}; color:var(--foam); box-shadow:0 30px 90px rgba(0,0,0,.34); display:grid; justify-items:center; text-align:center; }}
    .beer-modal__close {{ position:absolute; top:18px; right:18px; border:0; border-radius:999px; width:34px; height:34px; background:var(--golden-malt); color:var(--ink); cursor:pointer; font-weight:900; }}
    .beer-modal h3 {{ margin:0 42px 10px; color:var(--golden-malt); font-size:30px; }}
    .beer-modal p {{ margin:4px 0; }}
    .beer-modal__mockup {{ max-width:min(260px,78vw); max-height:420px; object-fit:contain; margin:18px auto 12px; filter:drop-shadow(0 24px 30px rgba(0,0,0,.32)); }}
    .untappd-link {{ display:inline-grid; place-items:center; margin-top:12px; text-decoration:none; }}
    .untappd-link img {{ width:42px; height:42px; object-fit:contain; transition:transform .18s ease, filter .18s ease; }}
    .untappd-link:hover img {{ transform:scale(1.06); filter:brightness(1.12); }}
    @media (max-width:1100px) {{ .seasonal-grid {{ grid-template-columns:repeat(auto-fit,minmax(64px,104px)); }} }}
    @media (max-width:760px) {{ .beer-page {{ padding:128px 16px 48px; background-size:cover, cover; background-position:center, center; background-attachment:scroll, fixed; }} .beer-shell {{ gap:clamp(34px,9vw,52px); }} .beer-section h1, .beer-section h2 {{ font-size:clamp(26px,8vw,32px); letter-spacing:.06em; }} .beer-section p {{ max-width:100%; margin-bottom:18px; font-size:15px; line-height:1.45; }} .partners-grid {{ width:100%; gap:12px 18px; }} .partner-card img {{ max-width:calc(var(--logo-size) * .72); max-height:58px; }} .partner-card__fallback {{ font-size:13px; }} .product-subsection {{ margin-top:22px; }} .product-subsection h3 {{ font-size:20px; margin-bottom:14px; }} .new-grid {{ grid-template-columns:repeat(3,minmax(72px,1fr)); gap:14px; }} .seasonal-grid {{ width:min(100%,360px); grid-template-columns:repeat(5,minmax(0,1fr)); gap:8px 6px; }} .seasonal-grid .beer-can {{ width:100%; max-width:54px; min-width:0; }} .beer-can--featured img, .beer-can--featured .beer-can__fallback {{ max-height:178px; }} .beer-can--seasonal img, .beer-can--seasonal .beer-can__fallback {{ max-height:74px; }} .beer-modal__card {{ padding:24px 18px; border-radius:22px; }} .beer-modal h3 {{ font-size:24px; }} }}
    @media (max-width:420px) {{ .new-grid {{ gap:10px; }} .seasonal-grid {{ gap:7px 5px; }} .seasonal-grid .beer-can {{ max-width:48px; }} .beer-can--featured img, .beer-can--featured .beer-can__fallback {{ max-height:152px; }} .beer-can--seasonal img, .beer-can--seasonal .beer-can__fallback {{ max-height:68px; }} }}
  </style>
</head>
<body>
{public_nav("beer", site_content)}
  <main class="beer-page"{beer_page_style}><div class="beer-shell">{beer_sections_html}</div></main>
  <div class="beer-modal" id="beerModal"><div class="beer-modal__card"><button class="beer-modal__close" type="button" aria-label="Закрыть">×</button><h3 id="beerModalTitle"></h3><p id="beerModalStyle"></p><p id="beerModalAbv"></p><img class="beer-modal__mockup" id="beerModalImage" src="" alt=""><a class="untappd-link" id="beerModalUntappd" href="#" target="_blank" rel="noopener" aria-label="Untappd"></a></div></div>
  <script>
    (function () {{
      const modal = document.getElementById('beerModal');
      const title = document.getElementById('beerModalTitle');
      const style = document.getElementById('beerModalStyle');
      const abv = document.getElementById('beerModalAbv');
      const link = document.getElementById('beerModalUntappd');
      const image = document.getElementById('beerModalImage');
      const untappdLogoUrl = "{escape(untappd_logo_url)}";
      function close() {{ modal.classList.remove('is-open'); }}
      document.addEventListener('click', function (event) {{
        const button = event.target.closest('[data-product]');
        if (button) {{
          const data = JSON.parse(button.dataset.product || '{{}}');
          title.textContent = data.name || 'Stamm Brewing';
          style.textContent = data.style || '';
          abv.textContent = data.abv ? 'ABV: ' + data.abv : '';
          link.href = data.untappdUrl || '#';
          image.src = data.imageUrl || '';
          image.alt = data.name || '';
          image.hidden = !data.imageUrl;
          link.innerHTML = untappdLogoUrl ? '<img src="' + untappdLogoUrl.replace(/"/g, '&quot;') + '" alt="Untappd">' : '';
          link.hidden = !data.untappdUrl || !untappdLogoUrl;
          modal.classList.add('is-open');
        }}
        if (event.target === modal || event.target.closest('.beer-modal__close')) close();
      }});
      document.addEventListener('keydown', function (event) {{ if (event.key === 'Escape') close(); }});
    }})();
  </script>
{age_gate_markup(site_content)}
</body>
</html>"""

def gallery_page(content: dict[str, Any] | None = None) -> str:
    site_content = public_content_or_defaults(content)
    gallery = site_content.get("gallery") or {}

    def gallery_card(item: dict[str, Any], index: int) -> str:
        image_url = escape(str(item.get("image_url") or ""))
        caption = str(item.get("caption") or "")
        caption_html = f"<span>{escape(caption)}</span>" if caption else ""
        size = str(item.get("size") or "medium")
        if size not in {"small", "medium", "large"}:
            size = "medium"
        return f"""
            <button class="gallery-card gallery-card--{escape(size)}" type="button" data-gallery-open data-gallery-src="{image_url}" data-gallery-caption="{escape(caption)}" aria-label="Открыть фото {index + 1}">
              <img src="{image_url}" alt="{escape(caption or 'Фото Stamm Brewing')}" loading="lazy">
              {caption_html}
            </button>
            """

    source_sections = list(gallery.get("sections") or [])
    if not source_sections and gallery.get("items"):
        source_sections = [{"title": str(gallery.get("gallery_title") or GALLERY_DEFAULTS["gallery_title"]), "is_visible": True, "items": gallery.get("items")}]
    visible_sections = []
    global_index = 0
    for section in source_sections:
        if not is_enabled(section.get("is_visible"), True):
            continue
        visible_items = [
            item for item in section.get("items", [])
            if item.get("image_url") and is_enabled(item.get("is_visible"), True)
        ]
        if not visible_items:
            continue
        cards = []
        for item in visible_items:
            cards.append(gallery_card(item, global_index))
            global_index += 1
        visible_sections.append(
            f"""
            <section class="gallery-section">
              <h2>{escape(str(section.get('title') or 'Раздел галереи'))}</h2>
              <div class="gallery-grid">{''.join(cards)}</div>
            </section>
            """
        )
    sections_html = "".join(visible_sections) or "<p class='gallery-empty'>Галерея скоро пополнится новыми фотографиями Stamm Brewing.</p>"
    title = str(gallery.get("gallery_title") or GALLERY_DEFAULTS["gallery_title"])
    description = str(gallery.get("gallery_description") or "")
    description_html = f"<p>{cms_text(description)}</p>" if description else ""
    gallery_bg_style = section_background_style(site_content, "history")
    return f"""<!doctype html>
<html lang="ru">
<head>
  {seo_head(site_content, "gallery", "/gallery")}
  <style>
{BASE_CSS}
{typography_style(site_content)}
    .gallery-page {{ min-height:100vh; padding:calc(var(--menu-offset,176px) + 22px) min(5vw,64px) 84px; background-image:radial-gradient(circle at 18% 12%, rgba(199,177,102,.16), transparent 30%), linear-gradient(180deg, rgba(16,88,89,.9), rgba(11,63,64,.96)), var(--section-bg, linear-gradient(180deg, rgba(16,88,89,.96), rgba(11,63,64,.98))); background-size:auto, cover, cover; background-position:center; background-repeat:no-repeat; background-attachment:scroll, fixed, fixed; }}
    .gallery-shell {{ width:min(1440px,100%); margin:0 auto; }}
    .gallery-hero {{ max-width:820px; margin:0 auto 42px; text-align:center; }}
    .gallery-hero h1 {{ margin:0; color:var(--golden-malt); font-size:var(--stamm-page-title-font-size,42px); line-height:.95; text-transform:uppercase; letter-spacing:.08em; }}
    .gallery-hero p {{ margin:16px auto 0; color:rgba(246,241,227,.78); font-size:var(--stamm-lead-font-size,18px); line-height:1.55; white-space:pre-line; }}
    .gallery-sections {{ display:grid; gap:54px; }}
    .gallery-section h2 {{ margin:0 0 18px; color:var(--foam); font-size:clamp(24px,3vw,36px); line-height:1; text-transform:uppercase; letter-spacing:.07em; }}
    .gallery-grid {{ display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); grid-auto-flow:dense; gap:14px; }}
    .gallery-card {{ position:relative; min-height:230px; grid-column:span 2; border:0; padding:0; overflow:hidden; border-radius:28px; background:rgba(246,241,227,.08); cursor:pointer; box-shadow:0 22px 60px rgba(0,0,0,.2); }}
    .gallery-card--small {{ grid-column:span 2; min-height:220px; }}
    .gallery-card--medium {{ grid-column:span 3; min-height:300px; }}
    .gallery-card--large {{ grid-column:span 4; grid-row:span 2; min-height:430px; }}
    .gallery-card img {{ width:100%; height:100%; position:absolute; inset:0; object-fit:cover; display:block; transform:scale(1.01); transition:transform .45s ease, filter .45s ease; }}
    .gallery-card::after {{ content:""; position:absolute; inset:0; background:linear-gradient(180deg, transparent 58%, rgba(0,0,0,.42)); opacity:.58; transition:opacity .35s ease; }}
    .gallery-card span {{ position:absolute; left:18px; right:18px; bottom:16px; z-index:1; color:var(--foam); font-weight:700; font-size:15px; line-height:1.25; text-align:left; }}
    .gallery-card:hover img {{ transform:scale(1.07); filter:brightness(1.08) saturate(1.02); }}
    .gallery-card:hover::after {{ opacity:.48; }}
    .gallery-empty {{ margin:0 auto; max-width:620px; color:rgba(246,241,227,.72); text-align:center; }}
    .gallery-lightbox {{ position:fixed; inset:0; z-index:900; display:none; place-items:center; padding:28px; background:rgba(7,32,33,.88); backdrop-filter:blur(12px); }}
    .gallery-lightbox.is-open {{ display:grid; }}
    .gallery-lightbox__inner {{ width:min(1120px,100%); display:grid; gap:14px; justify-items:center; }}
    .gallery-lightbox img {{ max-width:100%; max-height:78vh; object-fit:contain; border-radius:22px; box-shadow:0 30px 90px rgba(0,0,0,.42); }}
    .gallery-lightbox p {{ margin:0; color:var(--foam); font-weight:600; text-align:center; }}
    .gallery-lightbox button {{ border:0; border-radius:999px; padding:10px 16px; background:var(--golden-malt); color:var(--ink); font-weight:900; cursor:pointer; }}
    @media (max-width:980px) {{ .gallery-page {{ background-attachment:scroll, scroll, scroll; }} .gallery-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .gallery-card, .gallery-card--small, .gallery-card--medium, .gallery-card--large {{ grid-column:span 1; grid-row:span 1; min-height:240px; }} }}
    @media (max-width:620px) {{ .gallery-page {{ padding:128px 16px 48px; background-size:auto, cover, cover; background-position:center, center, center; background-attachment:scroll, scroll, fixed; }} .gallery-hero {{ margin-bottom:28px; }} .gallery-hero h1 {{ font-size:30px; }} .gallery-hero p {{ font-size:15px; }} .gallery-sections {{ gap:36px; }} .gallery-section h2 {{ font-size:22px; }} .gallery-grid {{ grid-template-columns:1fr; gap:12px; }} .gallery-card {{ min-height:220px; border-radius:20px; }} .gallery-card span {{ font-size:13px; }} }}
  </style>
</head>
<body>
{public_nav("history", site_content)}
  <main class="gallery-page" style="--menu-offset:{menu_offset_px(site_content, 'history')};{gallery_bg_style}">
    <section class="gallery-shell">
      <div class="gallery-hero"><h1>{escape(title)}</h1>{description_html}</div>
      <div class="gallery-sections">{sections_html}</div>
    </section>
  </main>
  <div class="gallery-lightbox" id="galleryLightbox" aria-hidden="true">
    <div class="gallery-lightbox__inner">
      <img src="" alt="">
      <p></p>
      <button type="button" data-gallery-close>Закрыть</button>
    </div>
  </div>
  <script>
    (function () {{
      const lightbox = document.getElementById('galleryLightbox');
      if (!lightbox) return;
      const image = lightbox.querySelector('img');
      const caption = lightbox.querySelector('p');
      function close() {{
        lightbox.classList.remove('is-open');
        lightbox.setAttribute('aria-hidden', 'true');
        if (image) image.src = '';
      }}
      document.querySelectorAll('[data-gallery-open]').forEach((button) => {{
        button.addEventListener('click', () => {{
          if (!image || !caption) return;
          image.src = button.dataset.gallerySrc || '';
          image.alt = button.dataset.galleryCaption || 'Фото Stamm Brewing';
          caption.textContent = button.dataset.galleryCaption || '';
          lightbox.classList.add('is-open');
          lightbox.setAttribute('aria-hidden', 'false');
        }});
      }});
      lightbox.addEventListener('click', (event) => {{ if (event.target === lightbox) close(); }});
      lightbox.querySelector('[data-gallery-close]')?.addEventListener('click', close);
      document.addEventListener('keydown', (event) => {{ if (event.key === 'Escape') close(); }});
    }})();
  </script>
{age_gate_markup(site_content)}
</body>
</html>"""

def public_placeholder_page(title: str, active: str, content: dict[str, Any] | None = None) -> str:
    site_content = public_content_or_defaults(content)
    placeholder_bg_style = section_background_style(site_content, active)
    return f"""<!doctype html>
<html lang="ru">
<head>
  {seo_head(site_content, active, "/" + active)}
  <style>
{BASE_CSS}
{typography_style(site_content)}
    .placeholder {{ min-height:54vh; display:grid; place-items:center; padding:96px min(6vw,72px) 72px; background-image:linear-gradient(135deg, rgba(16,88,89,.9), rgba(11,63,64,.94)), var(--section-bg, linear-gradient(135deg, var(--noble-hop), var(--deep-hop))); background-size:cover; background-position:center; background-repeat:no-repeat; background-attachment:fixed; }}
    .placeholder__card {{ max-width:760px; background:var(--card-hop); border:1px solid rgba(199,177,102,.2); border-radius:24px; padding:30px; }}
    .placeholder__card h1 {{ margin:0 0 10px; color:var(--golden-malt); text-transform:uppercase; letter-spacing:.08em; font-size:var(--stamm-page-title-font-size,42px); }}
    .placeholder__card p {{ margin:0; color:rgba(246,241,227,.76); }}
    @media (max-width:620px) {{ .placeholder {{ padding:128px 16px 48px; background-size:cover, cover; background-position:center, center; background-attachment:scroll, fixed; }} .placeholder__card {{ padding:22px; border-radius:20px; }} .placeholder__card h1 {{ font-size:30px; }} }}
  </style>
</head>
<body>
{public_nav(active, site_content)}
  <main class="placeholder" style="--menu-offset:{menu_offset_px(site_content, active)};{placeholder_bg_style}"><section class="placeholder__card"><h1>{title}</h1><p>Раздел будет собираться после ядра B2B-магазина и админки.</p></section></main>
{age_gate_markup(site_content)}
</body>
</html>"""


def business_guest_page(content: dict[str, Any] | None = None) -> str:
    site_content = public_content_or_defaults(content)
    site_content = {**site_content, "actions": [{**item, "is_visible": False} if item.get("key") == "cart" else item for item in site_content.get("actions", [])]}
    business = site_content.get("business") or {}
    message = str(business.get("business_guest_text") or BUSINESS_DEFAULTS["business_guest_text"])
    message_size = css_font_px(business.get("business_guest_font_size_px"), int(BUSINESS_DEFAULTS["business_guest_font_size_px"]), 12, 72)
    message_weight = css_weight(business.get("business_guest_font_weight"), int(BUSINESS_DEFAULTS["business_guest_font_weight"]))
    business_bg_style = section_background_style(site_content, "business")
    return f"""<!doctype html>
<html lang="ru">
<head>
  {seo_head(site_content, "business", "/business")}
  <style>
{BASE_CSS}
{typography_style(site_content)}
    html, body {{ min-height:100%; background:var(--deep-hop); }}
    .business-guest {{ min-height:100vh; padding:var(--menu-offset,176px) min(6vw,72px) 72px; display:grid; place-items:center; background-image:radial-gradient(circle at 24% 18%, rgba(199,177,102,.16), transparent 32%), linear-gradient(135deg, rgba(16,88,89,.9), rgba(11,63,64,.94)), var(--section-bg, linear-gradient(135deg, var(--noble-hop), var(--deep-hop))); background-size:auto, cover, cover; background-position:center; background-repeat:no-repeat; background-attachment:scroll, fixed, fixed; }}
    .business-guest__message {{ max-width:620px; margin:0 auto; text-align:center; color:var(--foam); font-size:var(--business-guest-font-size); line-height:1.38; font-weight:var(--business-guest-font-weight); letter-spacing:.01em; white-space:pre-line; }}
    @media (max-width:720px) {{ .business-guest {{ padding:128px 18px 46px; background-size:auto, cover, cover; background-position:center, center, center; background-attachment:scroll, scroll, fixed; }} .business-guest__message {{ max-width:28rem; font-size:min(var(--business-guest-font-size), 22px); line-height:1.34; }} }}
    @media (max-width:420px) {{ .business-guest {{ padding-left:14px; padding-right:14px; }} .business-guest__message {{ font-size:min(var(--business-guest-font-size), 20px); }} }}
  </style>
</head>
<body>
{public_nav("business", site_content)}
  <main class="business-guest" style="--menu-offset:{menu_offset_px(site_content, 'business')}; --business-guest-font-size:{message_size}; --business-guest-font-weight:{message_weight};{business_bg_style}">
    <p class="business-guest__message">{cms_text(message)}</p>
  </main>
{age_gate_markup(site_content)}
</body>
</html>"""


def business_storefront_page(content: dict[str, Any] | None = None) -> str:
    site_content = public_content_or_defaults(content)
    business_bg_style = section_background_style(site_content, "business")
    return f"""<!doctype html>
<html lang="ru">
<head>
  {seo_head(site_content, "business", "/business")}
  <style>
{BASE_CSS}
{typography_style(site_content)}
    .wrap {{ min-height:100vh; padding:58px min(6vw,72px) 56px; background-image:linear-gradient(135deg, rgba(16,88,89,.9), rgba(11,63,64,.94)), var(--section-bg, linear-gradient(135deg, var(--noble-hop), var(--deep-hop))); background-size:cover; background-position:center; background-repeat:no-repeat; background-attachment:fixed; }}
    .toolbar {{ display:flex; flex-wrap:wrap; justify-content:space-between; gap:16px; align-items:center; margin-bottom:18px; }}
    .filters {{ display:flex; gap:10px; flex-wrap:wrap; }}
    .filter {{ border:1px solid rgba(199,177,102,.34); background:rgba(11,63,64,.55); color:var(--foam); padding:9px 15px; border-radius:999px; font-weight:600; cursor:pointer; }}
    .filter.is-active {{ background:var(--golden-malt); color:var(--ink); border-color:var(--golden-malt); }}
    .shop-layout {{ display:grid; grid-template-columns:minmax(0,1fr) 360px; gap:18px; align-items:start; }}
    .grid {{ display:grid; grid-template-columns:1fr; gap:10px; }}
    .product {{ overflow:hidden; background:var(--card-hop); border:1px solid rgba(199,177,102,.18); border-radius:18px; box-shadow:0 14px 30px rgba(0,0,0,.14); display:grid; grid-template-columns:82px minmax(0,1fr) auto; align-items:center; gap:12px; min-height:98px; padding:9px 12px; }}
    .product__image {{ width:70px; height:70px; border-radius:14px; background:radial-gradient(circle at 34% 28%, rgba(199,177,102,.74), transparent 34%), linear-gradient(135deg, rgba(246,241,227,.92), rgba(199,177,102,.28)); display:block; overflow:hidden; flex-shrink:0; }}
    .product__image img {{ width:100%; height:100%; object-fit:cover; display:block; }}
    .product__image-fallback {{ width:100%; height:100%; background:radial-gradient(circle at 50% 36%, rgba(199,177,102,.78), transparent 32%), linear-gradient(135deg, rgba(246,241,227,.18), rgba(199,177,102,.22)); }}
    .product__body {{ min-width:0; display:flex; flex-direction:column; gap:7px; justify-content:center; }}
    .badges {{ display:flex; gap:6px; flex-wrap:wrap; }}
    .badge {{ font-size:11px; padding:4px 8px; border-radius:999px; background:rgba(246,241,227,.1); color:var(--foam); font-weight:600; line-height:1; }}
    h2 {{ margin:0; font-size:var(--stamm-product-title-font-size,16px); line-height:1.15; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; color:var(--white); font-weight:600; }}
    .meta {{ display:flex; align-items:center; justify-content:flex-start; gap:14px; font-weight:600; font-size:13px; }}
    .price {{ font-size:var(--stamm-price-font-size,17px); color:var(--golden-malt); }}
    .price-base {{ color:rgba(246,241,227,.48); text-decoration:line-through; white-space:nowrap; }}
    .product__order {{ display:grid; place-items:center; min-width:116px; }}
    .quantity {{ display:grid; grid-template-columns:30px 38px 30px; align-items:center; border:1px solid rgba(199,177,102,.28); border-radius:999px; overflow:hidden; background:rgba(11,63,64,.42); }}
    .quantity__button {{ border:0; width:30px; height:30px; background:var(--golden-malt); color:var(--ink); font-weight:700; cursor:pointer; }}
    .quantity__button:hover {{ filter:brightness(1.06); }}
    .quantity__value {{ width:38px; min-width:0; border:0; background:transparent; text-align:center; font-weight:700; color:var(--foam); font:inherit; font-size:13px; appearance:textfield; }}
    .quantity__value::-webkit-outer-spin-button, .quantity__value::-webkit-inner-spin-button {{ -webkit-appearance:none; margin:0; }}
    .cart {{ font-size:var(--stamm-cart-font-size,14px); position:sticky; top:86px; background:var(--card-hop); border:1px solid rgba(199,177,102,.22); border-radius:20px; box-shadow:0 14px 34px rgba(0,0,0,.16); overflow:hidden; }}
    .cart__header {{ display:flex; align-items:center; justify-content:space-between; gap:12px; padding:16px 18px; border-bottom:1px solid rgba(199,177,102,.14); }}
    .cart__title {{ margin:0; color:var(--golden-malt); font-size:var(--stamm-section-title-font-size,18px); text-transform:uppercase; letter-spacing:.08em; }}
    .cart__counter {{ min-width:30px; height:30px; border-radius:999px; display:grid; place-items:center; background:var(--golden-malt); color:var(--ink); font-weight:700; }}
    .cart__comment {{ padding:14px 18px 0; }}
    .cart__comment label {{ display:grid; gap:6px; color:rgba(246,241,227,.72); font-size:var(--stamm-label-font-size,12px); font-weight:600; }}
    .cart__comment textarea {{ width:100%; min-height:76px; resize:vertical; border:1px solid rgba(199,177,102,.28); border-radius:14px; padding:10px 12px; background:rgba(11,63,64,.42); color:var(--foam); font:inherit; }}
    .cart__comment textarea:focus {{ outline:2px solid rgba(199,177,102,.38); outline-offset:2px; }}
    .cart__body {{ padding:14px 18px 18px; }}
    .cart__empty {{ min-height:12px; }}
    .cart__items {{ display:grid; gap:10px; margin-bottom:14px; }}
    .cart-item {{ display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px 10px; padding:10px 0; border-bottom:1px solid rgba(246,241,227,.1); }}
    .cart-item__name {{ font-weight:600; color:var(--white); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
    .cart-item__meta {{ color:rgba(246,241,227,.68); font-size:12px; margin-top:3px; }}
    .cart-item__sum {{ color:var(--golden-malt); font-weight:700; white-space:nowrap; }}
    .cart-item__controls {{ grid-column:1 / -1; display:flex; align-items:center; justify-content:space-between; gap:8px; }}
    .cart-remove {{ border:0; background:transparent; color:rgba(246,241,227,.72); cursor:pointer; text-decoration:underline; padding:0; }}
    .cart__total {{ display:flex; justify-content:space-between; align-items:center; padding-top:12px; border-top:1px solid rgba(199,177,102,.18); font-weight:700; }}
    .cart__total strong {{ color:var(--golden-malt); font-size:var(--stamm-price-font-size,20px); }}
    .cart__minimum {{ margin-top:10px; color:rgba(246,241,227,.72); font-size:var(--stamm-cart-font-size,12px); line-height:1.35; }}
    .cart__minimum.is-below {{ color:#ffaaa0; }}
    .cart__message {{ margin-top:10px; border-radius:12px; padding:9px 10px; background:rgba(199,177,102,.12); color:rgba(246,241,227,.84); font-size:12px; }}
    .cart__message.is-error {{ background:rgba(115,33,33,.42); color:#ffe6df; }}
    .cart__submit {{ width:100%; margin-top:14px; border:0; border-radius:14px; padding:12px 14px; background:var(--golden-malt); color:var(--ink); font-weight:700; cursor:pointer; }}
    .cart__submit:disabled {{ opacity:.48; cursor:not-allowed; }}
    .state {{ background:var(--card-hop); border:1px solid rgba(199,177,102,.18); border-radius:20px; padding:34px; text-align:center; color:rgba(246,241,227,.76); }}
    .state strong {{ display:block; color:var(--golden-malt); font-size:22px; margin-bottom:8px; }}
    @media (max-width:920px) {{ .shop-layout {{ grid-template-columns:1fr; }} .cart {{ position:static; }} }}
    @media (max-width:720px) {{ .wrap {{ padding:128px 14px 38px; background-size:cover, cover; background-position:center, center; background-attachment:scroll, fixed; }} .toolbar {{ gap:12px; margin-bottom:14px; }} .filters {{ gap:8px; }} .filter {{ padding:8px 12px; font-size:13px; }} .product {{ grid-template-columns:54px minmax(0,1fr); gap:9px; min-height:80px; padding:9px; border-radius:16px; }} .product__image {{ width:50px; height:50px; border-radius:12px; }} .product__order {{ grid-column:2; justify-self:start; min-width:0; margin-top:2px; }} .badge {{ font-size:10px; padding:3px 7px; }} h2 {{ font-size:14px; }} .price {{ font-size:15px; }} .quantity {{ grid-template-columns:28px 36px 28px; }} .quantity__button {{ width:28px; height:28px; }} .cart {{ border-radius:18px; }} .cart__header {{ padding:14px 15px; }} .cart__body, .cart__comment {{ padding-left:15px; padding-right:15px; }} }}
  </style>
</head>
<body>
{public_nav("business", content)}
  <main class="wrap" style="--menu-offset:{menu_offset_px(site_content, 'business')};{business_bg_style}">
    <div class="toolbar">
      <div class="filters" aria-label="Фильтры каталога">
        <button class="filter is-active" data-filter="all">Все</button>
        <button class="filter" data-filter="keg">Кеги</button>
        <button class="filter" data-filter="can">Банки</button>
      </div>
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
        <div class="cart__comment">
          <label>Комментарий к заказу
            <textarea id="orderComment" maxlength="1000"></textarea>
          </label>
        </div>
        <div class="cart__body" id="cartBody"><div class="cart__empty" aria-label="Корзина пуста"></div></div>
      </aside>
    </div>
  </main>
  <script>
    const stateEl = document.getElementById('state');
    const gridEl = document.getElementById('grid');
    const cartCounterEl = document.getElementById('cartCounter');
    const cartBodyEl = document.getElementById('cartBody');
    const orderCommentEl = document.getElementById('orderComment');
    const filterButtons = [...document.querySelectorAll('.filter')];
    let activeFilter = 'all';
    let currentItems = [];
    let minimumOrderAmountMinor = 1500000;
    let minimumOrderLabel = '15 000 ₽';
    const cart = new Map();

    function setState(title, text, branch = 'loading') {{
      stateEl.hidden = false;
      gridEl.hidden = true;
      stateEl.dataset.branch = branch;
      stateEl.innerHTML = `<strong>${{title}}</strong>${{text}}`;
    }}

    function escapeHtml(value) {{
      return String(value === null || value === undefined ? '' : value).replace(/[&<>"']/g, (char) => ({{ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }}[char]));
    }}

    function formatMoney(amountMinor, currency = 'RUB') {{
      if (amountMinor === null || amountMinor === undefined) return 'Цена по запросу';
      return `${{Number(amountMinor / 100).toLocaleString('ru-RU')}} ₽`;
    }}

    function numberOrDefault(value, fallback = 0) {{
      const number = Number(value);
      return Number.isFinite(number) ? number : fallback;
    }}

    function normalizeCatalogItem(raw) {{
      const item = raw && typeof raw === 'object' ? raw : {{}};
      const price = item.price && typeof item.price === 'object' ? item.price : {{}};
      const availability = item.availability && typeof item.availability === 'object' ? item.availability : {{}};
      const rules = item.orderRules && typeof item.orderRules === 'object' ? item.orderRules : {{}};
      const fallbackId = item.slug || item.externalId || item.sku || item.name || '';
      const productId = item.productId !== undefined && item.productId !== null ? item.productId : fallbackId;
      const containerType = item.containerType || 'keg';
      const maxQuantity = rules.maxQuantity !== undefined && rules.maxQuantity !== null ? rules.maxQuantity : availability.quantity;
      return {{
        productId,
        variantId: item.variantId || null,
        slug: item.slug || String(productId || ''),
        name: item.name || item.publicName || item.accountingName || 'Позиция каталога',
        subtitle: item.subtitle || '',
        sku: item.sku || '',
        externalId: item.externalId || null,
        externalHref: item.externalHref || null,
        containerType,
        containerLabel: item.containerLabel || (containerType === 'can' ? 'Банки' : 'Кеги'),
        volumeLiters: item.volumeLiters || null,
        alcoholPercent: item.alcoholPercent || null,
        alcoholLabel: item.alcoholLabel || '',
        price: {{
          visibility: price.visibility || 'hidden',
          amountMinor: numberOrDefault(price.amountMinor, 0),
          baseAmountMinor: numberOrDefault(price.baseAmountMinor, price.amountMinor || 0),
          currency: price.currency || 'RUB',
          label: price.label || 'Цена по запросу',
          baseLabel: price.baseLabel || '',
          showBasePrice: Boolean(price.showBasePrice),
          pricingSource: price.pricingSource || 'base',
          priceTypeName: price.priceTypeName || null,
        }},
        availability: {{
          status: availability.status || 'unavailable',
          label: availability.label || '',
          quantity: numberOrDefault(availability.quantity, 0),
        }},
        imageUrl: item.imageUrl || '',
        ctaLabel: item.ctaLabel || 'В заявку',
        orderRules: {{
          allowPreorder: Boolean(rules.allowPreorder),
          minQuantity: numberOrDefault(rules.minQuantity, containerType === 'can' ? 12 : 1),
          step: numberOrDefault(rules.step, containerType === 'can' ? 12 : 1),
          maxQuantity: numberOrDefault(maxQuantity, 0),
        }},
      }};
    }}

    function cartQuantity(productId) {{
      const entry = cart.get(String(productId));
      return entry ? entry.quantity : 0;
    }}

    function itemStep(item) {{
      const rules = item && item.orderRules ? item.orderRules : {{}};
      return Number(rules.step || (item && item.containerType === 'can' ? 12 : 1));
    }}

    function availableQuantity(item) {{
      const rules = item && item.orderRules ? item.orderRules : {{}};
      const availability = item && item.availability ? item.availability : {{}};
      const rawMax = rules.maxQuantity !== undefined && rules.maxQuantity !== null ? rules.maxQuantity : availability.quantity;
      const max = Number(rawMax || 0);
      return Number.isFinite(max) ? Math.max(0, max) : 0;
    }}

    function maxOrderQuantity(item) {{
      const step = itemStep(item);
      const max = availableQuantity(item);
      if (step <= 1) return max;
      return Math.floor(max / step) * step;
    }}

    function normalizeQuantity(item, quantity) {{
      const step = itemStep(item);
      const max = maxOrderQuantity(item);
      const raw = Math.max(0, Number(quantity) || 0);
      if (raw === 0 || max <= 0) return 0;
      const stepped = Math.ceil(raw / step) * step;
      return Math.min(stepped, max);
    }}

    function renderCards(items) {{
      currentItems = items;
      const cards = items.map((item, index) => {{
        try {{
          const price = item && item.price ? item.price : {{}};
          const safeName = escapeHtml(item && item.name ? item.name : 'Позиция каталога');
          const safeContainer = escapeHtml(item && item.containerLabel ? item.containerLabel : 'Кеги');
          const safePrice = escapeHtml(price.label || 'Цена по запросу');
          const basePrice = price.showBasePrice ? `<span class="price-base">${{escapeHtml(price.baseLabel || '')}}</span>` : '';
          const abvBadge = item && item.alcoholLabel ? `<span class="badge">${{escapeHtml(item.alcoholLabel)}}</span>` : '';
          const fallback = `<div class="product__image-fallback" aria-label="Фото скоро появится"></div>`;
          const imageUrl = item && item.imageUrl ? item.imageUrl : '';
          const productId = item && item.productId !== undefined && item.productId !== null ? item.productId : `invalid-${{index}}`;
          const imageMarkup = imageUrl
            ? `<img src="${{escapeHtml(imageUrl)}}" alt="${{safeName}}" loading="lazy" onerror="this.hidden=true; this.nextElementSibling.hidden=false"><div class="product__image-fallback" aria-label="Фото скоро появится" hidden></div>`
            : fallback;
          const quantity = cartQuantity(productId);
          const step = itemStep(item);
          const maxQuantity = maxOrderQuantity(item);
          const stepHint = item && item.containerType === 'can' ? '<span class="badge">ящик ×12</span>' : '';
          return `
          <article class="product">
            <div class="product__image">${{imageMarkup}}</div>
            <div class="product__body">
              <div class="badges"><span class="badge">${{safeContainer}}</span>${{stepHint}}${{abvBadge}}</div>
              <h2>${{safeName}}</h2>
              <div class="meta"><span class="price">${{safePrice}}</span>${{basePrice}}</div>
            </div>
            <div class="product__order" aria-label="Количество для ${{safeName}}">
              <div class="quantity" data-product-id="${{escapeHtml(productId)}}">
                <button class="quantity__button" type="button" data-action="decrease" aria-label="Уменьшить">−</button>
                <input class="quantity__value" data-quantity-for="${{escapeHtml(productId)}}" data-quantity-input data-product-id="${{escapeHtml(productId)}}" type="number" min="0" max="${{escapeHtml(maxQuantity)}}" step="${{escapeHtml(step)}}" value="${{escapeHtml(quantity)}}" aria-label="Количество">
                <button class="quantity__button" type="button" data-action="increase" aria-label="Увеличить" ${{quantity >= maxQuantity ? 'disabled' : ''}}>+</button>
              </div>
            </div>
          </article>
        `;
        }} catch (error) {{
          console.error('[BusinessCatalog] Failed to render item card', {{
            error,
            message: error && error.message ? error.message : 'unknown error',
            stack: error && error.stack ? error.stack : null,
            index,
            item,
          }});
          return '';
        }}
      }}).filter(Boolean);
      currentItems = items.filter((item) => item && item.productId && item.name);
      gridEl.innerHTML = cards.join('');
      stateEl.hidden = true;
      gridEl.hidden = false;
    }}

    function updateQuantityControls(productId) {{
      const entry = cart.get(String(productId));
      const item = (entry && entry.item) || currentItems.find((candidate) => String(candidate.productId) === String(productId));
      const quantity = cartQuantity(productId);
      const maxQuantity = item ? maxOrderQuantity(item) : 0;
      document.querySelectorAll('[data-quantity-for]').forEach((node) => {{
        if (node.dataset.quantityFor === String(productId)) node.value = quantity;
      }});
      document.querySelectorAll('[data-product-id]').forEach((node) => {{
        if (node.dataset.productId !== String(productId)) return;
        node.querySelectorAll('[data-action="increase"]').forEach((button) => {{
          button.disabled = maxQuantity <= 0 || quantity >= maxQuantity;
        }});
      }});
    }}

    function setCartQuantity(item, nextQuantity) {{
      const productId = String(item.productId);
      const requestedQuantity = Math.max(0, Number(nextQuantity) || 0);
      const quantity = normalizeQuantity(item, requestedQuantity);
      const wasClamped = requestedQuantity > quantity;
      if (quantity === 0) {{
        cart.delete(productId);
      }} else {{
        cart.set(productId, {{ item, quantity }});
      }}
      updateQuantityControls(productId);
      renderCart();
      if (wasClamped) showCartMessage(`Нельзя добавить больше доступного количества для «${{item.name}}».`, true);
    }}

    function changeCartQuantity(productId, delta) {{
      const existingEntry = cart.get(String(productId));
      const item = currentItems.find((entry) => String(entry.productId) === String(productId)) || (existingEntry ? existingEntry.item : null);
      if (!item) return;
      setCartQuantity(item, cartQuantity(productId) + (delta * itemStep(item)));
    }}

    function renderCart() {{
      const entries = [...cart.values()];
      const totalQuantity = entries.reduce((sum, entry) => sum + entry.quantity, 0);
      const totalMinor = entries.reduce((sum, entry) => sum + (entry.item.price.amountMinor || 0) * entry.quantity, 0);
      const isBelowMinimum = totalMinor < minimumOrderAmountMinor;
      cartCounterEl.textContent = totalQuantity;
      if (entries.length === 0) {{
        cartBodyEl.innerHTML = `<div class="cart__empty" aria-label="Корзина пуста"></div><div class="cart__minimum is-below">Минимальная сумма заказа: ${{escapeHtml(minimumOrderLabel)}}.</div>`;
        return;
      }}
      const rows = entries.map(({{ item, quantity }}) => {{
        const lineTotal = (item.price.amountMinor || 0) * quantity;
        const step = itemStep(item);
        const maxQuantity = maxOrderQuantity(item);
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
                <input class="quantity__value" data-quantity-input data-product-id="${{escapeHtml(item.productId)}}" type="number" min="0" max="${{escapeHtml(maxQuantity)}}" step="${{escapeHtml(step)}}" value="${{escapeHtml(quantity)}}" aria-label="Количество">
                <button class="quantity__button" type="button" data-action="increase" aria-label="Увеличить" ${{quantity >= maxQuantity ? 'disabled' : ''}}>+</button>
              </div>
              <button class="cart-remove" type="button" data-action="remove" data-product-id="${{escapeHtml(item.productId)}}">Удалить</button>
            </div>
          </div>`;
      }}).join('');
      cartBodyEl.innerHTML = `
        <div class="cart__items">${{rows}}</div>
        <div class="cart__total"><span>Итого</span><strong>${{escapeHtml(formatMoney(totalMinor))}}</strong></div>
        <div class="cart__minimum${{isBelowMinimum ? ' is-below' : ''}}">Минимальная сумма заказа: ${{escapeHtml(minimumOrderLabel)}}.</div>
        <button class="cart__submit" type="button" data-action="submit-order" ${{isBelowMinimum ? 'disabled' : ''}}>Оформить заявку</button>`;
    }}

    function showCartMessage(message, isError = false) {{
      cartBodyEl.querySelectorAll('.cart__message').forEach((node) => node.remove());
      cartBodyEl.insertAdjacentHTML('beforeend', `<div class="cart__message${{isError ? ' is-error' : ''}}">${{escapeHtml(message)}}</div>`);
    }}

    async function submitOrder() {{
      const entries = [...cart.values()];
      const payload = {{
        comment: (orderCommentEl ? orderCommentEl.value : ''),
        items: entries.map((entry) => ({{
          productId: entry.item.productId,
          quantity: entry.quantity,
          price: {{
            amountMinor: entry.item.price.amountMinor,
            baseAmountMinor: entry.item.price.baseAmountMinor,
            pricingSource: entry.item.price.pricingSource,
            priceTypeName: entry.item.price.priceTypeName,
          }},
        }})),
      }};
      try {{
        const response = await fetch('/api/public/business/order', {{
          method: 'POST',
          headers: {{ 'Accept': 'application/json', 'Content-Type': 'application/json' }},
          body: JSON.stringify(payload),
        }});
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.error || `Ошибка ${{response.status}}`);
        cart.clear();
        if (orderCommentEl) orderCommentEl.value = '';
        renderCart();
        cartBodyEl.innerHTML = `<div class="cart__message">Заявка ${{escapeHtml(data.orderNumber)}} принята. Менеджер Stamm Brewing свяжется с вами.</div>`;
      }} catch (error) {{
        const message = (error && error.message) ? error.message : 'Не удалось оформить заявку';
        showCartMessage(message, true);
      }}
    }}

    async function loadCatalog() {{
      setState('Загружаем каталог', 'Получаем товары из локального backend API сайта.', 'loading');
      const suffix = activeFilter === 'all' ? '' : `?containerType=${{encodeURIComponent(activeFilter)}}`;
      const controller = new AbortController();
      const timeoutId = window.setTimeout(() => controller.abort(), 10000);
      let phase = 'init';
      let payload = null;
      let rawItems = [];
      let rejectedItems = [];
      try {{
        phase = 'fetch';
        const response = await fetch(`/api/public/business/catalog${{suffix}}`, {{ headers: {{ 'Accept': 'application/json' }}, signal: controller.signal }});
        if (!response.ok) throw new Error(`Local API error: ${{response.status}}`);
        phase = 'parse-json';
        const data = await response.json();
        payload = data;
        phase = 'normalize-items';
        rawItems = Array.isArray(data.items) ? data.items : [];
        const items = [];
        rawItems.forEach((rawItem, index) => {{
          try {{
            const item = normalizeCatalogItem(rawItem);
            if (item.productId && item.name) {{
              items.push(item);
            }} else {{
              rejectedItems.push({{ index, reason: 'missing productId or name', item: rawItem }});
            }}
          }} catch (error) {{
            rejectedItems.push({{
              index,
              reason: error && error.message ? error.message : 'normalization error',
              stack: error && error.stack ? error.stack : null,
              item: rawItem,
            }});
          }}
        }});
        if (rejectedItems.length) {{
          console.error('[BusinessCatalog] Skipped invalid catalog items', {{ rejectedItems, payload }});
        }}
        const meta = data.meta || {{}};
        const minimumOrder = meta.minimumOrder || {{}};
        minimumOrderAmountMinor = Number(minimumOrder.amountMinor || minimumOrderAmountMinor);
        minimumOrderLabel = minimumOrder.label || minimumOrderLabel;
        if (meta.totalLocalItems === 0) {{
          setState('Каталог скоро появится', 'В локальном каталоге пока нет опубликованных товаров. Оставьте заявку менеджеру Stamm Brewing.', 'empty');
          return;
        }}
        if (items.length === 0) {{
          const activeFilterButton = filterButtons.find((button) => button.dataset.filter === activeFilter);
          const label = activeFilterButton ? activeFilterButton.textContent : 'выбранному фильтру';
          setState('Ничего не найдено', `В локальном каталоге нет товаров по фильтру «${{label}}». Попробуйте другой фильтр.`, 'empty');
          return;
        }}
        phase = 'render-cards';
        renderCards(items);
        phase = 'render-cart';
        renderCart();
      }} catch (error) {{
        const message = error && error.name === 'AbortError' ? 'timeout' : ((error && error.message) ? error.message : 'unknown error');
        console.error('[BusinessCatalog] Catalog load failed', {{
          error,
          message,
          stack: error && error.stack ? error.stack : null,
          phase,
          activeFilter,
          payload,
          rawItems,
          rejectedItems,
        }});
        setState('Не удалось загрузить каталог сайта', 'Попробуйте обновить страницу или свяжитесь с менеджером. Техническое обновление каталога выполняется на стороне сайта.', 'error');
      }} finally {{
        window.clearTimeout(timeoutId);
      }}
    }}

    document.addEventListener('click', (event) => {{
      const actionButton = event.target.closest('[data-action]');
      if (!actionButton) return;
      const action = actionButton.dataset.action;
      if (action === 'submit-order') {{
        submitOrder();
        return;
      }}
      const productNode = actionButton.closest('[data-product-id]');
      const productId = actionButton.dataset.productId || (productNode ? productNode.dataset.productId : null);
      if (!productId) return;
      if (action === 'increase') changeCartQuantity(productId, 1);
      if (action === 'decrease') changeCartQuantity(productId, -1);
      if (action === 'remove') {{
        const entry = cart.get(String(productId));
        if (entry) setCartQuantity(entry.item, 0);
      }}
    }});

    document.addEventListener('change', (event) => {{
      const input = event.target.closest('[data-quantity-input]');
      if (!input) return;
      const productId = input.dataset.productId;
      const existingEntry = cart.get(String(productId));
      const item = currentItems.find((entry) => String(entry.productId) === String(productId)) || (existingEntry ? existingEntry.item : null);
      if (!item) return;
      setCartQuantity(item, input.value);
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
{age_gate_markup(site_content)}
</body>
</html>"""
