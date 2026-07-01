from __future__ import annotations

import json
from html import escape
from urllib.parse import quote
from typing import Any

from app.modules.content.service import ACTION_DEFAULTS, BUSINESS_DEFAULTS, CONTACT_DEFAULTS, HOME_DEFAULTS, LAYOUT_DEFAULTS, MENU_DEFAULTS, SITE_DEFAULTS, TYPOGRAPHY_DEFAULTS


PUBLIC_HEAD = """<meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\">
  <link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>
  <link href=\"https://fonts.googleapis.com/css2?family=Jost:wght@400;500;700;800;900&display=swap\" rel=\"stylesheet\">"""


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
    .top-nav + main { padding-top:var(--menu-offset,176px); }
    body.age-gate-pending { overflow:hidden; }
    .age-gate { position:fixed; inset:0; z-index:1000; display:grid; place-items:center; padding:24px; background:radial-gradient(circle at 50% 25%, rgba(199,177,102,.16), transparent 30%), rgba(11,63,64,.96); backdrop-filter:blur(14px); }
    .age-gate.is-hidden { display:none; }
    .age-gate__card { width:min(520px,100%); border-radius:28px; padding:34px; background:var(--card-hop); box-shadow:0 30px 90px rgba(0,0,0,.32); text-align:center; color:var(--foam); }
    .age-gate__card h2 { margin:0 0 12px; color:var(--golden-malt); font-size:clamp(34px,6vw,56px); line-height:.95; letter-spacing:.06em; text-transform:uppercase; }
    .age-gate__card p { margin:0; color:rgba(246,241,227,.8); font-size:var(--stamm-lead-font-size,18px); line-height:1.45; }
    .age-gate__actions { display:flex; justify-content:center; gap:12px; flex-wrap:wrap; margin-top:24px; }
    .age-gate__card button { border:0; border-radius:999px; padding:14px 22px; background:var(--golden-malt); color:var(--ink); font:inherit; font-weight:900; cursor:pointer; }
    .age-gate__card .age-gate__deny { background:transparent; color:var(--foam); border:1px solid rgba(199,177,102,.42); }
    @media (max-width:920px) { .top-nav { align-items:flex-start; flex-direction:column; position:sticky; } .top-nav + main { padding-top:0; } .nav-links { justify-content:flex-start; } }
"""


def public_content_or_defaults(content: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "home": {**HOME_DEFAULTS, **((content or {}).get("home") or {})},
        "business": {**BUSINESS_DEFAULTS, **((content or {}).get("business") or {})},
        "contacts": {**CONTACT_DEFAULTS, **((content or {}).get("contacts") or {})},
        "typography": {**TYPOGRAPHY_DEFAULTS, **((content or {}).get("typography") or {})},
        "layout": {**LAYOUT_DEFAULTS, **((content or {}).get("layout") or {})},
        "site": {**SITE_DEFAULTS, **((content or {}).get("site") or {})},
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
    links = "".join(
        f'<a class="{"is-active" if item.get("key") == active else ""}" href="{escape(str(item.get("href") or "#"))}">{escape(str(item.get("label") or ""))}</a>'
        for item in site_content["menu"]
        if item.get("is_visible", True)
    )
    action_links = []
    for item in site_content["actions"]:
        if not item.get("is_visible", True):
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
    <a class="brand" href="/">Stamm Brewing</a>
    <div class="nav-links">{links}</div>
    <div class="nav-actions" aria-label="Соцсети и корзина">{actions}</div>
  </nav>"""


