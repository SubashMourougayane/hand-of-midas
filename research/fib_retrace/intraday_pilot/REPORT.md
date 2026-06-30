# Intraday Pilot Report — 12h Hard Cap

Test: re-walk Fib V2 ENSEMBLE signals with `max_hold_h=12h` hard cap.
Same SL/TP/regime/fib_382-786 entry zone. Only the time-stop tightens.

**Sizing**: $5,000 account, 1.5% risk per trade ($75).

## 12h cap results

```
               label    n  net_R  wins  WR_pct    PF   MAR pos_years  dollar_pnl  return_pct_total symbol base_tf ptp_mode  cap_hours  cost_usd
 XAU/M5/baseline/12h 3911  266.7  1720   43.98 1.148 0.214     14/21     20002.0             400.0    XAU      M5 baseline         12   0.30000
   XAU/M5/PTP+1R/12h 3911 1022.7  2072   52.98 1.686 2.143     20/21     76702.0            1534.0    XAU      M5   PTP+1R         12   0.30000
   XAU/M5/PTP+2R/12h 3911  921.3  1815   46.41 1.539 1.333     19/21     69097.0            1381.9    XAU      M5   PTP+2R         12   0.30000
XAU/M15/baseline/12h 3404  225.8  1525   44.80 1.146 0.214     15/21     16938.0             338.8    XAU     M15 baseline         12   0.30000
  XAU/M15/PTP+1R/12h 3404  933.4  1833   53.85 1.735 2.518     20/21     70003.0            1400.1    XAU     M15   PTP+1R         12   0.30000
  XAU/M15/PTP+2R/12h 3404  824.6  1609   47.27 1.564 1.180     19/21     61843.0            1236.9    XAU     M15   PTP+2R         12   0.30000
 EUR/M5/baseline/12h 3677   84.5  1627   44.25 1.063 0.114     13/22      6334.0             126.7    EUR      M5 baseline         12   0.00003
   EUR/M5/PTP+1R/12h 3677  595.6  1836   49.93 1.513 1.700     22/22     44670.0             893.4    EUR      M5   PTP+1R         12   0.00003
   EUR/M5/PTP+2R/12h 3677  445.5  1678   45.64 1.346 0.813     22/22     33410.0             668.2    EUR      M5   PTP+2R         12   0.00003
EUR/M15/baseline/12h 3596  385.7  1587   44.13 1.256 0.762     18/22     28927.0             578.5    EUR     M15 baseline         12   0.00003
  EUR/M15/PTP+1R/12h 3596 1163.5  1919   53.36 1.955 4.740     22/22     87262.0            1745.2    EUR     M15   PTP+1R         12   0.00003
  EUR/M15/PTP+2R/12h 3596 1017.0  1678   46.66 1.716 3.155     21/22     76276.0            1525.5    EUR     M15   PTP+2R         12   0.00003
```

## 72h reference (production)

```
              label    n  net_R  wins  WR_pct    PF   MAR pos_years  dollar_pnl  return_pct_total symbol    base_tf ptp_mode  cap_hours  cost_usd
XAU/M5/baseline/72h 4740  918.0  1499   31.62 1.276 0.376     17/21     68854.0            1377.1    XAU M5_72h_REF baseline         72   0.30000
  XAU/M5/PTP+1R/72h 4740 2203.7  2547   53.73 1.979 3.263     20/21    165278.0            3305.6    XAU M5_72h_REF   PTP+1R         72   0.30000
  XAU/M5/PTP+2R/72h 4740 2565.9  1921   40.53 1.889 2.248     20/21    192445.0            3848.9    XAU M5_72h_REF   PTP+2R         72   0.30000
EUR/M5/baseline/72h 4801  407.2  1694   35.28 1.140 0.180     17/22     30537.0             610.7    EUR M5_72h_REF baseline         72   0.00003
  EUR/M5/PTP+1R/72h 4801 1594.5  2537   52.84 1.747 1.687     21/22    119589.0            2391.8    EUR M5_72h_REF   PTP+1R         72   0.00003
  EUR/M5/PTP+2R/72h 4801 1667.4  1994   41.53 1.634 1.179     21/22    125054.0            2501.1    EUR M5_72h_REF   PTP+2R         72   0.00003
```

## Edge-survival check

- XAU/M5/baseline: 12h n=3911 net_R=+266.7 PF=1.15  vs  72h-M5 n=4740 net_R=+918.0 PF=1.28  (29% of net, 90% of PF)
- XAU/M5/PTP+1R: 12h n=3911 net_R=+1022.7 PF=1.69  vs  72h-M5 n=4740 net_R=+2203.7 PF=1.98  (46% of net, 85% of PF)
- XAU/M5/PTP+2R: 12h n=3911 net_R=+921.3 PF=1.54  vs  72h-M5 n=4740 net_R=+2565.9 PF=1.89  (36% of net, 81% of PF)
- XAU/M15/baseline: 12h n=3404 net_R=+225.8 PF=1.15  vs  72h-M5 n=4740 net_R=+918.0 PF=1.28  (25% of net, 90% of PF)
- XAU/M15/PTP+1R: 12h n=3404 net_R=+933.4 PF=1.74  vs  72h-M5 n=4740 net_R=+2203.7 PF=1.98  (42% of net, 88% of PF)
- XAU/M15/PTP+2R: 12h n=3404 net_R=+824.6 PF=1.56  vs  72h-M5 n=4740 net_R=+2565.9 PF=1.89  (32% of net, 83% of PF)
- EUR/M5/baseline: 12h n=3677 net_R=+84.5 PF=1.06  vs  72h-M5 n=4801 net_R=+407.2 PF=1.14  (21% of net, 93% of PF)
- EUR/M5/PTP+1R: 12h n=3677 net_R=+595.6 PF=1.51  vs  72h-M5 n=4801 net_R=+1594.5 PF=1.75  (37% of net, 87% of PF)
- EUR/M5/PTP+2R: 12h n=3677 net_R=+445.5 PF=1.35  vs  72h-M5 n=4801 net_R=+1667.4 PF=1.63  (27% of net, 82% of PF)
- EUR/M15/baseline: 12h n=3596 net_R=+385.7 PF=1.26  vs  72h-M5 n=4801 net_R=+407.2 PF=1.14  (95% of net, 110% of PF)
- EUR/M15/PTP+1R: 12h n=3596 net_R=+1163.5 PF=1.96  vs  72h-M5 n=4801 net_R=+1594.5 PF=1.75  (73% of net, 112% of PF)
- EUR/M15/PTP+2R: 12h n=3596 net_R=+1017.0 PF=1.72  vs  72h-M5 n=4801 net_R=+1667.4 PF=1.63  (61% of net, 105% of PF)

**Survived (≥80% PF kept):** XAU/M5/baseline, XAU/M5/PTP+1R, XAU/M5/PTP+2R, XAU/M15/baseline, XAU/M15/PTP+1R, XAU/M15/PTP+2R, EUR/M5/baseline, EUR/M5/PTP+1R, EUR/M5/PTP+2R, EUR/M15/baseline, EUR/M15/PTP+1R, EUR/M15/PTP+2R
**Died (<80% PF):** none

## Files
- `matrix.csv` — 12h cap, 2 symbols × 2 base TFs × 3 PTP modes
- `reference_72h.csv` — production 72h M5 for context