from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.integrations.moysklad.client import MoyskladClient
from app.integrations.moysklad.settings_service import decode_token, get_settings
from app.modules.auth.security import hash_password, new_session_id, verify_password

CUSTOMER_SESSION_COOKIE = "stamm_customer_session"
CUSTOMER_SESSION_DAYS = 14
DISCOUNT_CACHE_TTL_MINUTES = 15


@dataclass(frozen=True)
class RegistrationResult:
    ok: bool
    message: str
    account: sqlite3.Row | None = None


class DiscountRefreshError(RuntimeError):
    """Raised when login-time MoySklad discount refresh cannot complete."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def normalize_inn(inn: str) -> str:
    return re.sub(r"\D+", "", inn or "")


def validate_registration_form(inn: str, email: str, password: str, password_confirm: str) -> str | None:
    normalized_inn = normalize_inn(inn)
    if len(normalized_inn) not in {10, 12}:
        return "ИНН должен содержать 10 или 12 цифр."
    if "@" not in normalize_email(email):
        return "Введите корректный e-mail."
    if len(password) < 8:
        return "Пароль должен быть не короче 8 символов."
    if password != password_confirm:
        return "Пароль и подтверждение не совпадают."
    return None


def _account_by_email(conn: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM customer_accounts WHERE lower(email) = lower(?)", (normalize_email(email),)).fetchone()


def _account_by_id(conn: sqlite3.Connection, account_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM customer_accounts WHERE id = ?", (account_id,)).fetchone()


def _build_moysklad_client(conn: sqlite3.Connection) -> MoyskladClient:
    settings = get_settings(conn)
    token = decode_token(settings["encrypted_token"])
    if not token:
        raise RuntimeError("Не настроен токен МойСклад для проверки контрагентов.")
    return MoyskladClient(token=token, api_base_url=settings["api_base_url"])


def _discount_is_stale(account: sqlite3.Row) -> bool:
    synced_at = account["discount_synced_at"]
    if not synced_at:
        return True
    try:
        moment = datetime.fromisoformat(str(synced_at).replace("Z", "+00:00"))
    except ValueError:
        return True
    return utc_now() - moment > timedelta(minutes=DISCOUNT_CACHE_TTL_MINUTES)


def _save_counterparty_profile(conn: sqlite3.Connection, account_id: int, counterparty: dict[str, Any]) -> sqlite3.Row | None:
    discount_percent = float(counterparty.get("discountPercent") or 0)
    conn.execute(
        """
        UPDATE customer_accounts
        SET counterparty_id = ?, counterparty_href = ?, counterparty_name = ?, counterparty_meta_json = ?,
            discount_percent = ?, discount_synced_at = ?, discount_source_json = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            counterparty["id"],
            counterparty["href"],
            counterparty["name"],
            json.dumps(counterparty.get("meta") or {}, ensure_ascii=False),
            discount_percent,
            utc_now_iso(),
            json.dumps({"discounts": counterparty.get("discounts") or []}, ensure_ascii=False),
            account_id,
        ),
    )
    conn.commit()
    return _account_by_id(conn, account_id)


def refresh_customer_discount(conn: sqlite3.Connection, account: sqlite3.Row, force: bool = False) -> sqlite3.Row:
    if not force and not _discount_is_stale(account):
        return account
    try:
        client = _build_moysklad_client(conn)
        last_error: Exception | None = None
        counterparty = None
        try:
            counterparty = client.fetch_counterparty(account["counterparty_href"])
        except Exception as exc:
            last_error = exc
        if counterparty is None:
            try:
                counterparty = client.find_counterparty_by_inn(account["inn"])
            except Exception as exc:
                last_error = exc
        if counterparty is None:
            if force:
                raise DiscountRefreshError("Не удалось обновить скидку контрагента из МойСклад.") from last_error
            return account
        refreshed = _save_counterparty_profile(conn, account["id"], counterparty)
        return refreshed or account
    except DiscountRefreshError:
        raise
    except Exception as exc:
        if force:
            raise DiscountRefreshError("Не удалось обновить скидку контрагента из МойСклад.") from exc
        return account


