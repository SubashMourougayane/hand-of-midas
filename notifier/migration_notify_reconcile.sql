-- Additive NOTIFY-trigger fix for the Telegram notifier (2026-07-06).
-- The reconciler stamps broker_net_usd + broker_reconciled_at in a separate UPDATE
-- that touches none of {exit_timestamp, exit_price, exit_reason, net_r}, so the
-- existing bt_trades UPDATE trigger never fired NOTIFY when the real $ landed.
-- Adding the two broker columns to the trigger's watch list broadcasts the
-- exact-$ moment, which the notifier's wait-for-exact-$ close alert consumes.
--
-- Idempotent + additive. Apply live with psql — no service restart, legs untouched:
--   psql "$BT_ENGINE_DB_URL" -f migration_notify_reconcile.sql

DROP TRIGGER IF EXISTS trg_notify_bt_trade_update ON bt_trades;
CREATE TRIGGER trg_notify_bt_trade_update
  AFTER UPDATE OF exit_timestamp, exit_price, exit_reason, net_r,
                  broker_net_usd, broker_reconciled_at ON bt_trades
  FOR EACH ROW EXECUTE FUNCTION notify_bt_trade();
