---
name: research-session-windows
description: "Research: Asia sweeping previous sessions tested — works but 7x weaker than current. Late night (20-24) loses money. NY-only is strongest WR."
metadata: 
  node_type: memory
  type: project
  originSessionId: 9b58418d-2726-44cc-8f57-287672e22ae5
---

## Session Window Research (May 26, 2026)

Tested all possible scan windows for Alpha-Sweep on Gold (Variant C, 21 years, production fill model).

### Results

| Window | Trades | WR | PF | $/yr |
|---|---|---|---|---|
| **CURRENT (08-20 London+NY)** | 1,203 | 62.7% | 3.15 | **+$6,908** |
| 08-22 (+2hr late NY) | 1,229 | 62.4% | 3.09 | +$6,911 |
| 08-24 (full post-Asia) | 1,251 | 61.8% | 3.01 | +$6,832 |
| 13-20 (NY only) | 782 | **67.6%** | **4.15** | +$5,008 |
| 08-13 (London only) | 446 | 53.1% | 2.16 | +$2,002 |
| 20-24 (late night) | 60 | 41.7% | 0.89 | **-$25** |
| Asia sweeps prev session range | 303 | 53.1% | 1.98 | +$941 |
| Asia+London sweeps prev NY range | 645 | 56.1% | 2.23 | +$2,526 |

### Key Findings

1. **Asia (00-08) cannot sweep its own range** — range is still building, nothing to sweep yet.
2. **Asia CAN sweep previous session** (ICT "Asian manipulation") — but PF 1.98, 53% WR, only $941/yr. 7x weaker than current approach. Not worth the complexity.
3. **Late night (20-24) LOSES money** — PF 0.89. Thin liquidity, no follow-through. Never extend past 20:00.
4. **NY session (13-20) is the strongest edge** — 67.6% WR, PF 4.15. The institutional flow drives reliable reversals.
5. **London (08-13) is weaker** — 53% WR. Sweeps happen but engulfing confirmation is less reliable.
6. **Extending to 22 or 24 adds almost nothing** — +26 trades for $62/yr. Not worth the risk.
7. **Current 08-20 is already optimal** — best balance of trade count and edge quality.

**Why:** London+NY sweeping Asia range works because that's when institutional money enters and deliberately runs overnight stops. Asia sweeping prev session is a slow drift, not a stop hunt — less conviction, less follow-through.

**How to apply:** Don't extend the scan window. Don't try Asia session trading. The edge is structurally tied to high-liquidity sessions hunting low-liquidity session ranges.
