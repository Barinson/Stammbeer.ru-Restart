from __future__ import annotations

import hashlib
import json
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
from app.timezone import format_moscow_datetime
from app.integrations.moysklad.settings_service import decode_token, encode_token
from app.modules.auth.security import hash_password
from app.modules.account.service import normalize_email, utc_now_iso

EMAIL_CONFIRMATION_TTL_HOURS = 24
PASSWORD_RESET_TTL_HOURS = 1



EMAIL_TEMPLATE_DEFAULTS: dict[str, dict[str, str]] = {
    "registration_confirmation": {"label": "Подтверждение регистрации", "subject": "Регистрация Stamm Brewing"},
    "email_confirmation": {"label": "Подтверждение email", "subject": "Подтвердите e-mail · Stamm Brewing"},
    "password_reset": {"label": "Восстановление пароля", "subject": "Восстановление пароля · Stamm Brewing"},
    "order_created": {"label": "Заказ создан", "subject": "Заказ создан · Stamm Brewing"},
    "order_status_changed": {"label": "Заказ изменён / статус изменён", "subject": "Статус заказа изменён · Stamm Brewing"},
    "test": {"label": "Тестовое письмо", "subject": "Тест почты · Stamm Brewing"},
}


@dataclass(frozen=True)
class EmailConfig:
    provider: str
    enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    from_email: str
    from_name: str
    reply_to_email: str
    use_ssl: bool
    use_tls: bool
    source: str


@dataclass(frozen=True)
class EmailServiceResult:
    ok: bool
    message: str
    details: str | None = None


def resolve_email_config(conn: sqlite3.Connection, settings: Settings) -> EmailConfig:
    row = conn.execute("SELECT * FROM email_settings WHERE id = 1").fetchone()
    if row is None:
        return EmailConfig(
            provider=settings.email_provider or "yandex",
            enabled=bool(settings.email_enabled),
            smtp_host=settings.email_smtp_host,
            smtp_port=int(settings.email_smtp_port),
            smtp_username=settings.email_smtp_username,
            smtp_password=settings.email_smtp_password,
            from_email=settings.email_from_email or settings.email_smtp_username,
            from_name=settings.email_from_name,
            reply_to_email="",
            use_ssl=int(settings.email_smtp_port) == 465,
            use_tls=int(settings.email_smtp_port) != 465,
            source="env",
        )
    return EmailConfig(
        provider=row["provider"] or "yandex",
        enabled=bool(row["is_enabled"]),
        smtp_host=row["smtp_host"] or "smtp.yandex.com",
        smtp_port=int(row["smtp_port"] or 465),
        smtp_username=row["smtp_username"] or "",
        smtp_password=decode_token(row["smtp_password_secret"] or ""),
        from_email=row["from_email"] or row["smtp_username"] or "",
        from_name=row["from_name"] or "Stamm Brewing",
        reply_to_email=row["reply_to_email"] or "",
        use_ssl=bool(row["use_ssl"]),
        use_tls=bool(row["use_tls"]),
        source="database",
    )


def email_service_status(conn: sqlite3.Connection, settings: Settings) -> dict[str, Any]:
    config = resolve_email_config(conn, settings)
    missing = []
    if not config.smtp_host:
        missing.append("SMTP host")
    if not config.smtp_username:
        missing.append("username")
    if not config.smtp_password:
        missing.append("password/app password")
    if not config.from_email:
        missing.append("from email")
    return {
        "provider": config.provider,
        "enabled": config.enabled,
        "source": config.source,
        "smtpHost": config.smtp_host,
        "smtpPort": config.smtp_port,
        "smtpUsername": config.smtp_username,
        "hasPassword": bool(config.smtp_password),
        "fromEmail": config.from_email,
        "fromName": config.from_name,
        "replyToEmail": config.reply_to_email,
        "useSsl": config.use_ssl,
        "useTls": config.use_tls,
        "ready": not missing,
        "missing": missing,
    }