def register_customer(conn: sqlite3.Connection, inn: str, email: str, password: str, password_confirm: str) -> RegistrationResult:
    validation_error = validate_registration_form(inn, email, password, password_confirm)
    if validation_error:
        return RegistrationResult(False, validation_error)

    normalized_email = normalize_email(email)
    normalized_inn = normalize_inn(inn)
    if _account_by_email(conn, normalized_email) is not None:
        return RegistrationResult(False, "Этот e-mail уже зарегистрирован.")

    try:
        counterparty = _build_moysklad_client(conn).find_counterparty_by_inn(normalized_inn)
    except Exception:
        return RegistrationResult(False, "МойСклад временно недоступен. Попробуйте зарегистрироваться позже.")

    if counterparty is None:
        return RegistrationResult(False, "Регистрация невозможна: контрагент с таким ИНН не найден в МойСклад.")

    cursor = conn.execute(
        """
        INSERT INTO customer_accounts (
            email, password_hash, inn, counterparty_id, counterparty_href,
            counterparty_name, counterparty_meta_json, discount_percent, discount_synced_at, discount_source_json, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
        """,
        (
            normalized_email,
            hash_password(password),
            normalized_inn,
            counterparty["id"],
            counterparty["href"],
            counterparty["name"],
            json.dumps(counterparty.get("meta") or {}, ensure_ascii=False),
            float(counterparty.get("discountPercent") or 0),
            utc_now_iso(),
            json.dumps({"discounts": counterparty.get("discounts") or []}, ensure_ascii=False),
        ),
    )
    conn.commit()
    account = _account_by_id(conn, int(cursor.lastrowid))
    return RegistrationResult(True, "Аккаунт создан и связан с контрагентом МойСклад.", account)


def authenticate_customer(conn: sqlite3.Connection, email: str, password: str, refresh_discount: bool = True) -> sqlite3.Row | None:
    account = _account_by_email(conn, email)
    if account is None or account["status"] != "active":
        return None
    if not verify_password(password, account["password_hash"]):
        return None
    conn.execute("UPDATE customer_accounts SET last_login_at = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (utc_now_iso(), account["id"]))
    conn.commit()
    refreshed = _account_by_id(conn, account["id"])
    if refreshed is None or not refresh_discount:
        return refreshed
    return refresh_customer_discount(conn, refreshed, force=True)


def create_customer_session(conn: sqlite3.Connection, account_id: int) -> str:
    session_id = new_session_id()
    expires_at = (utc_now() + timedelta(days=CUSTOMER_SESSION_DAYS)).isoformat().replace("+00:00", "Z")
    conn.execute(
        """
        INSERT INTO customer_sessions (id, customer_account_id, expires_at, last_seen_at)
        VALUES (?, ?, ?, ?)
        """,
        (session_id, account_id, expires_at, utc_now_iso()),
    )
    conn.commit()
    return session_id


def customer_session_from_cookie(cookie_header: str | None) -> str | None:
    if not cookie_header:
        return None
    for part in cookie_header.split(";"):
        name, _, value = part.strip().partition("=")
        if name == CUSTOMER_SESSION_COOKIE:
            return value or None
    return None


def current_customer(conn: sqlite3.Connection, cookie_header: str | None) -> sqlite3.Row | None:
    session_id = customer_session_from_cookie(cookie_header)
    if not session_id:
        return None
    row = conn.execute(
        """
        SELECT ca.*
        FROM customer_sessions cs
        JOIN customer_accounts ca ON ca.id = cs.customer_account_id
        WHERE cs.id = ? AND cs.expires_at > ? AND ca.status = 'active'
        """,
        (session_id, utc_now_iso()),
    ).fetchone()
    if row is not None:
        conn.execute("UPDATE customer_sessions SET last_seen_at = ? WHERE id = ?", (utc_now_iso(), session_id))
        conn.commit()
    return row


def destroy_customer_session(conn: sqlite3.Connection, session_id: str | None) -> None:
    if session_id:
        conn.execute("DELETE FROM customer_sessions WHERE id = ?", (session_id,))
        conn.commit()


def customer_cookie_header(session_id: str) -> str:
    max_age = CUSTOMER_SESSION_DAYS * 24 * 60 * 60
    return f"{CUSTOMER_SESSION_COOKIE}={session_id}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}"


def expired_customer_cookie_header() -> str:
    return f"{CUSTOMER_SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