def age_gate_markup(content: dict[str, Any] | None = None) -> str:
    site_content = public_content_or_defaults(content)
    if (site_content.get("viewer") or {}).get("is_customer"):
        return ""
    site = site_content.get("site") or {}
    title = escape(str(site.get("age_gate_title") or SITE_DEFAULTS["age_gate_title"]))
    text = cms_text(site.get("age_gate_text") or SITE_DEFAULTS["age_gate_text"])
    confirm_label = escape(str(site.get("age_gate_confirm_label") or SITE_DEFAULTS["age_gate_confirm_label"]))
    deny_label = escape(str(site.get("age_gate_deny_label") or SITE_DEFAULTS["age_gate_deny_label"]))
    return f"""
  <div class="age-gate" id="ageGate" role="dialog" aria-modal="true" aria-labelledby="ageGateTitle">
    <div class="age-gate__card">
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
      const gate = document.getElementById("ageGate");
      const button = document.getElementById("ageGateConfirm");
      const rejectButton = document.getElementById("ageGateReject");
      if (!gate || !button || !rejectButton) return;
      function unlock() {{
        gate.classList.add("is-hidden");
        document.body.classList.remove("age-gate-pending");
      }}
      document.body.classList.add("age-gate-pending");
      button.addEventListener("click", unlock);
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
    raw_text = str(site.get("maintenance_text") or SITE_DEFAULTS["maintenance_text"])
    text_html = cms_text(raw_text).replace(
        "marketing@stammbeer.ru",
        '<a href="mailto:marketing@stammbeer.ru">marketing@stammbeer.ru</a>',
    )
    return f"""<!doctype html>
<html lang="ru">
<head>
  {PUBLIC_HEAD}
  <title>Stamm Brewing · Технические работы</title>
  <style>
{BASE_CSS}
{typography_style(site_content)}
    .maintenance-shell {{ min-height:100vh; display:grid; place-items:center; padding:120px min(6vw,72px) 72px; text-align:center; background:radial-gradient(circle at 50% 18%, rgba(199,177,102,.16), transparent 30%), linear-gradient(135deg, var(--noble-hop), var(--deep-hop)); }}
    .maintenance-message {{ width:min(760px,100%); margin:0; color:var(--foam); font-size:clamp(18px,2.2vw,28px); line-height:1.45; white-space:pre-line; }}
    .maintenance-message a {{ color:var(--golden-malt); text-decoration:none; }}
  </style>
</head>
<body>
  <main class="maintenance-shell" aria-label="Технические работы">
    <p class="maintenance-message">{text_html}</p>
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
    content_bg_style = f' style="--home-content-bg:url(\'{escape(content_bg_url)}\');"' if content_bg_url else ""
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
  {PUBLIC_HEAD}
  <title>Stamm Brewing · Главная</title>
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
    .home-content {{ position:relative; min-height:100vh; background-image:linear-gradient(180deg, rgba(16,88,89,.84), rgba(11,63,64,.9)), var(--home-content-bg, linear-gradient(135deg, var(--noble-hop), var(--deep-hop))); background-size:cover; background-position:center; background-repeat:no-repeat; background-attachment:fixed; }}
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
    @media (max-width:760px) {{ .home-content {{ background-attachment:scroll; }} .news-card {{ grid-template-columns:1fr; padding:20px; }} .home-logo {{ max-width:130px; max-height:130px; }} }}
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
    .account-orders { display:grid; gap:12px; }
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
    @media (max-width:680px) { .account-shell { padding:56px 18px; } .account-card { padding:24px; } .account-detail { display:grid; gap:4px; } .account-detail strong { text-align:left; } }
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
    return f"""<!doctype html>
<html lang="ru">
<head>
  {PUBLIC_HEAD}
  <title>Контакты · Stamm Brewing</title>
  <style>
{BASE_CSS}
{typography_style(site_content)}
    .contacts-page {{ min-height:calc(100vh - 88px); padding:104px min(6vw,72px) 64px; display:grid; place-items:start center; background:linear-gradient(135deg, var(--noble-hop), var(--deep-hop)); }}
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
    @media (max-width:880px) {{ .contacts-info-card {{ justify-self:stretch; }} .map-card {{ width:100%; justify-self:stretch; }} }}
  </style>
</head>
<body>
{public_nav("contacts", site_content)}
  <main class="contacts-page" style="--menu-offset:{menu_offset_px(site_content, 'contacts')};">
    <section class="contacts-hero">
      <div class="contacts-card contacts-info-card">
        {description_markup}
        {address_markup}
        <ul class="contact-list">{email_cards}</ul>
        <ul class="contact-list">{phone_cards}</ul>
      </div>
      <div class="contacts-card map-card" style="--contacts-map-height:{map_height}; --contacts-map-width:{map_width}">
        <iframe title="Яндекс.Карта: {escape(title)}" src="{map_src}" loading="lazy" allowfullscreen></iframe>
        <div class="map-compact-badge"><strong>{escape(title)}</strong><span>★ оценка на Яндекс Картах</span></div>
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
        partners_section = f'<section class="beer-section"><h1>{escape(str(beer.get("beer_partners_title") or "Где найти Stamm Brewing"))}</h1><p>{cms_text(beer.get("beer_partners_description") or "")}</p><div class="partners-grid">{"".join(partner_cards)}</div></section>'
    products_inner = ""
    if is_enabled(beer.get("beer_new_is_visible"), True):
        products_inner += f'<div class="product-subsection"><h3>{escape(str(beer.get("beer_new_title") or "Новинки"))}</h3><div class="new-grid">{new_cards}</div></div>'
    if is_enabled(beer.get("beer_core_is_visible"), True):
        products_inner += f'<div class="product-subsection"><h3>{escape(str(beer.get("beer_core_title") or "Постоянная линейка"))}</h3><div class="seasonal-grid">{core_cards}</div></div>'
    if is_enabled(beer.get("beer_seasonal_is_visible"), True):
        products_inner += f'<div class="product-subsection"><h3>{escape(str(beer.get("beer_seasonal_title") or "Сезонные сорта"))}</h3><div class="seasonal-grid">{seasonal_cards}</div></div>'
    products_section = f'<section class="beer-section"><h2>{escape(str(beer.get("beer_products_title") or "Наша продукция"))}</h2>{products_inner}</section>' if is_enabled(beer.get("beer_products_is_visible"), True) else ""
    beer_bg_url = str(site_content.get("home", {}).get("home_content_bg_url") or "")
    beer_style_values = [f"--menu-offset:{menu_offset_px(site_content, 'beer')}"]
    beer_section_gap = css_section_gap_px(beer.get("beer_section_gap_px"), 72)
    if beer_bg_url:
        beer_style_values.append(f"--beer-bg:url('{escape(beer_bg_url)}')")
    beer_page_style = f' style="{";".join(beer_style_values)}"'
    return f"""<!doctype html>
