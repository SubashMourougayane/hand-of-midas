-- =============================================================================
-- ORPHAN TRADE BACKFILL — June 10, 2026
-- =============================================================================
-- Context: 7 BRENT SHORT trades placed by Oil Micro between 01:03 and 04:42 UTC
-- but never persisted to gd_trades / gd_signals / gd_journal due to
-- _log_journal exception in execute_signal path. All 7 closed manually by user.
--
-- Net realized P&L: +$345.86 (5 wins, 2 losses)
-- WARNING: First 4 trades (+$605) were directional luck. Last 3 (-$259) show
-- the bug now bleeding money — Oil Micro must be STOPPED until Phase 2 lands.
--
-- Source: JustMarkets web History tab (verified close times + P&L)
-- Close prices derived from entry +/- (pnl_raw / units), verified consistent.
--
-- Run order:
--   1. INSERT into gd_trades (7 rows, all with exit_time set)
--   2. INSERT into gd_journal (14 rows: ENTRY_FILLED + EXIT_MANUAL each)
--   3. UPDATE gd_dd_state (id=4 = Oil Micro: equity, peak, consecutive)
--   4. Verify with SELECT queries at the bottom
-- =============================================================================

BEGIN;

-- 1) gd_trades — 6 orphan trades, all closed
INSERT INTO gd_trades (
  trade_ref, strategy, side,
  entry_time, entry_price,
  exit_time, exit_price,
  sl_price, tp_price,
  lot_size, units, mode, oanda_trade_id,
  pnl_usd, pnl_gbp, exit_reason
) VALUES
  -- 4 trades from the first burst (01:03-02:27 UTC), all closed at 04:00 UTC
  ('OIL-MI-rec-303852', 'micro_alpha_sweep_oil', 'SHORT',
   '2026-06-10 01:03:00+00', 91.45,
   '2026-06-10 04:00:00+00', 91.20,
   92.55, 88.99,
   0.62, 620, 'live', '2031303852',
   151.28, 151.28, 'MANUAL_CLOSE'),

  ('OIL-MI-rec-324884', 'micro_alpha_sweep_oil', 'SHORT',
   '2026-06-10 01:06:00+00', 91.48,
   '2026-06-10 04:00:00+00', 91.20,
   92.55, 88.99,
   0.61, 610, 'live', '2031324884',
   167.14, 167.14, 'MANUAL_CLOSE'),

  ('OIL-MI-rec-450502', 'micro_alpha_sweep_oil', 'SHORT',
   '2026-06-10 01:45:00+00', 91.53,
   '2026-06-10 04:00:00+00', 91.20,
   92.55, 88.99,
   0.61, 610, 'live', '2031450502',
   197.64, 197.64, 'MANUAL_CLOSE'),

  ('OIL-MI-rec-569381', 'micro_alpha_sweep_oil', 'SHORT',
   '2026-06-10 02:27:00+00', 91.35,
   '2026-06-10 04:00:00+00', 91.20,
   92.55, 88.99,
   0.62, 620, 'live', '2031569381',
   89.28, 89.28, 'MANUAL_CLOSE'),

  -- 5th orphan (different setup, larger position, the only loser)
  ('OIL-MI-rec-871738', 'micro_alpha_sweep_oil', 'SHORT',
   '2026-06-10 04:03:00+00', 91.20,
   '2026-06-10 04:29:00+00', 91.38,
   91.78, 90.67,
   1.01, 1010, 'live', '2031871738',
   -187.86, -187.86, 'MANUAL_CLOSE'),

  -- 6th orphan (appeared after closing #5 — same bug fired again)
  ('OIL-MI-rec-942681', 'micro_alpha_sweep_oil', 'SHORT',
   '2026-06-10 04:30:00+00', 91.28,
   '2026-06-10 04:39:00+00', 91.24,
   91.78, 90.67,
   0.98, 980, 'live', '2031942681',
   33.32, 33.32, 'MANUAL_CLOSE'),

  -- 7th orphan (fired again after closing #6 — bug is on every cycle)
  ('OIL-MI-rec-975446', 'micro_alpha_sweep_oil', 'SHORT',
   '2026-06-10 04:42:00+00', 91.13,
   '2026-06-10 04:50:00+00', 91.23,
   91.78, 90.67,
   0.99, 990, 'live', '2031975446',
   -104.94, -104.94, 'MANUAL_CLOSE');

-- 2) gd_journal — audit trail for each trade (ENTRY_FILLED + EXIT_MANUAL)
INSERT INTO gd_journal (trade_ref, strategy, event_type, price, context, timestamp) VALUES
  -- Trade 1 (303852)
  ('OIL-MI-rec-303852', 'micro_alpha_sweep_oil', 'ENTRY_FILLED_RECOVERED', 91.45,
   '{"recovered": true, "broker_id": "2031303852", "side": "SHORT", "units": 620, "sl": 92.55, "tp": 88.99}'::jsonb,
   '2026-06-10 01:03:00+00'),
  ('OIL-MI-rec-303852', 'micro_alpha_sweep_oil', 'EXIT_MANUAL', 91.20,
   '{"recovered": true, "reason": "user_closed_orphan", "pnl_usd": 151.28, "broker_id": "2031303852"}'::jsonb,
   '2026-06-10 04:00:00+00'),

  -- Trade 2 (324884)
  ('OIL-MI-rec-324884', 'micro_alpha_sweep_oil', 'ENTRY_FILLED_RECOVERED', 91.48,
   '{"recovered": true, "broker_id": "2031324884", "side": "SHORT", "units": 610, "sl": 92.55, "tp": 88.99}'::jsonb,
   '2026-06-10 01:06:00+00'),
  ('OIL-MI-rec-324884', 'micro_alpha_sweep_oil', 'EXIT_MANUAL', 91.20,
   '{"recovered": true, "reason": "user_closed_orphan", "pnl_usd": 167.14, "broker_id": "2031324884"}'::jsonb,
   '2026-06-10 04:00:00+00'),

  -- Trade 3 (450502)
  ('OIL-MI-rec-450502', 'micro_alpha_sweep_oil', 'ENTRY_FILLED_RECOVERED', 91.53,
   '{"recovered": true, "broker_id": "2031450502", "side": "SHORT", "units": 610, "sl": 92.55, "tp": 88.99}'::jsonb,
   '2026-06-10 01:45:00+00'),
  ('OIL-MI-rec-450502', 'micro_alpha_sweep_oil', 'EXIT_MANUAL', 91.20,
   '{"recovered": true, "reason": "user_closed_orphan", "pnl_usd": 197.64, "broker_id": "2031450502"}'::jsonb,
   '2026-06-10 04:00:00+00'),

  -- Trade 4 (569381)
  ('OIL-MI-rec-569381', 'micro_alpha_sweep_oil', 'ENTRY_FILLED_RECOVERED', 91.35,
   '{"recovered": true, "broker_id": "2031569381", "side": "SHORT", "units": 620, "sl": 92.55, "tp": 88.99}'::jsonb,
   '2026-06-10 02:27:00+00'),
  ('OIL-MI-rec-569381', 'micro_alpha_sweep_oil', 'EXIT_MANUAL', 91.20,
   '{"recovered": true, "reason": "user_closed_orphan", "pnl_usd": 89.28, "broker_id": "2031569381"}'::jsonb,
   '2026-06-10 04:00:00+00'),

  -- Trade 5 (871738) — the loser
  ('OIL-MI-rec-871738', 'micro_alpha_sweep_oil', 'ENTRY_FILLED_RECOVERED', 91.20,
   '{"recovered": true, "broker_id": "2031871738", "side": "SHORT", "units": 1010, "sl": 91.78, "tp": 90.67}'::jsonb,
   '2026-06-10 04:03:00+00'),
  ('OIL-MI-rec-871738', 'micro_alpha_sweep_oil', 'EXIT_MANUAL', 91.38,
   '{"recovered": true, "reason": "user_closed_orphan", "pnl_usd": -187.86, "broker_id": "2031871738"}'::jsonb,
   '2026-06-10 04:29:00+00'),

  -- Trade 6 (942681) — fresh orphan after closing #5
  ('OIL-MI-rec-942681', 'micro_alpha_sweep_oil', 'ENTRY_FILLED_RECOVERED', 91.28,
   '{"recovered": true, "broker_id": "2031942681", "side": "SHORT", "units": 980, "sl": 91.78, "tp": 90.67}'::jsonb,
   '2026-06-10 04:30:00+00'),
  ('OIL-MI-rec-942681', 'micro_alpha_sweep_oil', 'EXIT_MANUAL', 91.24,
   '{"recovered": true, "reason": "user_closed_orphan", "pnl_usd": 33.32, "broker_id": "2031942681"}'::jsonb,
   '2026-06-10 04:39:00+00'),

  -- Trade 7 (975446) — fresh orphan after closing #6
  ('OIL-MI-rec-975446', 'micro_alpha_sweep_oil', 'ENTRY_FILLED_RECOVERED', 91.13,
   '{"recovered": true, "broker_id": "2031975446", "side": "SHORT", "units": 990, "sl": 91.78, "tp": 90.67}'::jsonb,
   '2026-06-10 04:42:00+00'),
  ('OIL-MI-rec-975446', 'micro_alpha_sweep_oil', 'EXIT_MANUAL', 91.23,
   '{"recovered": true, "reason": "user_closed_orphan", "pnl_usd": -104.94, "broker_id": "2031975446"}'::jsonb,
   '2026-06-10 04:50:00+00');

-- 3) gd_dd_state for Oil Micro (id=4)
-- Net realized: +$345.86 across 7 trades (5 wins, 2 losses)
-- Consecutive losses sequence: W, W, W, W, L, W, L → ends at 1 (last was a loss)
UPDATE gd_dd_state
SET
  consecutive_losses = 1,
  pause_counter = 0,
  equity = COALESCE(equity, 10000) + 345.86,
  peak_equity = GREATEST(COALESCE(peak_equity, 10000), COALESCE(equity, 10000) + 345.86),
  updated_at = NOW()
