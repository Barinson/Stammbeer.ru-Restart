ALTER TABLE customer_accounts ADD COLUMN price_type_id TEXT;
ALTER TABLE customer_accounts ADD COLUMN price_type_href TEXT;
ALTER TABLE customer_accounts ADD COLUMN price_type_name TEXT;
ALTER TABLE customer_accounts ADD COLUMN price_type_meta_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE products ADD COLUMN price_type_prices_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE business_catalog_items ADD COLUMN price_type_prices_json TEXT NOT NULL DEFAULT '{}';
