-- =============================================================================
-- PHASE 3 SAFETY MIGRATION — Orphan Reconciler Support
-- =============================================================================
-- Adds the supporting DB structures the Phase 3 orphan reconciler relies on.
-- Idempotent — safe to run multiple times.
--
-- Run on VPS BEFORE deploying the Phase 3 code:
--   psql golddigger -f scripts\migration_phase3_orphan_safety.sql
-- =============================================================================

BEGIN;

-- 1) Unique partial index on oanda_trade_id
-- Why partial: oanda_trade_id can be NULL during the brief window between
-- order placement and trade_id assignment, and historical/test rows may
-- have NULL. Partial index allows multiple NULLs but enforces uniqueness
-- on real broker IDs — matching ON CONFLICT (oanda_trade_id) for the
-- reconciler's idempotent INSERT.
CREATE UNIQUE INDEX IF NOT EXISTS gd_trades_oanda_trade_id_uniq
  ON gd_trades(oanda_trade_id)
  WHERE oanda_trade_id IS NOT NULL;

-- 2) Index for orphan reconciler's hot lookup (open trades by trade_ref prefix)
-- The reconciler runs every 60s and queries open positions per system. This
-- index keeps that query <1ms even as trade history grows.
CREATE INDEX IF NOT EXISTS gd_trades_open_by_ref
  ON gd_trades(trade_ref, exit_time)
  WHERE exit_time IS NULL;

-- 3) Index for daily reconciliation report
-- The 00:00 UTC daily recon scans yesterday's trades; partial index on
-- entry_time::date keeps it fast.
CREATE INDEX IF NOT EXISTS gd_trades_entry_date
  ON gd_trades((entry_time::date));

-- 4) Index for journal queries by event_type (used in daily recon)
CREATE INDEX IF NOT EXISTS gd_journal_event_type_ts
  ON gd_journal(event_type, timestamp);

COMMIT;

-- =============================================================================
-- VERIFICATION
-- =============================================================================

SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'gd_trades' OR tablename = 'gd_journal'
ORDER BY tablename, indexname;