<html lang="ru">
<head>
  {PUBLIC_HEAD}
  <title>Пиво · Stamm Brewing</title>
  <style>
{BASE_CSS}
{typography_style(site_content)}
    .beer-page {{ min-height:calc(100vh - 88px); padding:120px min(6vw,72px) 72px; background-image:linear-gradient(180deg, rgba(16,88,89,.78), rgba(11,63,64,.86)), var(--beer-bg, linear-gradient(135deg, var(--noble-hop), var(--deep-hop))); background-size:cover; background-position:center; background-repeat:no-repeat; background-attachment:fixed; }}
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
    .seasonal-grid {{ width:min(1320px,100%); display:flex; flex-wrap:wrap; justify-content:center; align-items:end; gap:16px; margin:0 auto; }}
    .beer-can {{ border:0; background:transparent; color:var(--foam); cursor:pointer; display:grid; justify-items:center; gap:10px; font:inherit; font-weight:800; transition:transform .18s ease; }}
    .seasonal-grid .beer-can {{ flex:0 1 calc((100% - 128px) / 9); max-width:132px; min-width:72px; }}
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
    @media (max-width:1100px) {{ .seasonal-grid .beer-can {{ flex-basis:110px; }} }}
    @media (max-width:760px) {{ .new-grid {{ grid-template-columns:1fr; }} .beer-page {{ padding:76px 20px 54px; background-attachment:scroll; }} }}
  </style>
</head>
<body>
{public_nav("beer", site_content)}
  <main class="beer-page"{beer_page_style}><div class="beer-shell">{partners_section}{products_section}</div></main>
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

def public_placeholder_page(title: str, active: str, content: dict[str, Any] | None = None) -> str:
    site_content = public_content_or_defaults(content)
    return f"""<!doctype html>
<html lang="ru">
<head>
  {PUBLIC_HEAD}
  <title>{title} · Stamm Brewing</title>
  <style>
{BASE_CSS}
{typography_style(site_content)}
    .placeholder {{ min-height:54vh; display:grid; place-items:center; padding:96px min(6vw,72px) 72px; background:linear-gradient(135deg, var(--noble-hop), var(--deep-hop)); }}
    .placeholder__card {{ max-width:760px; background:var(--card-hop); border:1px solid rgba(199,177,102,.2); border-radius:24px; padding:30px; }}
    .placeholder__card h1 {{ margin:0 0 10px; color:var(--golden-malt); text-transform:uppercase; letter-spacing:.08em; font-size:var(--stamm-page-title-font-size,42px); }}
    .placeholder__card p {{ margin:0; color:rgba(246,241,227,.76); }}
  </style>
</head>
<body>
{public_nav(active, site_content)}
  <main class="placeholder" style="--menu-offset:{menu_offset_px(site_content, active)};"><section class="placeholder__card"><h1>{title}</h1><p>Раздел будет собираться после ядра B2B-магазина и админки.</p></section></main>
{age_gate_markup(site_content)}
</body>
</html>"""


