-- bt_engine reference schema (kept in sync with alembic/versions/0001_initial_schema.py)

CREATE TABLE IF NOT EXISTS bt_runs (
  run_id          UUID PRIMARY KEY,
  ref             TEXT UNIQUE NOT NULL,
  mode            TEXT NOT NULL,
  strategy_id     TEXT NOT NULL,
  strategy_config JSONB NOT NULL,
  symbol          TEXT NOT NULL,
  timeframe       TEXT NOT NULL,
  start_ts        TIMESTAMPTZ NOT NULL,
  end_ts          TIMESTAMPTZ,
  data_provider   TEXT NOT NULL,
  git_sha         TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bt_trades (
  trade_id            UUID PRIMARY KEY,
  trade_ref           TEXT UNIQUE NOT NULL,
  run_id              UUID NOT NULL REFERENCES bt_runs(run_id) ON DELETE CASCADE,
  strategy_id         TEXT NOT NULL,
  symbol              TEXT NOT NULL,
  timeframe           TEXT NOT NULL,
  zone_id             INT,
  zone_tf             TEXT,
  spec_name           TEXT,
  direction           TEXT NOT NULL,
  side                INT NOT NULL,
  upper               DOUBLE PRECISION,
  lower               DOUBLE PRECISION,
  created_timestamp   TIMESTAMPTZ,
  base_timestamp      TIMESTAMPTZ,
  impulse_start_ts    TIMESTAMPTZ,
  impulse_end_ts      TIMESTAMPTZ,
  touch_timestamp     TIMESTAMPTZ,
  confirm_timestamp   TIMESTAMPTZ,
  entry_timestamp     TIMESTAMPTZ NOT NULL,
  entry_price         DOUBLE PRECISION NOT NULL,
  stop_price          DOUBLE PRECISION NOT NULL,
  take_profit_price   DOUBLE PRECISION,
  risk_units          DOUBLE PRECISION NOT NULL,
  exit_timestamp      TIMESTAMPTZ,
  exit_price          DOUBLE PRECISION,
  exit_reason         TEXT,
  bars_held           INT,
  bracket_1r_outcome  DOUBLE PRECISION,
  cost_r              DOUBLE PRECISION,
  gross_r             DOUBLE PRECISION,
  net_r               DOUBLE PRECISION,
  confluence_score    DOUBLE PRECISION,
  clean_top3_rank     INT,
  pivot_lb            INT,
  regime              TEXT,
  ext_target_pct      DOUBLE PRECISION,
  sl_buffer_pct       DOUBLE PRECISION,
  fib_diff            DOUBLE PRECISION,
  regime_at_entry     TEXT,
  leg                 TEXT,
  raw_features        JSONB,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_bt_trades_run ON bt_trades(run_id);
CREATE INDEX IF NOT EXISTS idx_bt_trades_entry_ts ON bt_trades(entry_timestamp);

-- Fib V2 ENSEMBLE columns (migration 0002, idempotent ALTERs for existing installs).
ALTER TABLE bt_trades ADD COLUMN IF NOT EXISTS pivot_lb        INT;
ALTER TABLE bt_trades ADD COLUMN IF NOT EXISTS regime          TEXT;
ALTER TABLE bt_trades ADD COLUMN IF NOT EXISTS ext_target_pct  DOUBLE PRECISION;
ALTER TABLE bt_trades ADD COLUMN IF NOT EXISTS sl_buffer_pct   DOUBLE PRECISION;
ALTER TABLE bt_trades ADD COLUMN IF NOT EXISTS fib_diff        DOUBLE PRECISION;
ALTER TABLE bt_trades ADD COLUMN IF NOT EXISTS regime_at_entry TEXT;
ALTER TABLE bt_trades ADD COLUMN IF NOT EXISTS leg             TEXT;

-- Partial-TP safety-net columns (migration 0003).
ALTER TABLE bt_trades ADD COLUMN IF NOT EXISTS partial_tp_at_r   DOUBLE PRECISION;
ALTER TABLE bt_trades ADD COLUMN IF NOT EXISTS partial_tp_pct    DOUBLE PRECISION;
ALTER TABLE bt_trades ADD COLUMN IF NOT EXISTS partial_taken     BOOLEAN;
ALTER TABLE bt_trades ADD COLUMN IF NOT EXISTS partial_r         DOUBLE PRECISION;
ALTER TABLE bt_trades ADD COLUMN IF NOT EXISTS partial_fill_price DOUBLE PRECISION;
ALTER TABLE bt_trades ADD COLUMN IF NOT EXISTS partial_fill_ts   TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS bt_journal_events (
  event_id    BIGSERIAL PRIMARY KEY,
  trade_id    UUID NOT NULL REFERENCES bt_trades(trade_id) ON DELETE CASCADE,
  run_id      UUID NOT NULL REFERENCES bt_runs(run_id) ON DELETE CASCADE,
  ts          TIMESTAMPTZ NOT NULL,
  event_type  TEXT NOT NULL,
  detail      JSONB NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_bt_journal_trade ON bt_journal_events(trade_id);
CREATE INDEX IF NOT EXISTS idx_bt_journal_ts ON bt_journal_events(ts);

CREATE TABLE IF NOT EXISTS bt_bar_walk (
  walk_id     BIGSERIAL PRIMARY KEY,
  trade_id    UUID NOT NULL REFERENCES bt_trades(trade_id) ON DELETE CASCADE,
  run_id      UUID NOT NULL REFERENCES bt_runs(run_id) ON DELETE CASCADE,
  bar_ts      TIMESTAMPTZ NOT NULL,
  phase       TEXT NOT NULL,
  open        DOUBLE PRECISION NOT NULL,
  high        DOUBLE PRECISION NOT NULL,
  low         DOUBLE PRECISION NOT NULL,
  close       DOUBLE PRECISION NOT NULL,
  volume      DOUBLE PRECISION,
  spread      DOUBLE PRECISION,
  distance_to_entry_r DOUBLE PRECISION,
  distance_to_stop_r  DOUBLE PRECISION,
  distance_to_tp_r    DOUBLE PRECISION,
  mfe_r        DOUBLE PRECISION,
  mae_r        DOUBLE PRECISION,
  unrealised_r DOUBLE PRECISION,
  UNIQUE(trade_id, bar_ts)
);
CREATE INDEX IF NOT EXISTS idx_bar_walk_trade_ts ON bt_bar_walk(trade_id, bar_ts);

CREATE TABLE IF NOT EXISTS bt_signals (
  signal_id   BIGSERIAL PRIMARY KEY,
  run_id      UUID NOT NULL REFERENCES bt_runs(run_id) ON DELETE CASCADE,
  ts          TIMESTAMPTZ NOT NULL,
  zone_id     INT,
  status      TEXT NOT NULL,
  reason      TEXT,
  detail      JSONB
);
CREATE INDEX IF NOT EXISTS idx_signals_run_ts ON bt_signals(run_id, ts);

CREATE TABLE IF NOT EXISTS bt_account_snapshot (
  snap_id     BIGSERIAL PRIMARY KEY,
  run_id      UUID NOT NULL REFERENCES bt_runs(run_id) ON DELETE CASCADE,
  ts          TIMESTAMPTZ NOT NULL,
  balance     DOUBLE PRECISION,
  equity      DOUBLE PRECISION,
  open_pnl    DOUBLE PRECISION,
  open_position INT,
  UNIQUE(run_id, ts)
);

-- ─── NOTIFY triggers for live dashboard (Option D) ───────────────────────────
-- Each table emits a NOTIFY on the channel matching its name after every INSERT.
-- Payload is small: {pk, run_id, ts, type/status} so we stay under the 8KB
-- pg_notify limit. Dashboard client refetches full row via REST.

CREATE OR REPLACE FUNCTION notify_bt_journal_event() RETURNS trigger AS $$
BEGIN
  PERFORM pg_notify('bt_journal_events', json_build_object(
    'event_id',   NEW.event_id,
    'trade_id',   NEW.trade_id,
    'run_id',     NEW.run_id,
    'ts',         NEW.ts,
    'event_type', NEW.event_type
  )::text);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_notify_bt_journal_event ON bt_journal_events;
CREATE TRIGGER trg_notify_bt_journal_event
  AFTER INSERT ON bt_journal_events
  FOR EACH ROW EXECUTE FUNCTION notify_bt_journal_event();

CREATE OR REPLACE FUNCTION notify_bt_signal() RETURNS trigger AS $$
BEGIN
  PERFORM pg_notify('bt_signals', json_build_object(
    'signal_id', NEW.signal_id,
    'run_id',    NEW.run_id,
    'ts',        NEW.ts,
    'status',    NEW.status,
    'zone_id',   NEW.zone_id,
    'reason',    NEW.reason
  )::text);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_notify_bt_signal ON bt_signals;
CREATE TRIGGER trg_notify_bt_signal
  AFTER INSERT ON bt_signals
  FOR EACH ROW EXECUTE FUNCTION notify_bt_signal();

CREATE OR REPLACE FUNCTION notify_bt_trade() RETURNS trigger AS $$
BEGIN
  PERFORM pg_notify('bt_trades', json_build_object(
    'trade_id',        NEW.trade_id,
    'run_id',          NEW.run_id,
    'entry_timestamp', NEW.entry_timestamp,
    'exit_timestamp',  NEW.exit_timestamp,
    'direction',       NEW.direction,
    'leg',             NEW.leg,
    'net_r',           NEW.net_r
  )::text);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_notify_bt_trade_insert ON bt_trades;
CREATE TRIGGER trg_notify_bt_trade_insert
  AFTER INSERT ON bt_trades
  FOR EACH ROW EXECUTE FUNCTION notify_bt_trade();

DROP TRIGGER IF EXISTS trg_notify_bt_trade_update ON bt_trades;
CREATE TRIGGER trg_notify_bt_trade_update
  AFTER UPDATE OF exit_timestamp, exit_price, exit_reason, net_r ON bt_trades
  FOR EACH ROW EXECUTE FUNCTION notify_bt_trade();

CREATE OR REPLACE FUNCTION notify_bt_account_snapshot() RETURNS trigger AS $$
BEGIN
  PERFORM pg_notify('bt_account_snapshot', json_build_object(
    'snap_id',       NEW.snap_id,
    'run_id',        NEW.run_id,
    'ts',            NEW.ts,
    'equity',        NEW.equity,
    'balance',       NEW.balance,
    'open_position', NEW.open_position
  )::text);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_notify_bt_account_snapshot ON bt_account_snapshot;
CREATE TRIGGER trg_notify_bt_account_snapshot
  AFTER INSERT ON bt_account_snapshot
  FOR EACH ROW EXECUTE FUNCTION notify_bt_account_snapshot();
