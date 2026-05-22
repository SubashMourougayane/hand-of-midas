-- GoldDigger Database Schema
-- Run: psql -U subash -d golddigger -f database/schema.sql

CREATE DATABASE golddigger;
\c golddigger;

-- Backtest runs (stores config + summary stats)
CREATE TABLE IF NOT EXISTS gd_backtest_runs (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    strategies TEXT[] NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    capital DECIMAL(12,2) NOT NULL,
    risk_pct DECIMAL(4,2) NOT NULL,
    total_trades INTEGER NOT NULL,
    wins INTEGER NOT NULL,
    losses INTEGER NOT NULL,
    win_rate DECIMAL(6,4) NOT NULL,
    profit_factor DECIMAL(8,4) NOT NULL,
    total_pnl DECIMAL(12,2) NOT NULL,
    max_drawdown_pct DECIMAL(6,2) NOT NULL,
    avg_win DECIMAL(10,2) NOT NULL,
    avg_loss DECIMAL(10,2) NOT NULL,
    risk_reward DECIMAL(6,2) NOT NULL,
    duration_ms INTEGER NOT NULL,
    is_latest BOOLEAN DEFAULT TRUE
);

-- Backtest trades (linked to a run)
CREATE TABLE IF NOT EXISTS gd_backtest_trades (
    id SERIAL PRIMARY KEY,
    run_id INTEGER REFERENCES gd_backtest_runs(id) ON DELETE CASCADE,
    trade_index INTEGER NOT NULL,
    date DATE NOT NULL,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    strategy VARCHAR(20) NOT NULL,
    direction VARCHAR(5) NOT NULL,
    entry DECIMAL(10,2) NOT NULL,
    sl DECIMAL(10,2) NOT NULL,
    tp DECIMAL(10,2) NOT NULL,
    exit_price DECIMAL(10,2) NOT NULL,
    pnl_unit DECIMAL(10,2) NOT NULL,
    pnl_sized DECIMAL(12,2) NOT NULL,
    units DECIMAL(8,2) NOT NULL,
    status VARCHAR(20) NOT NULL,
    bars_held INTEGER NOT NULL,
    hold_human VARCHAR(20) NOT NULL,
    risk DECIMAL(10,2) NOT NULL,
    r_mult DECIMAL(6,2) NOT NULL,
    equity_after DECIMAL(12,2) NOT NULL
);

CREATE INDEX idx_gd_bt_trades_run ON gd_backtest_trades(run_id);
CREATE INDEX idx_gd_bt_trades_strategy ON gd_backtest_trades(strategy);
CREATE INDEX idx_gd_bt_trades_date ON gd_backtest_trades(date);

-- Equity curve points (linked to a run)
CREATE TABLE IF NOT EXISTS gd_backtest_equity (
    id SERIAL PRIMARY KEY,
    run_id INTEGER REFERENCES gd_backtest_runs(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    cumulative_pnl DECIMAL(12,2) NOT NULL,
    equity DECIMAL(12,2) NOT NULL
);

CREATE INDEX idx_gd_bt_equity_run ON gd_backtest_equity(run_id);

-- Live trades (for Phase 5)
CREATE TABLE IF NOT EXISTS gd_trades (
    id SERIAL PRIMARY KEY,
    trade_ref VARCHAR(50) UNIQUE NOT NULL,
    strategy VARCHAR(20) NOT NULL,
    side VARCHAR(5) NOT NULL,
    entry_time TIMESTAMPTZ NOT NULL,
    exit_time TIMESTAMPTZ,
    entry_price DECIMAL(10,4) NOT NULL,
    exit_price DECIMAL(10,4),
    sl_price DECIMAL(10,4) NOT NULL,
    tp_price DECIMAL(10,4),
    lot_size DECIMAL(8,2) NOT NULL,
    units INTEGER NOT NULL,
    pnl_gbp DECIMAL(10,2),
    pnl_usd DECIMAL(10,2),
    exit_reason VARCHAR(30),
    mode VARCHAR(10) DEFAULT 'paper',
    oanda_trade_id VARCHAR(30),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Signals (every signal generated, taken or skipped)
CREATE TABLE IF NOT EXISTS gd_signals (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    strategy VARCHAR(20) NOT NULL,
    direction VARCHAR(5) NOT NULL,
    entry_price DECIMAL(10,4),
    sl_price DECIMAL(10,4),
    tp_price DECIMAL(10,4),
    taken BOOLEAN NOT NULL,
    skip_reason VARCHAR(100),
    trade_ref VARCHAR(50)
);

-- Journal events
CREATE TABLE IF NOT EXISTS gd_journal (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    trade_ref VARCHAR(50),
    strategy VARCHAR(20),
    event_type VARCHAR(30) NOT NULL,
    price DECIMAL(10,4),
    context JSONB
);

CREATE INDEX idx_gd_journal_trade_ref ON gd_journal(trade_ref);

-- DD protection state (persisted)
CREATE TABLE IF NOT EXISTS gd_dd_state (
    id INTEGER PRIMARY KEY DEFAULT 1,
    consecutive_losses INTEGER DEFAULT 0,
    pause_counter INTEGER DEFAULT 0,
    equity DECIMAL(12,2) DEFAULT 5000,
    peak_equity DECIMAL(12,2) DEFAULT 5000,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO gd_dd_state (id) VALUES (1) ON CONFLICT DO NOTHING;
INSERT INTO gd_dd_state (id) VALUES (2) ON CONFLICT DO NOTHING;  -- Oil DD state

-- Settings (key-value)
CREATE TABLE IF NOT EXISTS gd_settings (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
