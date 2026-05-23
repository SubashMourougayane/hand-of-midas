# Learnings — Building a Trading Engine from Scratch

These are hard-won lessons from building Hand Of Midas (Gold + Oil algorithmic trading system). Pass this to any AI agent building a new trading engine.

---

## 1. FILLS — The #1 Source of Fake Results

- **NEVER use trailing stops in backtest** — trailing SL (e.g., EMA20 - 0.3×ATR) can set SL ABOVE current price after a crash. The backtest "fills" at that impossible price. This single bug inflated our old system's P&L by 89%.
- **Fixed SL/TP only** — place at entry, never modify (except break-even once).
- **TP fills on bar HIGH/LOW touch** (not close-through). This matches OANDA limit order behavior.
- **SL gap-through checked FIRST** — if bar opens past SL, fill at open (worst case). Then check TP. Then check SL touch. This order matters.
- **If both SL and TP touched same bar (no gap)** — TP wins. OANDA limit order fills before stop.
- **Entry uses ASK for longs, BID for shorts** — never use MID. Mid gives you a free half-spread (~$0.25 on Gold) that doesn't exist in live.
- **Slippage on SL fills** — add adverse slippage when SL is hit. No slippage on TP (limit fill).
- **Expired/max-hold exits use bar close** — but in live you'd call close_trade() which has spread. Add exit slippage in pessimistic tests.

---

## 2. BACKTEST vs LIVE PARITY

- **Shared fill model** — ONE file used by both backtest and live. Not "similar logic" — literally the same imported function.
- **Same entry formula** — if backtest uses `ask_close + slippage(bar_range)`, live MUST use the same. A $0.25 difference × 1000 trades = $250 systematic bias.
- **Same column names** — if CSV has `bid_high/ask_high`, live API returns same. Don't mix `mid` in one and `bid/ask` in the other.
- **Test parity explicitly** — pick 50 random days, run both backtest strategy AND live scheduler simulation, assert signals match within $0.05.
- **numpy types crash psycopg2-binary** — Anaconda's psycopg2 auto-adapts numpy. pip's doesn't. Always cast to `float()`/`int()` before DB writes.
- **Decimal from PostgreSQL ≠ float** — `dd_state["equity"]` returns `Decimal(5000.00)`. Adding a float crashes. Always `float(dd_state["equity"])`.

---

## 3. POSITION MANAGEMENT

