ALTER TABLE customer_accounts ADD COLUMN discount_percent REAL NOT NULL DEFAULT 0;
ALTER TABLE customer_accounts ADD COLUMN discount_synced_at TEXT;
ALTER TABLE customer_accounts ADD COLUMN discount_source_json TEXT NOT NULL DEFAULT '{}';