WHERE id = 4;

COMMIT;

-- =============================================================================
-- VERIFICATION QUERIES — run these after the COMMIT to confirm
-- =============================================================================

-- Q1: Should return 7 rows, all with exit_time set
SELECT trade_ref, side, entry_time AT TIME ZONE 'UTC' as entry_utc,
       exit_time AT TIME ZONE 'UTC' as exit_utc,
       entry_price, exit_price, pnl_usd, exit_reason
FROM gd_trades
WHERE trade_ref LIKE 'OIL-MI-rec-%'
ORDER BY entry_time;

-- Q2: Should return $345.86
SELECT ROUND(SUM(pnl_usd)::numeric, 2) as total_realized_pnl
FROM gd_trades
WHERE trade_ref LIKE 'OIL-MI-rec-%';

-- Q3: Should return 14 rows (7 ENTRY + 7 EXIT)
SELECT event_type, COUNT(*)
FROM gd_journal
WHERE trade_ref LIKE 'OIL-MI-rec-%'
GROUP BY event_type;

-- Q4: Oil Micro DD state should reflect new equity
SELECT id, consecutive_losses, pause_counter, equity, peak_equity, updated_at
FROM gd_dd_state
WHERE id = 4;

-- Q5: Should return 0 (no Oil Micro trades still open in DB)
SELECT COUNT(*) as still_open
FROM gd_trades
WHERE trade_ref LIKE 'OIL-MI-%' AND exit_time IS NULL;

-- Q6: Today's trade count (should be 7 after backfill — blocks more entries today)
SELECT COUNT(*) as oil_micro_trades_today
FROM gd_trades
WHERE trade_ref LIKE 'OIL-MI-%' AND entry_time::date = '2026-06-10';
