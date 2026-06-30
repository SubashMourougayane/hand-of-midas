# DWX_Server.mq5 M15 Timeframe Patch

**File:** `/Users/subash/SUBASH/hand-of-midas/mql5/DWX_Server.mq5` (v2.15)
**Date:** 2026-07-01
**Objective:** Add M15 bar export to enable fib_v2_intraday_a / _d strategies (M15 base TF).

## Current state (v2.15)

EA exports 4 timeframes in `WriteBarData()` at line 485-493:

```mql5
void WriteBarData()
{
    for(int i = 0; i < g_numSymbols; i++)
    {
        WriteSymbolBars(g_symbols[i], PERIOD_M1, 5000, "M1");
        WriteSymbolBars(g_symbols[i], PERIOD_M3, 100, "M3");
        WriteSymbolBars(g_symbols[i], PERIOD_H1, 30, "H1");
        WriteSymbolBars(g_symbols[i], PERIOD_D1, 5, "D1");
    }
}
```

## Patch — add M15 export

Insert after the M3 line:

```mql5
        WriteSymbolBars(g_symbols[i], PERIOD_M15, 300, "M15");
```

Result:

```mql5
void WriteBarData()
{
    for(int i = 0; i < g_numSymbols; i++)
    {
        WriteSymbolBars(g_symbols[i], PERIOD_M1, 5000, "M1");
        WriteSymbolBars(g_symbols[i], PERIOD_M3, 100, "M3");
        WriteSymbolBars(g_symbols[i], PERIOD_M15, 300, "M15");   // NEW
        WriteSymbolBars(g_symbols[i], PERIOD_H1, 30, "H1");
        WriteSymbolBars(g_symbols[i], PERIOD_D1, 5, "D1");
    }
}
```

Bump version string (line 9):

```mql5
#property version   "2.16"
```

## Consumer side (bt_engine)

**No changes required.** Python side already supports M15:
- `bt_engine/data/timeframes.py::TIMEFRAMES` includes `"M15"`
- DWX bridge maps `"M15" → "M15"` filename suffix
- `Mt5LiveBarProvider` uses dynamic timeframe lookup

Python will read `bars_XAUUSD_ecn_M15.json` automatically on next engine restart.

## Deployment steps (operator)

1. **Edit** `/Users/subash/SUBASH/hand-of-midas/mql5/DWX_Server.mq5` in MetaEditor
   - Add line: `WriteSymbolBars(g_symbols[i], PERIOD_M15, 300, "M15");` after M3 call
   - Bump version `"2.15"` → `"2.16"` (line 9)
2. **Compile** (Ctrl+Shift+F9 in MetaEditor)
3. **Reload** Drag recompiled EA onto XAUUSD.ecn chart in MT5
4. **Verify** MT5 Experts tab shows:
   ```
   [DWX] Server started v2.16
   ```
5. **Check** Within 10 seconds, `bars_XAUUSD_ecn_M15.json` should appear in:
   ```
   ~/Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/users/user/AppData/Roaming/MetaQuotes/Terminal/Common/Files/DWX/
   ```

## Bar count rationale

- **M15: 300 bars** = ~5 calendar days of continuous trading (300 × 15min ÷ 24 / 60 ≈ 3.1 days)
- Provides enough warmup for `pivot_lb=3` (only need 7 M15 bars) + safety buffer
- Memory footprint: ~150 KB JSON per write cycle (tolerable on M3 + M15 dual emit)

## Verification (after deploy)

Run from Python to confirm M15 ingestion:

```bash
python3 -c "
from bt_engine.data.dwx_live_provider import Mt5LiveBarProvider
p = Mt5LiveBarProvider(symbol='XAUUSD.ecn', timeframe='M15')
print('latest M15 bar:', p.latest())
"
```

Expected: latest bar timestamp within 15 minutes of now, OHLC values present.

## Backout

If M15 export causes issues:
- Remove the inserted line
- Revert version to "2.15"
- Recompile + redeploy

No other production strategies depend on M15 (yet), so backout is safe.
