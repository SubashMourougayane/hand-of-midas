# Setup test database and run all tests
# Run: powershell -ExecutionPolicy Bypass -File scripts\setup-test-db.ps1

$psql = "C:\Program Files\PostgreSQL\17\bin\psql.exe"
$password = "postgres"
$env:PGPASSWORD = $password

Write-Host "=== Setting up test database ===" -ForegroundColor Cyan

# Drop and recreate test DB
& $psql -U postgres -c "DROP DATABASE IF EXISTS golddigger_test;" 2>&1 | Out-Null
& $psql -U postgres -c "CREATE DATABASE golddigger_test;" 2>&1 | Out-Null
Write-Host "  Created golddigger_test" -ForegroundColor Green

# Create all tables directly (avoid the \c switch in schema.sql)
$sql = @"
CREATE TABLE IF NOT EXISTS gd_backtest_runs (
    id SERIAL PRIMARY KEY, strategies TEXT[], total_trades INTEGER, wins INTEGER, losses INTEGER,
    win_rate NUMERIC, profit_factor NUMERIC, total_pnl NUMERIC, max_drawdown_pct NUMERIC,
    capital NUMERIC, risk_pct NUMERIC, start_date TEXT, end_date TEXT,
    is_latest BOOLEAN DEFAULT TRUE, created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS gd_backtest_trades (
    id SERIAL PRIMARY KEY, run_id INTEGER, trade_index INTEGER, date TEXT, year INTEGER, month INTEGER,
    strategy TEXT, direction TEXT, entry NUMERIC, sl NUMERIC, tp NUMERIC, exit_price NUMERIC,
    pnl_unit NUMERIC, pnl_sized NUMERIC, units NUMERIC, status TEXT, bars_held INTEGER,
    hold_human TEXT, risk NUMERIC, r_mult NUMERIC, equity_after NUMERIC
);
CREATE INDEX IF NOT EXISTS idx_gd_bt_trades_run ON gd_backtest_trades(run_id);
CREATE INDEX IF NOT EXISTS idx_gd_bt_trades_strategy ON gd_backtest_trades(strategy);
CREATE INDEX IF NOT EXISTS idx_gd_bt_trades_date ON gd_backtest_trades(date);
CREATE TABLE IF NOT EXISTS gd_backtest_equity (
    id SERIAL PRIMARY KEY, run_id INTEGER, date TEXT, cumulative_pnl NUMERIC, equity NUMERIC
);
CREATE INDEX IF NOT EXISTS idx_gd_bt_equity_run ON gd_backtest_equity(run_id);
CREATE TABLE IF NOT EXISTS gd_trades (
    id SERIAL PRIMARY KEY, trade_ref TEXT, strategy TEXT, side TEXT,
    entry_time TIMESTAMPTZ, exit_time TIMESTAMPTZ, entry_price NUMERIC, exit_price NUMERIC,
    sl_price NUMERIC, tp_price NUMERIC, lot_size NUMERIC, units INTEGER,
    pnl_gbp NUMERIC, pnl_usd NUMERIC, exit_reason TEXT, mode TEXT, oanda_trade_id TEXT
);
CREATE TABLE IF NOT EXISTS gd_signals (
    id SERIAL PRIMARY KEY, timestamp TIMESTAMPTZ DEFAULT NOW(), strategy TEXT, direction TEXT,
    entry_price NUMERIC, sl_price NUMERIC, tp_price NUMERIC, taken BOOLEAN,
    skip_reason TEXT, trade_ref TEXT
);
CREATE TABLE IF NOT EXISTS gd_journal (
    id SERIAL PRIMARY KEY, timestamp TIMESTAMPTZ DEFAULT NOW(), trade_ref TEXT, strategy TEXT,
    event_type TEXT, price NUMERIC, context TEXT
);
CREATE INDEX IF NOT EXISTS idx_gd_journal_trade_ref ON gd_journal(trade_ref);
CREATE TABLE IF NOT EXISTS gd_dd_state (
    id INTEGER PRIMARY KEY, consecutive_losses INTEGER DEFAULT 0, pause_counter INTEGER DEFAULT 0,
    equity NUMERIC DEFAULT 5000, peak_equity NUMERIC DEFAULT 5000, updated_at TIMESTAMPTZ DEFAULT NOW()
);
INSERT INTO gd_dd_state (id, consecutive_losses, pause_counter, equity, peak_equity) VALUES (1, 0, 0, 5000, 5000) ON CONFLICT (id) DO NOTHING;
INSERT INTO gd_dd_state (id, consecutive_losses, pause_counter, equity, peak_equity) VALUES (2, 0, 0, 5000, 5000) ON CONFLICT (id) DO NOTHING;
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY, email TEXT UNIQUE, password_hash TEXT, created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS sessions (
    id SERIAL PRIMARY KEY, user_id INTEGER, token TEXT UNIQUE, expires_at TIMESTAMPTZ, created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS gd_settings (
    key TEXT PRIMARY KEY, value TEXT, updated_at TIMESTAMPTZ DEFAULT NOW()
);
"@

& $psql -U postgres -d golddigger_test -c $sql
Write-Host "  All tables created" -ForegroundColor Green

# Also ensure main DB has tables
& $psql -U postgres -c "CREATE DATABASE golddigger;" 2>&1 | Out-Null
& $psql -U postgres -d golddigger -c $sql 2>&1 | Out-Null
Write-Host "  Main DB (golddigger) verified" -ForegroundColor Green

Write-Host ""
Write-Host "=== Running ALL tests ===" -ForegroundColor Cyan
$env:TEST_DB_URL = "postgresql://postgres:postgres@localhost:5432/golddigger_test"
$env:DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/golddigger"
python -m pytest tests/ -v --tb=short
