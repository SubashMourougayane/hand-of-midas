# Adversarial Battery — Verdict Table

Tested: 5 configs × 6 stress dimensions = 30 test families.

## Verdict per config (PASS / DECAY / FAIL)

```
         config  baseline_PF  baseline_MAR  baseline_$PnL  delay+1_PF_pct  delay+5_PF_pct  delay+10_PF_pct  cost_$0.50_PF  cost_$1.50_PF  OOS/IS_PF_ratio OOS_verdict  P(net<0)_pct pos_years
     A_best_MAR        2.054        10.070       475568.0           108.5           121.4            139.0              0              0             1.04        PASS           0.0 21.0/21.0
 B_tight_regime        2.194         9.142       413092.0           102.8           110.4            123.7              0              0             1.16        PASS           0.0 21.0/21.0
  C_high_volume        1.910         8.540       594552.0           106.5           118.4            141.6              0              0             1.09        PASS           0.0 21.0/21.0
    D_short_leg        1.851         6.647       683827.0           102.5           118.5            130.5              0              0             0.96        PASS           0.0 21.0/21.0
E_dollar_leader        1.924         6.192       983678.0           101.6           108.8            121.1              0              0             1.09        PASS           0.0 21.0/21.0
```