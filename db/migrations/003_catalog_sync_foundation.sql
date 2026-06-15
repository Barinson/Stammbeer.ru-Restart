ALTER TABLE products ADD COLUMN container_type TEXT;
ALTER TABLE products ADD COLUMN volume_liters REAL;
ALTER TABLE products ADD COLUMN price_minor INTEGER;
ALTER TABLE products ADD COLUMN currency TEXT DEFAULT 'RUB';
ALTER TABLE products ADD COLUMN stock_quantity REAL NOT NULL DEFAULT 0;
ALTER TABLE products ADD COLUMN availability_status TEXT NOT NULL DEFAULT 'unavailable';
ALTER TABLE products ADD COLUMN source_store_href TEXT;
ALTER TABLE products ADD COLUMN source_folder_href TEXT;
ALTER TABLE products ADD COLUMN sync_state TEXT NOT NULL DEFAULT 'active';
