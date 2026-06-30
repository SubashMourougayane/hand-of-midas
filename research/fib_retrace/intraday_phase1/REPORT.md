# Phase 1 Intraday Sweep — Top 20 by MAR

Configs run: 10800, with n≥100 trades: 10800
Total wall time: 83.2 min

```
                                             cfg_id  lb  hold_h   ext  sl_buf   session      regime direction  ptp     n  net_R    PF    MAR  WR_pct pos_years  dollar_pnl  error
  lb3_h12_ext2.618_sl0.02_london_ny_any_long_ptp1.0   3      12 2.618    0.02 london_ny         any      long  1.0 13327 6340.9 2.054 10.070   56.75     21/21    475568.0    NaN
       lb5_h24_ext2.618_sl0.02_all_bull_long_ptp1.0   5      24 2.618    0.02       all        bull      long  1.0  9940 5507.9 2.194  9.142   56.85     21/21    413092.0    NaN
       lb5_h12_ext2.618_sl0.02_all_bull_long_ptp1.0   5      12 2.618    0.02       all        bull      long  1.0  9079 4157.1 2.028  8.758   56.31     21/21    311785.0    NaN
         lb3_h8_ext2.618_sl0.02_all_any_long_ptp1.0   3       8 2.618    0.02       all         any      long  1.0 19101 7927.4 1.910  8.540   55.35     21/21    594552.0    NaN
  lb3_h12_ext1.618_sl0.02_london_ny_any_long_ptp1.0   3      12 1.618    0.02 london_ny         any      long  1.0 13327 5741.5 1.955  8.444   56.81     21/21    430614.0    NaN
        lb5_h24_ext2.618_sl0.1_all_bull_long_ptp1.0   5      24 2.618    0.10       all        bull      long  1.0  9920 5036.6 2.101  8.385   56.23     20/21    377745.0    NaN
lb5_h24_ext2.618_sl0.02_all_bull_strong_long_ptp1.0   5      24 2.618    0.02       all bull_strong      long  1.0  9160 5047.3 2.182  8.378   56.59     17/21    378549.0    NaN
       lb5_h24_ext1.618_sl0.02_all_bull_long_ptp1.0   5      24 1.618    0.02       all        bull      long  1.0  9940 4948.2 2.073  8.194   56.88     21/21    371118.0    NaN
       lb5_h12_ext1.618_sl0.02_all_bull_long_ptp1.0   5      12 1.618    0.02       all        bull      long  1.0  9079 3878.2 1.959  8.170   56.33     21/21    290862.0    NaN
        lb3_h24_ext2.618_sl0.1_all_bull_long_ptp1.0   3      24 2.618    0.10       all        bull      long  1.0 14617 7482.5 2.093  8.021   56.76     20/21    561191.0    NaN
lb5_h12_ext2.618_sl0.02_all_bull_strong_long_ptp1.0   5      12 2.618    0.02       all bull_strong      long  1.0  8352 3756.1 2.004  7.913   56.05     18/21    281705.0    NaN
       lb3_h24_ext2.618_sl0.02_all_bull_long_ptp1.0   3      24 2.618    0.02       all        bull      long  1.0 14631 7971.9 2.146  7.828   56.67     20/21    597894.0    NaN
        lb5_h12_ext2.618_sl0.1_all_bull_long_ptp1.0   5      12 2.618    0.10       all        bull      long  1.0  9061 3852.4 1.980  7.807   55.99     21/21    288927.0    NaN
        lb3_h12_ext2.618_sl0.02_all_any_long_ptp1.0   3      12 2.618    0.02       all         any      long  1.0 20250 9033.6 1.960  7.757   56.05     21/21    677517.0    NaN
         lb3_h8_ext1.618_sl0.02_all_any_long_ptp1.0   3       8 1.618    0.02       all         any      long  1.0 19101 7303.5 1.839  7.675   55.42     21/21    547763.0    NaN
           lb3_h8_ext1.0_sl0.02_all_any_long_ptp1.0   3       8 1.000    0.02       all         any      long  1.0 19101 6586.5 1.757  7.660   55.54     21/21    493987.0    NaN
  lb5_h12_ext2.618_sl0.02_london_ny_any_long_ptp1.0   5      12 2.618    0.02 london_ny         any      long  1.0  9266 4116.4 1.995  7.645   55.68     21/21    308728.0    NaN
    lb3_h12_ext1.0_sl0.02_london_ny_any_long_ptp1.0   3      12 1.000    0.02 london_ny         any      long  1.0 13327 5191.3 1.864  7.557   56.85     21/21    389350.0    NaN
        lb5_h24_ext1.618_sl0.1_all_bull_long_ptp1.0   5      24 1.618    0.10       all        bull      long  1.0  9920 4519.1 1.988  7.524   56.25     20/21    338932.0    NaN
        lb3_h24_ext1.618_sl0.1_all_bull_long_ptp1.0   3      24 1.618    0.10       all        bull      long  1.0 14617 6701.7 1.979  7.488   56.85     20/21    502629.0    NaN
```

## Next steps

1. Cross-validate top 5-10 on EUR (Phase 2)
2. Adversarial battery (delay/cost-stress/walk-forward) on survivors (Phase 3)
3. M30/H1 pivot check (Phase 4)