def business_guest_page(content: dict[str, Any] | None = None) -> str:
    site_content = public_content_or_defaults(content)
    site_content = {**site_content, "actions": [{**item, "is_visible": False} if item.get("key") == "cart" else item for item in site_content.get("actions", [])]}
    message = "Чтобы стать нашим партнёром, напишите на marketing@stammbeer.ru"
    return f"""<!doctype html>
<html lang="ru">
<head>
  {PUBLIC_HEAD}
  <title>Бизнес · Stamm Brewing</title>
  <style>
{BASE_CSS}
{typography_style(site_content)}
    .business-guest {{ min-height:calc(100vh - 88px); padding:var(--menu-offset,176px) min(6vw,72px) 72px; display:grid; place-items:center; background:radial-gradient(circle at 24% 18%, rgba(199,177,102,.16), transparent 32%), linear-gradient(135deg, var(--noble-hop), var(--deep-hop)); }}
    .business-guest__message {{ max-width:620px; margin:0 auto; text-align:center; color:var(--foam); font-size:clamp(17px,2vw,24px); line-height:1.38; font-weight:600; letter-spacing:.01em; }}
  </style>
</head>
<body>
{public_nav("business", site_content)}
  <main class="business-guest" style="--menu-offset:{menu_offset_px(site_content, 'business')};">
    <p class="business-guest__message">{escape(message)}</p>
  </main>
{age_gate_markup(site_content)}
</body>
</html>"""


