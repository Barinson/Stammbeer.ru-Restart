ALTER TABLE b2b_orders ADD COLUMN customer_account_id INTEGER REFERENCES customer_accounts(id) ON DELETE SET NULL;
ALTER TABLE b2b_orders ADD COLUMN counterparty_href TEXT;
ALTER TABLE b2b_orders ADD COLUMN external_order_id TEXT;
ALTER TABLE b2b_orders ADD COLUMN external_order_href TEXT;
ALTER TABLE b2b_orders ADD COLUMN external_status TEXT;
ALTER TABLE b2b_orders ADD COLUMN error_message TEXT;
