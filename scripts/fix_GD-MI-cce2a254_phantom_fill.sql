-- =============================================================================
-- IMMEDIATE FIX — GD-MI-cce2a254 was misattributed as SL+$9, broker filled at TP+$910.80
-- =============================================================================
-- Bug: backend-micro/scanner/live_engine.py:338-344 fallback heuristic.
-- Both extremes['high'] >= sl_price (BE stop $4,204.36, hit early at $4,208.04)
-- AND extremes['low'] <= tp_price ($4,174.30, hit at $4,174.26 by $0.04).
-- Heuristic defaults to SL when both reach. Real broker filled at TP.
--
-- See: docs/BUG_PHANTOM_FILL_BE_AMBIGUITY.md
--
-- This script makes the DB match broker reality. The heuristic itself is fixed
-- in the proper Phase 4-B (DWX EA + closed_orders.json) — see followup commit.
-- =============================================================================

BEGIN;

-- 1) Correct the trade row
UPDATE gd_trades
SET
    exit_price  = 4174.30,
    pnl_usd     = 910.80,
    pnl_gbp     = 910.80,
    exit_reason = 'TP'
WHERE trade_ref = 'GD-MI-cce2a254';

-- 2) Update Gold Micro DD state (id=3): add the missing $901.80 to equity,
--    bump peak if needed, reset consecutive_losses (it was a win, not a loss).
UPDATE gd_dd_state
SET
    equity              = equity + (910.80 - 9.00),
    peak_equity         = GREATEST(peak_equity, equity + (910.80 - 9.00)),
    consecutive_losses  = 0,
    pause_counter       = 0,
    updated_at          = NOW()
WHERE id = 3;

-- 3) Audit trail
INSERT INTO gd_journal (trade_ref, strategy, event_type, price, context, timestamp)
VALUES (
    'GD-MI-cce2a254',
    'micro_alpha_sweep',
    'PNL_CORRECTED',
    4174.30,
    '{"reason": "phantom_fill_bug_be_ambiguity",
      "wrong": {"exit_price": 4204.36, "pnl_usd": 9.00, "exit_reason": "SL"},
      "correct": {"exit_price": 4174.30, "pnl_usd": 910.80, "exit_reason": "TP"},
      "delta_usd": 901.80,
      "see": "docs/BUG_PHANTOM_FILL_BE_AMBIGUITY.md"}'::jsonb,
    NOW()
);

COMMIT;

-- =============================================================================
-- VERIFICATION
-- =============================================================================

-- Q1: trade now shows TP @ $4,174.30 / +$910.80
SELECT trade_ref, side, entry_price, exit_price, pnl_usd, exit_reason
FROM gd_trades WHERE trade_ref = 'GD-MI-cce2a254';

-- Q2: Gold Micro DD state reflects the corrected equity
SELECT id, equity, peak_equity, consecutive_losses, pause_counter, updated_at
FROM gd_dd_state WHERE id = 3;

-- Q3: audit journal entry exists
SELECT timestamp, event_type, price, context
FROM gd_journal
WHERE trade_ref = 'GD-MI-cce2a254' AND event_type = 'PNL_CORRECTED';
