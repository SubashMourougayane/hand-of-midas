-- =============================================================================
-- CLEANUP: 2 Gold Macro stale orphans from June 9
-- =============================================================================
-- These trades hit broker SL on June 9 19:18 IST but the position monitor
-- never updated their DB rows (the now-fixed missing import bug). They show
-- as 'open' in db_positions but are actually closed on JustMarkets.
--
-- Real close data from JustMarkets web (Jun 9 evening):
--   GD-AL-12c63d16: SHORT 29 @ $4,342.02 → SL $4,347.48, net -$160.37
--   GD-AL-b23ccc45: SHORT 31 @ $4,338.74 → SL $4,346.23, net -$234.36
-- Both closed at server 19:18 = real UTC 16:18 = IST 21:48
-- =============================================================================

BEGIN;

UPDATE gd_trades
SET
  exit_time = '2026-06-09 16:18:00+00:00',
  exit_price = 4347.48,
  pnl_usd = -160.37,
  pnl_gbp = -160.37,
  exit_reason = 'STOP_LOSS_RECOVERED'
WHERE trade_ref = 'GD-AL-12c63d16'
  AND exit_time IS NULL;

UPDATE gd_trades
SET
  exit_time = '2026-06-09 16:18:00+00:00',
  exit_price = 4346.23,
  pnl_usd = -234.36,
  pnl_gbp = -234.36,
  exit_reason = 'STOP_LOSS_RECOVERED'
WHERE trade_ref = 'GD-AL-b23ccc45'
  AND exit_time IS NULL;

-- Audit trail
INSERT INTO gd_journal (trade_ref, strategy, event_type, price, context, timestamp)
VALUES
  ('GD-AL-12c63d16', 'alpha_sweep', 'EXIT_RECOVERED', 4347.48,
   '{"reason": "manual_db_cleanup", "broker_close_time": "2026-06-09T16:18:00Z", "pnl_usd": -160.37}'::jsonb,
   NOW()),
  ('GD-AL-b23ccc45', 'alpha_sweep', 'EXIT_RECOVERED', 4346.23,
   '{"reason": "manual_db_cleanup", "broker_close_time": "2026-06-09T16:18:00Z", "pnl_usd": -234.36}'::jsonb,
   NOW());

COMMIT;

-- Verification
SELECT trade_ref, side, exit_time AT TIME ZONE 'UTC' AS exit_utc, exit_price, pnl_usd, exit_reason
FROM gd_trades
WHERE trade_ref IN ('GD-AL-12c63d16', 'GD-AL-b23ccc45');

-- Should return 0 (no Gold Macro positions remain "open" in DB)
SELECT COUNT(*) AS gold_macro_still_open
FROM gd_trades
WHERE trade_ref LIKE 'GD-AL-%' AND exit_time IS NULL;
