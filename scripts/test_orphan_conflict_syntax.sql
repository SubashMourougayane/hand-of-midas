-- Verify the ON CONFLICT predicate syntax matches the partial unique index.
-- This INSERTs a synthetic broker_id, then re-INSERTs the same one to prove
-- the conflict path resolves (DO NOTHING) instead of erroring.

-- Use a sentinel broker_id so we can clean up after.
DELETE FROM gd_trades WHERE oanda_trade_id = 'TEST_SYNTAX_999999999';

-- First insert (should succeed)
INSERT INTO gd_trades (
    trade_ref, strategy, side, entry_time, entry_price,
    sl_price, tp_price, lot_size, units, mode, oanda_trade_id
)
VALUES (
    'TEST-SYNTAX-999', 'micro_alpha_sweep_oil', 'SHORT', NOW(), 91.49,
    92.40, 90.18, 0.63, 630, 'live', 'TEST_SYNTAX_999999999'
)
ON CONFLICT (oanda_trade_id) WHERE oanda_trade_id IS NOT NULL DO NOTHING;

-- Second insert (should hit conflict and DO NOTHING — no error)
INSERT INTO gd_trades (
    trade_ref, strategy, side, entry_time, entry_price,
    sl_price, tp_price, lot_size, units, mode, oanda_trade_id
)
VALUES (
    'TEST-SYNTAX-998', 'micro_alpha_sweep_oil', 'SHORT', NOW(), 91.49,
    92.40, 90.18, 0.63, 630, 'live', 'TEST_SYNTAX_999999999'
)
ON CONFLICT (oanda_trade_id) WHERE oanda_trade_id IS NOT NULL DO NOTHING;

-- Verify only ONE row exists (proves DO NOTHING path took effect)
SELECT COUNT(*) AS row_count, oanda_trade_id
FROM gd_trades
WHERE oanda_trade_id = 'TEST_SYNTAX_999999999'
GROUP BY oanda_trade_id;

-- Cleanup
DELETE FROM gd_trades WHERE oanda_trade_id = 'TEST_SYNTAX_999999999';
