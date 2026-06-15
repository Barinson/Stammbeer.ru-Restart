from __future__ import annotations

import hashlib
import secrets
import smtplib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr
from html import escape
from typing import Any
from urllib.parse import quote

from app.config import Settings
from app.modules.auth.security import hash_password
from app.modules.account.service import normalize_email, utc_now_iso

EMAIL_CONFIRMATION_TTL_HOURS = 24
PASSWORD_RESET_TTL_HOURS = 1


@dataclass(frozen=True)
class EmailPayload:
    message_type: str
    to_email: str
    subject: str
    text_body: str
    html_body: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _base_url(settings: Settings) -> str:
    return settings.public_base_url.rstrip("/")


def _log_email(
    conn: sqlite3.Connection,
    payload: EmailPayload,
    provider: str,
    status: str,
    error_message: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO email_send_logs (message_type, recipient_email, subject, provider, status, error_message)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (payload.message_type, payload.to_email, payload.subject, provider, status, error_message),
    )
    conn.commit()


def _send_via_yandex(settings: Settings, payload: EmailPayload) -> None:
    if settings.email_provider != "yandex":
        raise ValueError("Поддерживается только email-provider yandex.")
    if not settings.email_smtp_username or not settings.email_smtp_password or not settings.email_from_email:
        raise ValueError("Не заполнены EMAIL_SMTP_USERNAME, EMAIL_SMTP_PASSWORD или EMAIL_FROM_EMAIL.")

    message = EmailMessage()
    message["Subject"] = payload.subject
    message["From"] = formataddr((settings.email_from_name, settings.email_from_email))
    message["To"] = payload.to_email
    message.set_content(payload.text_body)
    message.add_alternative(payload.html_body, subtype="html")

    if settings.email_smtp_port == 465:
        with smtplib.SMTP_SSL(settings.email_smtp_host, settings.email_smtp_port, timeout=15) as smtp:
            smtp.login(settings.email_smtp_username, settings.email_smtp_password)
            smtp.send_message(message)
        return

    with smtplib.SMTP(settings.email_smtp_host, settings.email_smtp_port, timeout=15) as smtp:
        smtp.starttls()
        smtp.login(settings.email_smtp_username, settings.email_smtp_password)
        smtp.send_message(message)


def send_email(conn: sqlite3.Connection, settings: Settings, payload: EmailPayload) -> bool:
    provider = settings.email_provider or "yandex"
    if not settings.email_enabled:
        _log_email(conn, payload, provider, "skipped", "EMAIL_ENABLED=false")
        return False
    try:
        _send_via_yandex(settings, payload)
    except Exception as exc:
        _log_email(conn, payload, provider, "failed", str(exc))
        return False
    _log_email(conn, payload, provider, "sent")
    return True


