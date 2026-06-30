# Fib V2 — Mar-Apr-May 2026 Dashboard

Static HTML dashboard for the 240 trades across baseline + PTP+1R + PTP+2R variants on XAUUSD + EURUSD.

## Open

### Option 1 (easiest, no server)

Just double-click `index.html`. Tested in Chrome, Safari.

Some browsers (notably Firefox under strict policy) block `<script src>` paths from sibling folders under `file://`. If you see no data, use Option 2.

### Option 2 (local server, always works)

```bash
cd evidence/mar_apr_may_2026/dashboard
python3 -m http.server 8000
```

Then open http://localhost:8000 in any browser.

## Rebuilding the data

Source CSVs are in the parent directory `evidence/mar_apr_may_2026/`. After regenerating CSVs (via `bt_engine/scripts/analyze_mar_apr_may_2026.py`), re-emit the dashboard payloads:

```bash
python3 bt_engine/scripts/build_dashboard.py
```

This writes 5 `.js` files into `dashboard/data/`. The dashboard reads those via `<script src>` (no fetch, no CORS, no server required).

## Sections

1. **Headline cards** — 3 strategy variants side-by-side. Total trades, win rate, PF, R:R, net R, partial locked, outcome mix.
2. **Monthly performance** — grouped bar chart per variant × symbol. Toggle metric (net R / win rate / total trades).
3. **Outcome distribution** — 3 doughnut charts, one per variant. Shows mix of full TP / partial→TP / partial→BE / full SL / timeout.
4. **Daily heatmap** — calendar grid, rows = variant×symbol, columns = day, cell color = net R.
5. **Equity curve** — overlaid cumulative net R per variant.
6. **Trade table** — all 240 trades. Sortable, filterable. Click `Simulate ▶` to replay any trade bar-by-bar.
7. **R-distribution** — histogram of net R in 0.5R bins per variant.

## Simulator

Click `Simulate ▶` on any trade row → modal opens with:

- **Candlestick chart** showing actual M5 bars of the trade.
- **Horizontal fib levels** drawn from the engine's exact stored values:
  - fib_H (pivot high) — grey solid
  - fib_L (pivot low) — grey solid
  - fib_0.382 (entry zone top) — cyan dashed
  - fib_0.786 (entry zone bottom) — cyan dashed
  - fib_100 (invalidation) — grey dashed
  - Entry — yellow solid
  - SL — red solid
  - TP (1.618 extension) — green solid
  - Partial-TP trigger (PTP variants only) — orange dashed
- **Replay controls**: Play / Pause / Step / Reset / Speed slider (1×-60×).
- **Live readouts** that update per bar: timestamp, OHLC, running MFE, running MAE, unrealized R, distance to stop, distance to TP.
- **Event markers** appear during playback: entry arrow, partial-armed gold circle (the bar where MFE crossed the partial-TP trigger), exit marker (✓ TP / ✗ SL / BE / timeout).

Press `Esc` or click the dark overlay to close.

## Files

- `index.html` — page structure
- `app.js` — all UI logic (~750 lines vanilla JS)
- `style.css` — dark theme, layout
- `data/headline.js` — 3-row variant summary
- `data/monthly.js` — variant × symbol × month
- `data/daily.js` — variant × symbol × day
- `data/trades.js` — 240 trades with full fib metadata (~211 KB)
- `data/walks.js` — 86,476 bar-walks grouped by trade_id (~11 MB)
