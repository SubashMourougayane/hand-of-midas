-- Synthetic test: simulate exactly what reconcile_orphans() does, twice.
-- If Fix Y is working, both runs succeed (no error) and exactly 1 row remains.
-- If Fix Y is broken (the original bug), the SECOND run errors with 42P10.

-- Cleanup any prior test rows (idempotent)
DELETE FROM gd_trades WHERE oanda_trade_id LIKE 'TEST_FIXY_%';

-- First adoption (acts like first reconciler cycle finding the orphan)
INSERT INTO gd_trades (
    trade_ref, strategy, side, entry_time, entry_price,
    sl_price, tp_price, lot_size, units, mode, oanda_trade_id
)
VALUES (
    'OIL-MI-orphan-FIXYTEST', 'micro_alpha_sweep_oil', 'SHORT', NOW(),
    91.49, 92.40, 90.18, 0.63, 630, 'live', 'TEST_FIXY_2034232555'
)
ON CONFLICT (oanda_trade_id) WHERE oanda_trade_id IS NOT NULL DO NOTHING;

-- Second adoption (reconciler runs again 60s later — should be idempotent)
-- This is the call that produced 140 ORPHAN_ADOPT_FAILED today.
INSERT INTO gd_trades (
    trade_ref, strategy, side, entry_time, entry_price,
    sl_price, tp_price, lot_size, units, mode, oanda_trade_id
)
VALUES (
    'OIL-MI-orphan-FIXYTEST2', 'micro_alpha_sweep_oil', 'SHORT', NOW(),
    91.49, 92.40, 90.18, 0.63, 630, 'live', 'TEST_FIXY_2034232555'
)
ON CONFLICT (oanda_trade_id) WHERE oanda_trade_id IS NOT NULL DO NOTHING;

-- Proof: exactly ONE row exists with our test broker_id.
-- (If both INSERTs had succeeded, we'd see 2 rows — proves DO NOTHING worked.)
SELECT COUNT(*) AS row_count, MAX(trade_ref) AS first_inserted_ref
FROM gd_trades
WHERE oanda_trade_id = 'TEST_FIXY_2034232555';

-- Cleanup
DELETE FROM gd_trades WHERE oanda_trade_id LIKE 'TEST_FIXY_%';