def _render_shell(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="ru">
<body style="margin:0;background:#0b3f40;color:#f6f1e3;font-family:Jost,Arial,sans-serif;">
  <div style="max-width:640px;margin:0 auto;padding:32px 20px;">
    <h1 style="margin:0 0 18px;color:#c7b166;letter-spacing:.06em;text-transform:uppercase;">{escape(title)}</h1>
    <div style="font-size:16px;line-height:1.55;">{body}</div>
  </div>
</body>
</html>"""


def _button(url: str, label: str) -> str:
    return (
        f'<p><a href="{escape(url)}" style="display:inline-block;padding:12px 18px;border-radius:999px;'
        'background:#c7b166;color:#082f30;text-decoration:none;font-weight:800;">'
        f"{escape(label)}</a></p>"
    )


def create_email_verification_token(conn: sqlite3.Connection, account_id: int) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute(
        """
        INSERT INTO customer_email_verification_tokens (customer_account_id, token_hash, expires_at)
        VALUES (?, ?, ?)
        """,
        (account_id, _token_hash(token), _iso(_now() + timedelta(hours=EMAIL_CONFIRMATION_TTL_HOURS))),
    )
    conn.commit()
    return token


def send_email_confirmation(conn: sqlite3.Connection, settings: Settings, account: sqlite3.Row) -> bool:
    token = create_email_verification_token(conn, int(account["id"]))
    link = f"{_base_url(settings)}/account/verify-email?token={quote(token)}"
    text = (
        "Подтвердите e-mail для личного кабинета Stamm Brewing.\n\n"
        f"Ссылка действует {EMAIL_CONFIRMATION_TTL_HOURS} часов и используется один раз:\n{link}"
    )
    html = _render_shell(
        "Подтверждение e-mail",
        f"<p>Подтвердите e-mail для личного кабинета Stamm Brewing.</p>{_button(link, 'Подтвердить e-mail')}"
        f"<p>Ссылка действует {EMAIL_CONFIRMATION_TTL_HOURS} часов и используется один раз.</p>",
    )
    return send_email(conn, settings, EmailPayload("email_confirmation", account["email"], "Подтвердите e-mail · Stamm Brewing", text, html))


def _load_active_token(conn: sqlite3.Connection, table: str, token: str) -> sqlite3.Row | None:
    row = conn.execute(
        f"SELECT * FROM {table} WHERE token_hash = ? AND used_at IS NULL",
        (_token_hash(token),),
    ).fetchone()
    if row is None:
        return None
    expires_at = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
    if expires_at <= _now():
        return None
    return row


def verify_customer_email(conn: sqlite3.Connection, token: str) -> bool:
    row = _load_active_token(conn, "customer_email_verification_tokens", token)
    if row is None:
        return False
    now = utc_now_iso()
    conn.execute("UPDATE customer_accounts SET email_verified_at = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (now, row["customer_account_id"]))
    conn.execute("UPDATE customer_email_verification_tokens SET used_at = ? WHERE id = ?", (now, row["id"]))
    conn.commit()
    return True


def send_password_reset(conn: sqlite3.Connection, settings: Settings, email: str) -> bool:
    account = conn.execute("SELECT * FROM customer_accounts WHERE lower(email) = lower(?)", (normalize_email(email),)).fetchone()
    if account is None or account["status"] != "active":
        return False
    token = secrets.token_urlsafe(32)
    conn.execute(
        """
        INSERT INTO customer_password_reset_tokens (customer_account_id, token_hash, expires_at)
        VALUES (?, ?, ?)
        """,
        (account["id"], _token_hash(token), _iso(_now() + timedelta(hours=PASSWORD_RESET_TTL_HOURS))),
    )
    conn.commit()
    link = f"{_base_url(settings)}/account/password-reset/confirm?token={quote(token)}"
    text = (
        "Вы запросили восстановление пароля Stamm Brewing.\n\n"
        f"Ссылка действует {PASSWORD_RESET_TTL_HOURS} час и используется один раз:\n{link}\n\n"
        "Если вы не запрашивали сброс пароля, просто игнорируйте письмо."
    )
    html = _render_shell(
        "Восстановление пароля",
        f"<p>Вы запросили восстановление пароля Stamm Brewing.</p>{_button(link, 'Сбросить пароль')}"
        f"<p>Ссылка действует {PASSWORD_RESET_TTL_HOURS} час и используется один раз.</p>"
        "<p>Если вы не запрашивали сброс пароля, просто игнорируйте письмо.</p>",
    )
    return send_email(conn, settings, EmailPayload("password_reset", account["email"], "Восстановление пароля · Stamm Brewing", text, html))


def reset_customer_password(conn: sqlite3.Connection, token: str, password: str, password_confirm: str) -> tuple[bool, str]:
    if len(password) < 8:
        return False, "Пароль должен быть не короче 8 символов."
    if password != password_confirm:
        return False, "Пароль и подтверждение не совпадают."
    row = _load_active_token(conn, "customer_password_reset_tokens", token)
    if row is None:
        return False, "Ссылка сброса пароля недействительна или устарела."
    now = utc_now_iso()
    conn.execute(
        "UPDATE customer_accounts SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (hash_password(password), row["customer_account_id"]),
    )
    conn.execute("UPDATE customer_password_reset_tokens SET used_at = ? WHERE id = ?", (now, row["id"]))
    conn.commit()
    return True, "Пароль обновлён. Теперь можно войти."


def send_order_created(
    conn: sqlite3.Connection,
    settings: Settings,
    customer: sqlite3.Row,
    order_number: str,
    order_date: str,
    items: list[dict[str, Any]],
    total_minor: int,
    comment: str = "",
    moysklad_order_name: str | None = None,
) -> bool:
    display_number = moysklad_order_name or order_number
    item_lines = []
    item_rows = []
    for entry in items:
        item = entry["item"]
        qty = int(entry["quantity"])
        line_total = int(entry["lineTotalMinor"])
        price_minor = int(((item.get("price") or {}).get("amountMinor")) or 0)
        price_text = f"{price_minor / 100:,.2f} ₽".replace(",", " ")
        line_total_text = f"{line_total / 100:,.2f} ₽".replace(",", " ")
        item_lines.append(f"- {item['name']} × {qty}: {line_total_text}")
        item_rows.append(
            "<tr>"
            f"<td style='padding:8px;border-bottom:1px solid rgba(199,177,102,.25);'>{escape(str(item['name']))}</td>"
            f"<td style='padding:8px;border-bottom:1px solid rgba(199,177,102,.25);text-align:right;'>{qty}</td>"
            f"<td style='padding:8px;border-bottom:1px solid rgba(199,177,102,.25);text-align:right;'>{price_text}</td>"
            f"<td style='padding:8px;border-bottom:1px solid rgba(199,177,102,.25);text-align:right;'>{line_total_text}</td>"
            "</tr>"
        )
    total = f"{total_minor / 100:,.2f} ₽".replace(",", " ")
    text = (
        f"Заказ {display_number} создан.\n"
        f"Дата: {order_date}\n\n"
        "Позиции:\n" + "\n".join(item_lines) + f"\n\nИтого: {total}"
    )
    if comment.strip():
        text += f"\nКомментарий: {comment.strip()}"
    html = _render_shell(
        "Заказ создан",
        f"<p>Заказ <strong>{escape(str(display_number))}</strong> создан.</p>"
        f"<p>Дата: {escape(order_date)}</p>"
        "<table style='width:100%;border-collapse:collapse;'>"
        "<thead><tr><th align='left'>Позиция</th><th align='right'>Кол-во</th><th align='right'>Цена</th><th align='right'>Сумма</th></tr></thead>"
        f"<tbody>{''.join(item_rows)}</tbody></table>"
        f"<p><strong>Итого: {escape(total)}</strong></p>"
        + (f"<p>Комментарий: {escape(comment.strip())}</p>" if comment.strip() else ""),
    )
    return send_email(conn, settings, EmailPayload("order_created", customer["email"], f"Заказ {display_number} создан · Stamm Brewing", text, html))