def save_email_settings(conn: sqlite3.Connection, form: dict[str, Any]) -> None:
    existing = conn.execute("SELECT * FROM email_settings WHERE id = 1").fetchone()
    password = str(form.get("smtp_password") or "").strip()
    password_secret = encode_token(password) if password else (existing["smtp_password_secret"] if existing else "")
    conn.execute(
        """
        INSERT INTO email_settings (
            id, provider, is_enabled, smtp_host, smtp_port, smtp_username, smtp_password_secret,
            from_email, from_name, reply_to_email, use_ssl, use_tls, updated_at
        ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            provider = excluded.provider,
            is_enabled = excluded.is_enabled,
            smtp_host = excluded.smtp_host,
            smtp_port = excluded.smtp_port,
            smtp_username = excluded.smtp_username,
            smtp_password_secret = excluded.smtp_password_secret,
            from_email = excluded.from_email,
            from_name = excluded.from_name,
            reply_to_email = excluded.reply_to_email,
            use_ssl = excluded.use_ssl,
            use_tls = excluded.use_tls,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            str(form.get("provider") or "yandex").strip() or "yandex",
            1 if form.get("is_enabled") else 0,
            str(form.get("smtp_host") or "smtp.yandex.com").strip(),
            int(form.get("smtp_port") or 465),
            str(form.get("smtp_username") or "").strip(),
            password_secret,
            str(form.get("from_email") or "").strip(),
            str(form.get("from_name") or "Stamm Brewing").strip() or "Stamm Brewing",
            str(form.get("reply_to_email") or "").strip(),
            1 if form.get("use_ssl") else 0,
            1 if form.get("use_tls") else 0,
        ),
    )
    conn.commit()


def list_email_templates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = {row["message_type"]: row for row in conn.execute("SELECT * FROM email_templates").fetchall()}
    templates = []
    for message_type, defaults in EMAIL_TEMPLATE_DEFAULTS.items():
        row = rows.get(message_type)
        templates.append({
            "messageType": message_type,
            "label": defaults["label"],
            "enabled": bool(row["is_enabled"]) if row else True,
            "subject": row["subject"] if row else defaults["subject"],
            "bodyText": row["body_text"] if row else "",
        })
    return templates


def save_email_templates(conn: sqlite3.Connection, form: dict[str, Any]) -> None:
    for message_type, defaults in EMAIL_TEMPLATE_DEFAULTS.items():
        subject = str(form.get(f"subject_{message_type}") or defaults["subject"]).strip() or defaults["subject"]
        body_text = str(form.get(f"body_{message_type}") or "").strip()
        enabled = 1 if form.get(f"enabled_{message_type}") else 0
        conn.execute(
            """
            INSERT INTO email_templates (message_type, is_enabled, subject, body_text, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(message_type) DO UPDATE SET
                is_enabled = excluded.is_enabled,
                subject = excluded.subject,
                body_text = excluded.body_text,
                updated_at = CURRENT_TIMESTAMP
            """,
            (message_type, enabled, subject, body_text),
        )
    conn.commit()


def _template_for(conn: sqlite3.Connection, message_type: str) -> dict[str, Any]:
    defaults = EMAIL_TEMPLATE_DEFAULTS.get(message_type, {"label": message_type, "subject": message_type})
    row = conn.execute("SELECT * FROM email_templates WHERE message_type = ?", (message_type,)).fetchone()
    if row is None:
        return {"enabled": True, "subject": defaults["subject"], "bodyText": ""}
    return {"enabled": bool(row["is_enabled"]), "subject": row["subject"] or defaults["subject"], "bodyText": row["body_text"] or ""}


def email_logs(conn: sqlite3.Connection, query: str = "", message_type: str = "", status: str = "", limit: int = 50) -> list[sqlite3.Row]:
    conditions = []
    params: list[Any] = []
    if query.strip():
        conditions.append("lower(recipient_email) LIKE ?")
        params.append(f"%{query.strip().lower()}%")
    if message_type.strip():
        conditions.append("message_type = ?")
        params.append(message_type.strip())
    if status.strip():
        conditions.append("status = ?")
        params.append(status.strip())
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    params.append(limit)
    return list(conn.execute(f"SELECT * FROM email_send_logs {where} ORDER BY created_at DESC, id DESC LIMIT ?", params).fetchall())

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


def _build_message(config: EmailConfig, payload: EmailPayload) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = payload.subject
    message["From"] = formataddr((config.from_name, config.from_email))
    message["To"] = payload.to_email
    if config.reply_to_email:
        message["Reply-To"] = config.reply_to_email
    message.set_content(payload.text_body)
    message.add_alternative(payload.html_body, subtype="html")
    return message


def _send_via_yandex(config: EmailConfig, payload: EmailPayload, send_message: bool = True) -> None:
    if config.provider != "yandex":
        raise ValueError("Поддерживается только email-provider yandex.")
    if not config.smtp_username or not config.smtp_password or not config.from_email:
        raise ValueError("Не заполнены SMTP username, password/app password или from email.")

    message = _build_message(config, payload)
    if config.use_ssl:
        with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=15) as smtp:
            smtp.login(config.smtp_username, config.smtp_password)
            if send_message:
                smtp.send_message(message)
        return

    with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=15) as smtp:
        if config.use_tls:
            smtp.starttls()
        smtp.login(config.smtp_username, config.smtp_password)
        if send_message:
            smtp.send_message(message)


def send_email(conn: sqlite3.Connection, settings: Settings, payload: EmailPayload) -> bool:
    config = resolve_email_config(conn, settings)
    template = _template_for(conn, payload.message_type)
    effective_payload = payload
    if template["subject"]:
        effective_payload = EmailPayload(payload.message_type, payload.to_email, template["subject"], payload.text_body, payload.html_body)
    if not template["enabled"]:
        _log_email(conn, effective_payload, config.provider, "skipped", "email template disabled")
        return False
    if not config.enabled:
        _log_email(conn, effective_payload, config.provider, "skipped", "email service disabled")
        return False
    try:
        _send_via_yandex(config, effective_payload)
    except Exception as exc:
        _log_email(conn, effective_payload, config.provider, "failed", str(exc))
        return False
    _log_email(conn, effective_payload, config.provider, "sent")
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


def create_email_verification_token(conn: sqlite3.Connection, account_id: int) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires_at = _now() + timedelta(hours=EMAIL_CONFIRMATION_TTL_HOURS)
    conn.execute(
        """
        INSERT INTO customer_email_verification_tokens (customer_account_id, token_hash, expires_at)
        VALUES (?, ?, ?)
        """,
        (account_id, _token_hash(token), _iso(expires_at)),
    )
    conn.commit()
    return token, expires_at


def send_email_confirmation(conn: sqlite3.Connection, settings: Settings, account: sqlite3.Row) -> bool:
    token, expires_at = create_email_verification_token(conn, int(account["id"]))
    expires_at_msk = format_moscow_datetime(expires_at)
    link = f"{_base_url(settings)}/account/verify-email?token={quote(token)}"
    text = (
        "Подтвердите e-mail для личного кабинета Stamm Brewing.\n\n"
        f"Ссылка действует {EMAIL_CONFIRMATION_TTL_HOURS} часов и используется один раз. Действует до {expires_at_msk}:\n{link}"
    )
    html = _render_shell(
        "Подтверждение e-mail",
        f"<p>Подтвердите e-mail для личного кабинета Stamm Brewing.</p>{_button(link, 'Подтвердить e-mail')}"
        f"<p>Ссылка действует {EMAIL_CONFIRMATION_TTL_HOURS} часов и используется один раз. Действует до {escape(expires_at_msk)}.</p>",
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
    expires_at = _now() + timedelta(hours=PASSWORD_RESET_TTL_HOURS)
    expires_at_msk = format_moscow_datetime(expires_at)
    conn.execute(
        """
        INSERT INTO customer_password_reset_tokens (customer_account_id, token_hash, expires_at)
        VALUES (?, ?, ?)
        """,
        (account["id"], _token_hash(token), _iso(expires_at)),
    )
    conn.commit()
    link = f"{_base_url(settings)}/account/password-reset/confirm?token={quote(token)}"
    text = (
        "Вы запросили восстановление пароля Stamm Brewing.\n\n"
        f"Ссылка действует {PASSWORD_RESET_TTL_HOURS} час и используется один раз. Действует до {expires_at_msk}:\n{link}\n\n"
        "Если вы не запрашивали сброс пароля, просто игнорируйте письмо."
    )
    html = _render_shell(
        "Восстановление пароля",
        f"<p>Вы запросили восстановление пароля Stamm Brewing.</p>{_button(link, 'Сбросить пароль')}"
        f"<p>Ссылка действует {PASSWORD_RESET_TTL_HOURS} час и используется один раз. Действует до {escape(expires_at_msk)}.</p>"
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
    order_date = format_moscow_datetime(order_date)
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


def test_email_connection(conn: sqlite3.Connection, settings: Settings) -> EmailServiceResult:
    config = resolve_email_config(conn, settings)
    missing = email_service_status(conn, settings)["missing"]
    if missing:
        return EmailServiceResult(False, "Не заполнены параметры подключения: " + ", ".join(missing))
    probe = EmailPayload("test", config.from_email, "SMTP connection probe", "probe", "<p>probe</p>")
    try:
        _send_via_yandex(config, probe, send_message=False)
    except smtplib.SMTPAuthenticationError as exc:
        return EmailServiceResult(False, "Ошибка аутентификации SMTP.", str(exc))
    except (TimeoutError, OSError) as exc:
        return EmailServiceResult(False, "Ошибка соединения с SMTP-сервером.", str(exc))
    except Exception as exc:
        return EmailServiceResult(False, "Проверка подключения завершилась ошибкой.", str(exc))
    return EmailServiceResult(True, "Подключение к Яндекс SMTP успешно проверено.")


def send_test_email(conn: sqlite3.Connection, settings: Settings, to_email: str, message_type: str = "test") -> EmailServiceResult:
    recipient = normalize_email(to_email)
    if not recipient:
        return EmailServiceResult(False, "Укажите e-mail получателя тестового письма.")
    label = EMAIL_TEMPLATE_DEFAULTS.get(message_type, EMAIL_TEMPLATE_DEFAULTS["test"])["label"]
    html = _render_shell("Тест почты", f"<p>Это тестовое письмо сценария «{escape(label)}» из админки Stamm Brewing.</p>")
    payload = EmailPayload(message_type if message_type in EMAIL_TEMPLATE_DEFAULTS else "test", recipient, "Тест почты · Stamm Brewing", f"Тестовое письмо: {label}", html)
    if send_email(conn, settings, payload):
        return EmailServiceResult(True, "Тестовое письмо отправлено.")
    return EmailServiceResult(False, "Тестовое письмо не отправлено. Проверьте статус и логи отправки.")


def _customer_by_ref(conn: sqlite3.Connection, customer_ref: str) -> sqlite3.Row | None:
    ref = str(customer_ref or "").strip()
    if not ref:
        return None
    if ref.isdigit():
        return conn.execute("SELECT * FROM customer_accounts WHERE id = ?", (int(ref),)).fetchone()
    return conn.execute("SELECT * FROM customer_accounts WHERE lower(email) = lower(?)", (normalize_email(ref),)).fetchone()


def send_email_confirmation_for_customer(conn: sqlite3.Connection, settings: Settings, customer_ref: str) -> EmailServiceResult:
    account = _customer_by_ref(conn, customer_ref)
    if account is None:
        return EmailServiceResult(False, "Пользователь не найден.")
    if account["status"] != "active":
        return EmailServiceResult(False, "Письмо подтверждения можно отправить только активному пользователю.")
    ok = send_email_confirmation(conn, settings, account)
    return EmailServiceResult(ok, "Письмо подтверждения отправлено." if ok else "Письмо подтверждения не отправлено. Проверьте логи.")


def send_password_reset_for_customer(conn: sqlite3.Connection, settings: Settings, customer_ref: str) -> EmailServiceResult:
    account = _customer_by_ref(conn, customer_ref)
    if account is None:
        return EmailServiceResult(False, "Пользователь не найден.")
    if account["status"] != "active":
        return EmailServiceResult(False, "Ссылку восстановления можно отправить только активному пользователю.")
    ok = send_password_reset(conn, settings, account["email"])
    return EmailServiceResult(ok, "Ссылка восстановления пароля отправлена." if ok else "Ссылка восстановления не отправлена. Проверьте логи.")


def send_order_created_for_order(conn: sqlite3.Connection, settings: Settings, order_id: int) -> EmailServiceResult:
    order = conn.execute("SELECT * FROM b2b_orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        return EmailServiceResult(False, "Заказ не найден.")
    customer = None
    if "customer_account_id" in order.keys() and order["customer_account_id"]:
        customer = conn.execute("SELECT * FROM customer_accounts WHERE id = ?", (order["customer_account_id"],)).fetchone()
    if customer is None:
        customer = conn.execute("SELECT * FROM customer_accounts WHERE lower(email) = lower(?)", (order["email"],)).fetchone()
    if customer is None:
        return EmailServiceResult(False, "У заказа нет связанного пользователя для отправки письма.")
    rows = conn.execute("SELECT * FROM b2b_order_items WHERE order_id = ? ORDER BY id", (order_id,)).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        try:
            snapshot = json.loads(row["product_snapshot_json"] or "{}")
        except Exception:
            snapshot = {}
        item = {
            "name": snapshot.get("name") or f"SKU #{row['product_id']}",
            "price": {"amountMinor": row["price_minor"] or 0},
        }
        items.append({"item": item, "quantity": int(row["quantity"] or 0), "lineTotalMinor": row["line_total_minor"] or 0})
    ok = send_order_created(
        conn,
        settings,
        customer,
        order["number"],
        order["created_at"],
        items,
        int(order["total_minor"] or 0),
        order["comment"] or "",
    )
    return EmailServiceResult(ok, "Письмо по заказу отправлено." if ok else "Письмо по заказу не отправлено. Проверьте логи.")
