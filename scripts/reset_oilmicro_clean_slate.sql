-- =============================================================================
-- OIL MICRO CLEAN SLATE RESET — June 10, 2026
-- =============================================================================
-- Purpose: Wipe Oil Micro DB state to match a fresh JustMarkets account top-up.
-- Forensic record of the 7 orphans is preserved in:
--   docs/JUNE10_OIL_4ORPHANS_INVESTIGATION.md
--   docs/PRODUCTION_FIX_PLAN_ORPHAN_TRADES.md
--
-- Safety:
--   - Affects ONLY Oil Micro data (TRADE_REF_PREFIX 'OIL-MI-' + DD_STATE_ID=4)
--   - Does NOT touch Gold Macro, Gold Micro, or Oil Macro tables/state
--   - Atomic — rolls back if any statement fails
--   - Verification queries at the end will confirm scope
--
-- Run order on VPS:
--   1. STOP all 4 services first (any open MT5 positions must be closed manually)
--   2. Top up JM wallet to $10,000 USD via web UI
--   3. Run this SQL: psql golddigger -f scripts\reset_oilmicro_clean_slate.sql
--   4. Verify the verification queries print expected results
--   5. Pull latest code (Phase 2 hardening must be deployed before restart)
--   6. Start services with .\scripts\start-win.bat
-- =============================================================================

BEGIN;

-- 1) Capture pre-reset counts for verification (printed via NOTICE)
DO $$
DECLARE
  trades_count INT;
  signals_count INT;
  journal_count INT;
  open_count INT;
BEGIN
  SELECT COUNT(*) INTO trades_count FROM gd_trades WHERE trade_ref LIKE 'OIL-MI-%';
  SELECT COUNT(*) INTO signals_count FROM gd_signals WHERE strategy = 'micro_alpha_sweep_oil';
  SELECT COUNT(*) INTO journal_count FROM gd_journal
    WHERE trade_ref LIKE 'OIL-MI-%' OR strategy = 'micro_alpha_sweep_oil';
  SELECT COUNT(*) INTO open_count FROM gd_trades
    WHERE trade_ref LIKE 'OIL-MI-%' AND exit_time IS NULL;

  RAISE NOTICE 'PRE-RESET STATE: % trades (% open), % signals, % journal events',
               trades_count, open_count, signals_count, journal_count;
END $$;

-- 2) Delete Oil Micro data (scoped by trade_ref prefix and strategy name)
DELETE FROM gd_journal
  WHERE trade_ref LIKE 'OIL-MI-%' OR strategy = 'micro_alpha_sweep_oil';

DELETE FROM gd_signals
  WHERE strategy = 'micro_alpha_sweep_oil';

DELETE FROM gd_trades
  WHERE trade_ref LIKE 'OIL-MI-%';

-- 3) Reset Oil Micro DD state (id=4) to fresh $10K baseline
UPDATE gd_dd_state
SET
  consecutive_losses = 0,
  pause_counter = 0,
  equity = 10000,
  peak_equity = 10000,
  updated_at = NOW()
WHERE id = 4;

-- If somehow the row doesn't exist, create it
INSERT INTO gd_dd_state (id, consecutive_losses, pause_counter, equity, peak_equity, updated_at)
VALUES (4, 0, 0, 10000, 10000, NOW())
ON CONFLICT (id) DO NOTHING;

-- 4) Log the reset event in the journal so we have an audit trail of WHEN we reset
INSERT INTO gd_journal (trade_ref, strategy, event_type, price, context, timestamp)
VALUES (
  'SYSTEM',
  'micro_alpha_sweep_oil',
  'CLEAN_SLATE_RESET',
  NULL,
  '{"reason": "post_orphan_bug_recovery", "wallet_topup_usd": 10000, "deleted_orphan_count": 7, "see_doc": "docs/JUNE10_OIL_4ORPHANS_INVESTIGATION.md"}'::jsonb,
  NOW()
);

COMMIT;

-- =============================================================================
-- VERIFICATION QUERIES — confirm clean state after reset
-- =============================================================================

-- Q1: Should return 0 (no Oil Micro trades remain)
SELECT COUNT(*) AS oil_micro_trades_remaining
FROM gd_trades
WHERE trade_ref LIKE 'OIL-MI-%';

-- Q2: Should return 0 (no Oil Micro signals remain)
SELECT COUNT(*) AS oil_micro_signals_remaining
FROM gd_signals
WHERE strategy = 'micro_alpha_sweep_oil';

-- Q3: Should return 1 row — the CLEAN_SLATE_RESET event we just inserted
SELECT trade_ref, event_type, timestamp, context
FROM gd_journal
WHERE trade_ref LIKE 'OIL-MI-%' OR strategy = 'micro_alpha_sweep_oil'
ORDER BY timestamp DESC
LIMIT 5;

-- Q4: Oil Micro DD state should show $10,000 baseline
SELECT id, consecutive_losses, pause_counter, equity, peak_equity, updated_at
FROM gd_dd_state
WHERE id = 4;

-- Q5: Confirm OTHER systems are UNTOUCHED — should still show their existing data
SELECT
  (SELECT COUNT(*) FROM gd_trades WHERE trade_ref LIKE 'GD-AL-%') AS gold_macro_trades,
  (SELECT COUNT(*) FROM gd_trades WHERE trade_ref LIKE 'GD-MI-%') AS gold_micro_trades,
  (SELECT COUNT(*) FROM gd_trades WHERE trade_ref LIKE 'OIL-AS-%') AS oil_macro_trades;

-- Q6: All DD states (id=1 Gold Macro, id=2 Oil Macro, id=3 Gold Micro, id=4 Oil Micro)
SELECT id, equity, peak_equity, consecutive_losses, pause_counter
FROM gd_dd_state
ORDER BY id;
