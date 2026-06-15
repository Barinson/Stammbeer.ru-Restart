CREATE TABLE IF NOT EXISTS customer_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    inn TEXT NOT NULL,
    counterparty_id TEXT NOT NULL,
    counterparty_href TEXT NOT NULL,
    counterparty_name TEXT NOT NULL,
    counterparty_meta_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active',
    last_login_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_customer_accounts_inn ON customer_accounts(inn);

CREATE TABLE IF NOT EXISTS customer_sessions (
    id TEXT PRIMARY KEY,
    customer_account_id INTEGER NOT NULL REFERENCES customer_accounts(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