- **One order per trade** — place market order with SL+TP attached. OANDA manages exits. You just monitor.
- **Position monitor every 60s** — compare DB (what you think is open) vs OANDA (what's actually open). If trade disappeared from OANDA → it closed (SL/TP hit).
- **Exit reason heuristic** — compare fill_price to SL/TP with tolerance (±$2 for Gold, ±$0.05 for Oil). If neither matches → "CLOSED" (manual or unknown).
- **Break-even: move SL once** — at 50% to TP, move SL to entry + small buffer. Never move again. Log success AND failure.
- **Max hold hard kill** — if trade exceeds N bars, force close. Don't let positions run forever on dead signals.
- **Race conditions** — position monitor and price stream can both detect same event. Use DB state (exit_time IS NULL) as single source of truth. Second detector sees exit_time already set → skips.

---

## 4. DD PROTECTION

- **Per-instrument, not portfolio-wide** — Gold having 5 losses shouldn't pause Oil. Separate DD state rows.
- **Consecutive losses counted on realized P&L > 0** — a $0.00 exit (break-even) counts as loss (P&L not > 0). Consider if this is desired.
- **Pause counter race condition** — if multiple threads call `_should_skip()` simultaneously, pause_counter can go negative. Use atomic DB operations or accept the edge case.
- **Equity MA check** — compare current equity vs rolling 20-trade average. But if < 20 trades exist, skip the check (don't compare against empty data).

---

## 5. OANDA SPECIFICS

- **Practice API is unreliable** — returns 522, empty responses, drops connections on weekends. All API calls need 30s timeout + 3x retry with exponential backoff.
- **GBP account → USD sizing** — fetch live GBP/USD rate for position sizing. Fallback to 1.33 if API fails (stale but won't crash).
- **Streaming API for break-even** — don't poll every 60s for BE detection. Use OANDA's streaming endpoint for tick-by-tick. 0ms latency vs 60s.
- **Stream disconnects** — will happen. Auto-reconnect in 3s. Log STREAM_DISCONNECTED to journal. Scheduler fallback checks BE every 60s as backup.
- **Market closed on weekends** — scheduler still fires crons. OANDA returns "tradeable: false" or stale prices. Handle gracefully, don't crash.

---

## 6. DATABASE

- **DB is truth, not memory** — every trade, signal, event persisted. No in-memory state that dies on restart.
- **gd_signals: log EVERY signal** — taken AND skipped. Skip reason is critical for debugging ("why didn't it trade today?").
- **gd_journal: event sourcing** — ENTRY_FILLED, EXIT_FILLED, BREAK_EVEN, SIGNAL_SKIPPED, ORDER_FAILED, STREAM_DISCONNECTED, CLOSE_FAILED. If it happened, it's in the journal.
- **Failure paths MUST log** — if `modify_stop_loss()` fails, log BREAK_EVEN_FAILED. If `close_trade()` fails, log CLOSE_FAILED. Silent failures are invisible bugs.
- **Full ISO timestamps (not just dates)** — journey chart needs exact bar time. DATE type strips hours. Use TEXT or TIMESTAMPTZ.
- **ON CONFLICT DO NOTHING** for idempotent operations — DD state init, user seed, etc.

---

## 7. FRONTEND

- **API_BASE must be environment-aware** — `localhost:5053` locally, `""` (relative) in production. Use `window.location.hostname === "localhost"` check.
- **useEffect dependencies** — if a page fetches data based on `instrument`, include `instrument` in the dependency array. In production `apiBase` is the same for both instruments (""), so `[apiBase]` won't re-trigger on instrument switch.
- **Auth redirect with `router.replace`** — not `router.push`. Push pollutes browser history → back button loops between /live and /login.
- **Don't render protected content while auth is loading** — show "Loading..." until token validation completes. Otherwise dashboard flashes for 100ms before redirect.
- **Optional chaining on API data** — OANDA can return empty/null when down. `state.account?.nav?.toLocaleString()` not `state.account.nav.toLocaleString()`.

---

## 8. DEPLOYMENT

- **t3.small needs swap for npm build** — 2GB RAM isn't enough. Create 2GB swap file before `npm run build`.
- **python3-venv not installed by default** — Ubuntu 22.04 needs `apt install python3-venv python3-dev libpq-dev`.
- **Nginx proxy_read_timeout** — backtest takes 60s+ to process 2M bars. Set to 300s for backtest endpoints.
- **Certbot needs DNS propagation** — add A record, wait 5-10 min, then run certbot. It validates via DNS lookup.
- **GitHub deploy key is per-repo** — one SSH key can't authenticate for multiple private repos. Generate separate keys per repo.
- **systemd services with EnvironmentFile** — put all secrets in .env, reference via `EnvironmentFile=/opt/app/.env` in service file.
- **Don't hardcode credentials** — use `os.getenv()` with `python-dotenv`. Even for demo accounts. Git history is forever.

---

## 9. TESTING

- **Mock at the usage site, not the source** — if `live_engine.py` does `from oanda_executor import place_market_order`, patch `live_engine.place_market_order` (for top-level imports) or use `monkeypatch.setattr`.
- **Test DB separate from prod** — `golddigger_test` with identical schema. Truncate between tests.
- **Patch DB connection in conftest** — `autouse=True` fixture that routes `backend.db.get_conn` to test DB.
- **Test failure paths, not just happy paths** — OANDA timeout, close failure, BE failure, zero equity, negative units. These are the bugs that cost money in production.
- **Parity test** — pick N random signal days, run both backtest strategy AND live scheduler logic, assert identical output. This is the definitive "will live match backtest?" test.

---

## 10. STRATEGY VALIDATION

- **Phantom fill check on every backtest** — for each trade, verify the exit bar's high/low actually reached the exit price. If not → phantom.
- **Walk-forward: split in half** — if first-half PF = 12 and second-half PF = 2, edge is decaying. Both halves should be similar.
- **Sensitivity test** — vary key thresholds ±50%. If PF drops from 8 to 0.5 on small changes, it's curve-fitted. If it stays 5+, it's robust.
- **Pessimistic test** — double slippage, add exit spread, fail 20% of break-evens, add entry penalty. If it still profits, the edge is real.
- **Year-by-year table** — look for concentration. If one year carries 80% of P&L, that's not a strategy — that's one lucky period.
- **R-multiple sanity** — TP set at 2× risk should give ~2R on TP exits. If you see 16R on a TP exit, something's wrong (min_sl adjusting risk denominator is legitimate, but investigate).
- **Monte Carlo is a one-time research tool** — run it once to validate, don't put it in the webapp. You'll never re-run it during live trading.

---

## 11. PROCESS

- **Define "done" before starting** — "fix the timeline" is not done. "Timeline shows IST with overlap visible and needle at correct position" is done.
- **Don't build features you'll remove** — Monte Carlo page (built → removed), PineScript (built → removed). Ask "will I use this weekly?" before building.
- **One real trade > 10,000 simulations** — at some point, stop testing and start trading. The market is the ultimate validator.
- **Commit frequently, push always** — if your laptop dies, is the code safe? Auto-deploy means every push is a backup.
- **Production bugs are different from local bugs** — psycopg2-binary vs Anaconda psycopg2, nginx timeouts, port-based routing that only works locally. Always test on actual server.
