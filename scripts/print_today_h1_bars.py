"""One-shot: print today's H1 bars + asia stats so we can manually check
whether any sweep qualifies under the live ALPHA_SWEEP rules."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from backend.execution.mt5_executor import get_candles
from backend.config import ALPHA_SWEEP

ASIA_START = 0
ASIA_END = 8

candles = get_candles(instrument="XAU_USD", granularity="H1", count=20, price="BA")
print(f"got {len(candles)} H1 bars\n")

today = datetime.now(timezone.utc).date()

asia_bars = []
scan_bars = []
for c in candles:
    ts = datetime.fromisoformat(c["timestamp"].replace("Z","+00:00"))
    mid_high = (c["bid_high"] + c["ask_high"]) / 2
    mid_low = (c["bid_low"] + c["ask_low"]) / 2
    mid_open = (c["bid_open"] + c["ask_open"]) / 2
    mid_close = (c["bid_close"] + c["ask_close"]) / 2
    c["mid_high"] = mid_high; c["mid_low"] = mid_low
    c["mid_open"] = mid_open; c["mid_close"] = mid_close
    c["ts_obj"] = ts
    if ts.date() == today and ASIA_START <= ts.hour < ASIA_END:
        asia_bars.append(c)
    if ts.date() == today and ts.hour >= ALPHA_SWEEP["scan_start"]:
        scan_bars.append(c)

if asia_bars:
    asia_high = max(c["mid_high"] for c in asia_bars)
    asia_low = min(c["mid_low"] for c in asia_bars)
    print(f"Asia range  high={asia_high:.2f} low={asia_low:.2f} range={asia_high-asia_low:.2f}")
    print(f"Sweep thresh: bullish<{asia_low-ALPHA_SWEEP['sweep_threshold']:.2f} bearish>{asia_high+ALPHA_SWEEP['sweep_threshold']:.2f}")
else:
    print("NO ASIA BARS YET")
    asia_high = asia_low = None

print(f"\nScan window bars (h>={ALPHA_SWEEP['scan_start']}):")
print(f"{'time':<22} {'O':>8} {'H':>8} {'L':>8} {'C':>8}  sweep?")
for c in scan_bars:
    ts = c["ts_obj"]
    sweep = ""
    if asia_high is not None:
        # bearish sweep: high > asia_high+thresh AND close < asia_high
        if c["mid_high"] > asia_high + ALPHA_SWEEP["sweep_threshold"] and c["mid_close"] < asia_high:
            sweep = "BEARISH SWEEP ✓"
        elif c["mid_low"] < asia_low - ALPHA_SWEEP["sweep_threshold"] and c["mid_close"] > asia_low:
            sweep = "BULLISH SWEEP ✓"
        else:
            # show which condition failed
            wick_above = c["mid_high"] - asia_high
            wick_below = asia_low - c["mid_low"]
            close_above = c["mid_close"] - asia_high
            close_below = asia_low - c["mid_close"]
            if wick_above > ALPHA_SWEEP["sweep_threshold"]:
                sweep = f"wick above {wick_above:.2f} but close still > asia_high (close-asia_high={close_above:+.2f})"
            elif wick_below > ALPHA_SWEEP["sweep_threshold"]:
                sweep = f"wick below {wick_below:.2f} but close still < asia_low (close-asia_low={close_below:+.2f})"
    print(f"{str(ts):<22} {c['mid_open']:>8.2f} {c['mid_high']:>8.2f} {c['mid_low']:>8.2f} {c['mid_close']:>8.2f}  {sweep}")
