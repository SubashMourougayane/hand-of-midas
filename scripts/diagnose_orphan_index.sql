-- Diagnose the orphan-adopt-failed cascade on Oil Micro (June 10).
-- Determines whether the partial unique index on oanda_trade_id exists,
-- whether ON CONFLICT (oanda_trade_id) can match it, and whether the
-- specific orphan ticket 2034232555 has any DB row at all.

-- 1) Unique partial index on oanda_trade_id
SELECT indexname, indexdef FROM pg_indexes
WHERE tablename = 'gd_trades' AND indexname LIKE '%oanda%';

-- 2) All indexes on gd_trades
SELECT indexname, indexdef FROM pg_indexes
WHERE tablename = 'gd_trades' ORDER BY indexname;

-- 3) Unique / primary key constraints on gd_trades
SELECT conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'gd_trades'::regclass AND contype IN ('u', 'p');

-- 4) Confirm key column widths
SELECT column_name, data_type, character_maximum_length
FROM information_schema.columns
WHERE table_name = 'gd_trades'
  AND column_name IN ('strategy', 'oanda_trade_id', 'trade_ref');

-- 5) Does the orphan broker ticket 2034232555 exist as a DB row?
SELECT trade_ref, strategy, oanda_trade_id, entry_time, exit_time, exit_reason, pnl_usd
FROM gd_trades WHERE oanda_trade_id = '2034232555';