def business_storefront_page(content: dict[str, Any] | None = None) -> str:
    site_content = public_content_or_defaults(content)
    return f"""<!doctype html>
<html lang="ru">
<head>
  {PUBLIC_HEAD}
  <title>Бизнес · Stamm Brewing</title>
  <style>
{BASE_CSS}
{typography_style(site_content)}
    .wrap {{ padding:58px min(6vw,72px) 56px; }}
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
    .quantity__value {{ text-align:center; font-weight:700; color:var(--foam); font-size:13px; }}
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
    @media (max-width:720px) {{ .wrap {{ padding:16px min(5vw,28px) 36px; }} .product {{ grid-template-columns:60px minmax(0,1fr); gap:10px; min-height:86px; padding:9px; }} .product__image {{ width:56px; height:56px; border-radius:12px; }} .product__order {{ grid-column:2; justify-self:start; min-width:0; margin-top:2px; }} h2 {{ font-size:15px; }} .price {{ font-size:15px; }} .quantity {{ grid-template-columns:28px 36px 28px; }} .quantity__button {{ width:28px; height:28px; }} }}
  </style>
</head>
<body>
{public_nav("business", content)}
  <main class="wrap" style="--menu-offset:{menu_offset_px(site_content, 'business')};">
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
      return String(value ?? '').replace(/[&<>"']/g, (char) => ({{ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }}[char]));
    }}

    function formatMoney(amountMinor, currency = 'RUB') {{
      if (amountMinor === null || amountMinor === undefined) return 'Цена по запросу';
      return `${{Number(amountMinor / 100).toLocaleString('ru-RU')}} ₽`;
    }}

    function cartQuantity(productId) {{
      return cart.get(String(productId))?.quantity || 0;
    }}

    function itemStep(item) {{
      return Number(item?.orderRules?.step || (item?.containerType === 'can' ? 12 : 1));
    }}

    function normalizeQuantity(item, quantity) {{
      const step = itemStep(item);
      const raw = Math.max(0, Number(quantity) || 0);
      if (raw === 0) return 0;
      if (item?.containerType === 'can') return Math.ceil(raw / 12) * 12;
      return Math.ceil(raw / step) * step;
    }}

    function renderCards(items) {{
      currentItems = items;
      gridEl.innerHTML = items.map((item) => {{
        const safeName = escapeHtml(item.name);
        const safeContainer = escapeHtml(item.containerLabel);
        const safePrice = escapeHtml(item.price.label);
        const basePrice = item.price.showBasePrice ? `<span class="price-base">${{escapeHtml(item.price.baseLabel)}}</span>` : '';
        const abvBadge = item.alcoholLabel ? `<span class="badge">${{escapeHtml(item.alcoholLabel)}}</span>` : '';
        const fallback = `<div class="product__image-fallback" aria-label="Фото скоро появится"></div>`;
        const imageMarkup = item.imageUrl
          ? `<img src="${{escapeHtml(item.imageUrl)}}" alt="${{safeName}}" loading="lazy" onerror="this.hidden=true; this.nextElementSibling.hidden=false"><div class="product__image-fallback" aria-label="Фото скоро появится" hidden></div>`
          : fallback;
        const quantity = cartQuantity(item.productId);
        const stepHint = item.containerType === 'can' ? '<span class="badge">ящик ×12</span>' : '';
        return `
        <article class="product">
          <div class="product__image">${{imageMarkup}}</div>
          <div class="product__body">
            <div class="badges"><span class="badge">${{safeContainer}}</span>${{stepHint}}${{abvBadge}}</div>
            <h2>${{safeName}}</h2>
            <div class="meta"><span class="price">${{safePrice}}</span>${{basePrice}}</div>
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

    function updateQuantityControls(productId) {{
      document.querySelectorAll('[data-quantity-for]').forEach((node) => {{
        if (node.dataset.quantityFor === String(productId)) node.textContent = cartQuantity(productId);
      }});
    }}

    function setCartQuantity(item, nextQuantity) {{
      const productId = String(item.productId);
      const quantity = normalizeQuantity(item, nextQuantity);
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
        <div class="cart__minimum${{isBelowMinimum ? ' is-below' : ''}}">Минимальная сумма заказа: ${{escapeHtml(minimumOrderLabel)}}.</div>
        <button class="cart__submit" type="button" data-action="submit-order" ${{isBelowMinimum ? 'disabled' : ''}}>Оформить заявку</button>`;
    }}

    async function submitOrder() {{
      const entries = [...cart.values()];
      const payload = {{
        comment: orderCommentEl?.value || '',
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
        const message = error?.message || 'Не удалось оформить заявку';
        cartBodyEl.insertAdjacentHTML('beforeend', `<div class="cart__message is-error">${{escapeHtml(message)}}</div>`);
      }}
    }}

    async function loadCatalog() {{
      setState('Загружаем каталог', 'Получаем товары из локального backend API сайта.', 'loading');
      const suffix = activeFilter === 'all' ? '' : `?containerType=${{encodeURIComponent(activeFilter)}}`;
      const controller = new AbortController();
      const timeoutId = window.setTimeout(() => controller.abort(), 10000);
      try {{
        const response = await fetch(`/api/public/business/catalog${{suffix}}`, {{ headers: {{ 'Accept': 'application/json' }}, signal: controller.signal }});
        if (!response.ok) throw new Error(`Local API error: ${{response.status}}`);
        const data = await response.json();
        const items = Array.isArray(data.items) ? data.items : [];
        const meta = data.meta || {{}};
        minimumOrderAmountMinor = Number(meta.minimumOrder?.amountMinor || minimumOrderAmountMinor);
        minimumOrderLabel = meta.minimumOrder?.label || minimumOrderLabel;
        if (meta.totalLocalItems === 0) {{
          setState('Каталог скоро появится', 'В локальном каталоге пока нет опубликованных товаров. Оставьте заявку менеджеру Stamm Brewing.', 'empty');
          return;
        }}
        if (items.length === 0) {{
          const label = filterButtons.find((button) => button.dataset.filter === activeFilter)?.textContent || 'выбранному фильтру';
          setState('Ничего не найдено', `В локальном каталоге нет товаров по фильтру «${{label}}». Попробуйте другой фильтр.`, 'empty');
          return;
        }}
        renderCards(items);
        renderCart();
      }} catch (error) {{
        const message = error?.name === 'AbortError' ? 'timeout' : (error?.message || 'unknown error');
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
{age_gate_markup(site_content)}
</body>
</html>"""
