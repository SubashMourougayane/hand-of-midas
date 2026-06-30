# L99 Multi-Timeframe Supply/Demand Confluence Research

## Status

Research-only. Frozen base unchanged.

This branch tests whether the real supply/demand edge is not simply a single zone, but a **stacked price area**:

- M15/M30 intraday zone reclaim event.
- Same-direction intraday zones overlapping the event's zone during the prior 24h.
- Same-direction H1 zones overlapping the event's zone during the prior 96h.
- Outcome remains the existing 1R bracket after estimated XAUUSD cost.

## Feature Tables

| feature | value | events | unique_days | net_r | avg_r | win_rate | profit_factor | avg_cost_r | median_risk_units |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cost_bucket | <=0.03R | 4527 | 752 | 21.2927 | 0.0047 | 0.5112 | 1.0096 | 0.0191 | 15.4250 |
| same_dir_h1_overlap_30d | 1 | 2398 | 758 | -34.6348 | -0.0144 | 0.5329 | 0.9713 | 0.0805 | 4.4577 |
| stack_score_7d_30d_capped | 2 | 843 | 416 | -40.7112 | -0.0483 | 0.5196 | 0.9074 | 0.0826 | 4.2813 |
| stack_score_7d_30d_capped | 1 | 698 | 356 | -64.4051 | -0.0923 | 0.4957 | 0.8313 | 0.0847 | 4.3123 |
| stack_score_7d_30d_capped | 0 | 559 | 385 | -89.7380 | -0.1605 | 0.4615 | 0.7248 | 0.0850 | 4.2733 |
| same_dir_intraday_overlap_7d | 0 | 1046 | 685 | -124.2087 | -0.1187 | 0.4837 | 0.7882 | 0.0884 | 4.1113 |
| has_intraday_stack_7d | False | 1046 | 685 | -124.2087 | -0.1187 | 0.4837 | 0.7882 | 0.0884 | 4.1113 |
| stack_score_7d_30d_capped | 4-5 | 3222 | 1072 | -134.3681 | -0.0417 | 0.5205 | 0.9194 | 0.0835 | 4.3865 |
| same_dir_intraday_overlap_7d | 2 | 1744 | 750 | -147.2631 | -0.0844 | 0.5000 | 0.8440 | 0.0828 | 4.3791 |
| same_dir_intraday_overlap_7d | 1 | 1443 | 708 | -159.0558 | -0.1102 | 0.4886 | 0.8012 | 0.0874 | 4.2759 |
| spec_name | m30_3c_1p5atr | 2434 | 1356 | -165.6694 | -0.0681 | 0.4959 | 0.8717 | 0.0591 | 5.8694 |
| stack_score | 3 | 2044 | 930 | -167.6412 | -0.0820 | 0.5029 | 0.8479 | 0.0866 | 4.2200 |
| same_dir_h1_overlap_30d | 2 | 1986 | 669 | -167.6621 | -0.0844 | 0.4945 | 0.8433 | 0.0779 | 4.6124 |
| stack_score | 2 | 2273 | 1011 | -186.2997 | -0.0820 | 0.5011 | 0.8479 | 0.0846 | 4.2071 |
| stack_score | 4-5 | 3608 | 1261 | -189.9179 | -0.0526 | 0.5155 | 0.8995 | 0.0830 | 4.1863 |
| cost_bucket | 0.03-0.05R | 5160 | 1273 | -197.9380 | -0.0384 | 0.5008 | 0.9255 | 0.0401 | 7.4854 |
| stack_score | 1 | 2014 | 953 | -209.4463 | -0.1040 | 0.4926 | 0.8107 | 0.0895 | 4.0491 |
| stack_score | 0 | 1709 | 1043 | -217.8846 | -0.1275 | 0.4827 | 0.7743 | 0.0940 | 3.7333 |
| same_dir_h1_overlap_96h | 1 | 4623 | 1186 | -225.0600 | -0.0487 | 0.5144 | 0.9065 | 0.0782 | 4.5630 |
| same_dir_intraday_overlap_7d | 3 | 1999 | 856 | -252.6214 | -0.1264 | 0.4762 | 0.7752 | 0.0809 | 4.6243 |
| same_dir_h1_overlap_96h | 2 | 2857 | 832 | -278.1034 | -0.0973 | 0.4893 | 0.8223 | 0.0782 | 4.6483 |
| stack_score_7d_30d_capped | 3 | 2952 | 775 | -280.5189 | -0.0950 | 0.4936 | 0.8259 | 0.0800 | 4.3054 |
| same_dir_intraday_overlap_24h | 1 | 3241 | 1312 | -285.7869 | -0.0882 | 0.5005 | 0.8372 | 0.0890 | 3.9939 |
| spec_name | m30_2c_1atr | 6117 | 1761 | -287.8537 | -0.0471 | 0.5087 | 0.9094 | 0.0643 | 5.3724 |
| same_dir_intraday_overlap_24h | 2 | 3652 | 1303 | -289.6736 | -0.0793 | 0.5016 | 0.8526 | 0.0835 | 4.3564 |
| same_dir_intraday_overlap_24h | 0 | 2581 | 1331 | -289.9921 | -0.1124 | 0.4901 | 0.7978 | 0.0932 | 3.7586 |
| has_intraday_stack | False | 2581 | 1331 | -289.9921 | -0.1124 | 0.4901 | 0.7978 | 0.0932 | 3.7586 |
| cost_bucket | >0.20R | 1068 | 451 | -311.3384 | -0.2915 | 0.4841 | 0.5507 | 0.2616 | 1.2519 |
| same_dir_intraday_overlap_7d | 4-5 | 3619 | 1192 | -314.5575 | -0.0869 | 0.4982 | 0.8396 | 0.0818 | 4.2790 |
| same_dir_intraday_overlap_24h | 4-5 | 5682 | 1499 | -338.1603 | -0.0595 | 0.5102 | 0.8871 | 0.0793 | 4.4096 |
| same_dir_intraday_overlap_24h | 3 | 4136 | 1356 | -348.5124 | -0.0843 | 0.4969 | 0.8440 | 0.0788 | 4.5304 |
| spec_name | m15_3c_1p5atr | 5399 | 1700 | -403.0389 | -0.0747 | 0.5018 | 0.8603 | 0.0792 | 4.4306 |
| same_dir_intraday_overlap_24h | 6+ | 8378 | 1408 | -414.8374 | -0.0495 | 0.5095 | 0.9048 | 0.0690 | 5.1744 |
| same_dir_h1_overlap_30d | 0 | 4848 | 925 | -460.6791 | -0.0950 | 0.4940 | 0.8261 | 0.0814 | 4.3237 |
| has_h1_stack_30d | False | 4848 | 925 | -460.6791 | -0.0950 | 0.4940 | 0.8261 | 0.0814 | 4.3237 |

## Rule Validation

| universe | direction | rule | events | unique_days | net_r | avg_r | win_rate | profit_factor | avg_cost_r | median_risk_units | train_net_r | oos_net_r | positive_years | negative_years | robust_pass |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| m30_2c_1atr | all | stack_score_3plus_cost_le_0p03 | 1095 | 542 | 49.8868 | 0.0456 | 0.5333 | 1.0979 | 0.0188 | 15.9183 | 6.5521 | 43.3348 | 6 | 2 | False |
| all_specs | supply | stack_score_3plus_cost_le_0p03 | 1536 | 427 | 47.5288 | 0.0309 | 0.5234 | 1.0653 | 0.0194 | 15.1872 | 21.4575 | 26.0713 | 6 | 2 | False |
| all_specs | supply | h1_stack_cost_le_0p03 | 1219 | 359 | 43.7991 | 0.0359 | 0.5242 | 1.0761 | 0.0192 | 15.6616 | 8.4891 | 35.3100 | 6 | 2 | False |
| all_specs | all | intraday_stack_cost_le_0p03 | 4198 | 721 | 41.1359 | 0.0098 | 0.5143 | 1.0202 | 0.0191 | 15.4366 | -2.7699 | 43.9058 | 5 | 3 | False |
| all_specs | supply | intraday_stack_cost_le_0p03 | 1799 | 480 | 39.4195 | 0.0219 | 0.5192 | 1.0457 | 0.0195 | 15.1069 | 12.6182 | 26.8013 | 5 | 3 | False |
| m30_2c_1atr | all | intraday_stack_cost_le_0p03 | 1232 | 574 | 37.6688 | 0.0306 | 0.5244 | 1.0648 | 0.0189 | 15.7141 | -1.0216 | 38.6904 | 6 | 2 | False |
| all_specs | all | stack_score_3plus_cost_le_0p03 | 3691 | 690 | 34.3749 | 0.0093 | 0.5148 | 1.0192 | 0.0191 | 15.4527 | 5.5586 | 28.8164 | 5 | 3 | False |
| m30_2c_1atr | all | h1_stack_cost_le_0p03 | 852 | 472 | 32.6834 | 0.0384 | 0.5282 | 1.0817 | 0.0190 | 15.7818 | 2.6365 | 30.0469 | 6 | 2 | False |
| m30_2c_1atr | all | stack_7d_30d_score_3plus_cost_le_0p03 | 1204 | 572 | 30.2765 | 0.0251 | 0.5216 | 1.0530 | 0.0188 | 15.7766 | -3.0275 | 33.3040 | 5 | 3 | False |
| all_specs | supply | stack_7d_30d_score_3plus_cost_le_0p03 | 1796 | 472 | 29.9952 | 0.0167 | 0.5161 | 1.0346 | 0.0194 | 15.2211 | 15.0657 | 14.9295 | 5 | 3 | False |
| m30_2c_1atr | demand | stack_score_3plus_cost_le_0p03 | 626 | 406 | 26.4558 | 0.0423 | 0.5351 | 1.0902 | 0.0188 | 15.9114 | -4.7539 | 31.2098 | 6 | 2 | False |
| m30_2c_1atr | supply | h1_stack_cost_le_0p03 | 364 | 272 | 23.4510 | 0.0644 | 0.5357 | 1.1414 | 0.0189 | 16.0866 | 6.0555 | 17.3955 | 7 | 1 | False |
| m30_2c_1atr | supply | stack_score_3plus_cost_le_0p03 | 469 | 328 | 23.4310 | 0.0500 | 0.5309 | 1.1081 | 0.0188 | 15.9183 | 11.3060 | 12.1250 | 6 | 2 | False |
| m30_2c_1atr | demand | intraday_stack_cost_le_0p03 | 684 | 429 | 22.7556 | 0.0333 | 0.5278 | 1.0707 | 0.0188 | 15.9584 | -7.0951 | 29.8507 | 6 | 2 | False |
| m30_2c_1atr | demand | stack_7d_30d_score_3plus_cost_le_0p03 | 675 | 429 | 19.2863 | 0.0286 | 0.5259 | 1.0605 | 0.0188 | 15.9786 | -8.8416 | 28.1280 | 5 | 3 | False |
| m15_2c_1atr | supply | stack_score_3plus_cost_le_0p03 | 565 | 291 | 19.1498 | 0.0339 | 0.5257 | 1.0715 | 0.0200 | 14.4881 | 8.3494 | 10.8004 | 6 | 2 | False |
| m15_2c_1atr | supply | intraday_stack_cost_le_0p03 | 667 | 331 | 16.7313 | 0.0251 | 0.5217 | 1.0522 | 0.0200 | 14.4881 | 5.0441 | 11.6872 | 5 | 3 | False |
| m30_2c_1atr | supply | intraday_stack_cost_le_0p03 | 548 | 369 | 14.9132 | 0.0272 | 0.5201 | 1.0574 | 0.0191 | 15.5139 | 6.0735 | 8.8397 | 5 | 3 | False |
| m15_2c_1atr | supply | stack_7d_30d_score_3plus_cost_le_0p03 | 714 | 337 | 13.9796 | 0.0196 | 0.5182 | 1.0406 | 0.0199 | 14.5464 | 7.6009 | 6.3787 | 6 | 2 | False |
| m15_2c_1atr | supply | h1_stack_cost_le_0p03 | 459 | 248 | 13.1050 | 0.0286 | 0.5207 | 1.0597 | 0.0196 | 15.0454 | 2.3852 | 10.7198 | 5 | 3 | False |
| m30_2c_1atr | supply | stack_7d_30d_score_3plus_cost_le_0p03 | 529 | 357 | 10.9902 | 0.0208 | 0.5161 | 1.0435 | 0.0189 | 15.6734 | 5.8141 | 5.1761 | 5 | 3 | False |
| m30_2c_1atr | demand | h1_stack_cost_le_0p03 | 488 | 343 | 9.2324 | 0.0189 | 0.5225 | 1.0394 | 0.0191 | 15.4961 | -3.4190 | 12.6513 | 5 | 3 | False |
| m15_3c_1p5atr | supply | h1_stack_cost_le_0p03 | 210 | 160 | 5.1949 | 0.0247 | 0.5190 | 1.0523 | 0.0192 | 15.7196 | 1.1990 | 3.9958 | 6 | 2 | False |
| m15_3c_1p5atr | supply | intraday_stack_cost_le_0p03 | 346 | 246 | 3.9717 | 0.0115 | 0.5145 | 1.0238 | 0.0195 | 15.4802 | 1.7640 | 2.2077 | 4 | 4 | False |
| m30_3c_1p5atr | supply | intraday_stack_cost_le_0p03 | 238 | 206 | 3.8034 | 0.0160 | 0.5168 | 1.0328 | 0.0189 | 15.6429 | -0.2634 | 4.0668 | 4 | 4 | False |
| m15_3c_1p5atr | all | intraday_stack_cost_le_0p03 | 857 | 433 | 3.4549 | 0.0040 | 0.5111 | 1.0083 | 0.0189 | 15.7501 | 7.3160 | -3.8611 | 5 | 3 | False |
| m30_3c_1p5atr | supply | stack_score_3plus_cost_le_0p03 | 227 | 200 | 3.0144 | 0.0133 | 0.5154 | 1.0272 | 0.0189 | 15.6577 | -0.2634 | 3.2778 | 5 | 3 | False |
| m30_3c_1p5atr | supply | stack_7d_30d_score_3plus_cost_le_0p03 | 237 | 206 | 2.8210 | 0.0119 | 0.5148 | 1.0244 | 0.0189 | 15.6280 | -0.2634 | 3.0844 | 4 | 4 | False |
| m15_3c_1p5atr | supply | stack_7d_30d_score_3plus_cost_le_0p03 | 316 | 224 | 2.2045 | 0.0070 | 0.5127 | 1.0144 | 0.0194 | 15.4802 | 1.9141 | 0.2904 | 6 | 2 | False |
| m30_3c_1p5atr | supply | h1_stack_cost_le_0p03 | 186 | 167 | 2.0483 | 0.0110 | 0.5161 | 1.0225 | 0.0189 | 15.7619 | -1.1505 | 3.1988 | 4 | 4 | False |
| m15_3c_1p5atr | supply | stack_score_3plus_cost_le_0p03 | 275 | 204 | 1.9335 | 0.0070 | 0.5127 | 1.0146 | 0.0197 | 14.6300 | 2.0654 | -0.1320 | 6 | 2 | False |
| all_specs | demand | intraday_stack_cost_le_0p03 | 2399 | 574 | 1.7163 | 0.0007 | 0.5106 | 1.0015 | 0.0189 | 15.5947 | -15.3881 | 17.1045 | 4 | 4 | False |
| m15_2c_1atr | all | intraday_stack_cost_le_0p03 | 1539 | 515 | 0.6053 | 0.0004 | 0.5088 | 1.0008 | 0.0196 | 14.8097 | 0.3350 | 0.2703 | 3 | 5 | False |
| m30_3c_1p5atr | all | stack_score_3plus_cost_le_0p03 | 556 | 386 | -0.3268 | -0.0006 | 0.5126 | 0.9988 | 0.0187 | 15.7501 | -9.4086 | 9.0818 | 5 | 3 | False |
| m15_3c_1p5atr | demand | intraday_stack_cost_le_0p03 | 511 | 331 | -0.5168 | -0.0010 | 0.5088 | 0.9979 | 0.0185 | 16.0479 | 5.5520 | -6.0688 | 4 | 4 | False |

## Random Benchmark

| universe | direction | rule | events | rule_net_r | random_p05 | random_p50 | random_p95 | prob_random_ge_rule |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| m30_2c_1atr | all | stack_score_3plus_cost_le_0p03 | 1095 | 49.8868 | -100.0234 | -50.0790 | -2.0434 | 0.0000 |
| all_specs | supply | stack_score_3plus_cost_le_0p03 | 1536 | 47.5288 | -183.2757 | -121.1906 | -60.4345 | 0.0000 |
| all_specs | supply | h1_stack_cost_le_0p03 | 1219 | 43.7991 | -149.2853 | -95.9771 | -42.6173 | 0.0000 |
| all_specs | all | intraday_stack_cost_le_0p03 | 4198 | 41.1359 | -398.1283 | -297.8785 | -201.1562 | 0.0000 |
| all_specs | supply | intraday_stack_cost_le_0p03 | 1799 | 39.4195 | -208.2802 | -143.9449 | -77.8643 | 0.0000 |
| m30_2c_1atr | all | intraday_stack_cost_le_0p03 | 1232 | 37.6688 | -108.1414 | -56.6743 | -6.3198 | 0.0020 |
| all_specs | all | stack_score_3plus_cost_le_0p03 | 3691 | 34.3749 | -351.6206 | -260.0778 | -169.7513 | 0.0000 |
| m30_2c_1atr | all | h1_stack_cost_le_0p03 | 852 | 32.6834 | -84.8748 | -40.1135 | 6.2476 | 0.0030 |
| m30_2c_1atr | all | stack_7d_30d_score_3plus_cost_le_0p03 | 1204 | 30.2765 | -109.1093 | -57.4354 | -7.7985 | 0.0020 |
| all_specs | supply | stack_7d_30d_score_3plus_cost_le_0p03 | 1796 | 29.9952 | -207.6507 | -143.3613 | -80.7762 | 0.0000 |
| m30_2c_1atr | demand | stack_score_3plus_cost_le_0p03 | 626 | 26.4558 | -51.9848 | -14.9100 | 22.7622 | 0.0360 |
| m30_2c_1atr | supply | h1_stack_cost_le_0p03 | 364 | 23.4510 | -54.9345 | -25.7903 | 3.5991 | 0.0040 |
| m30_2c_1atr | supply | stack_score_3plus_cost_le_0p03 | 469 | 23.4310 | -65.8019 | -33.0687 | -0.8984 | 0.0010 |
| m30_2c_1atr | demand | intraday_stack_cost_le_0p03 | 684 | 22.7556 | -54.0867 | -16.1287 | 20.9342 | 0.0387 |
| m30_2c_1atr | demand | stack_7d_30d_score_3plus_cost_le_0p03 | 675 | 19.2863 | -55.2429 | -16.7367 | 22.0855 | 0.0647 |
| m15_2c_1atr | supply | stack_score_3plus_cost_le_0p03 | 565 | 19.1498 | -83.7979 | -46.2657 | -8.7960 | 0.0003 |
| m15_2c_1atr | supply | intraday_stack_cost_le_0p03 | 667 | 16.7313 | -97.5377 | -55.2191 | -13.8129 | 0.0040 |
| m30_2c_1atr | supply | intraday_stack_cost_le_0p03 | 548 | 14.9132 | -74.2374 | -40.1018 | -5.4926 | 0.0043 |
| m15_2c_1atr | supply | stack_7d_30d_score_3plus_cost_le_0p03 | 714 | 13.9796 | -98.7743 | -57.9961 | -16.1385 | 0.0017 |
| m15_2c_1atr | supply | h1_stack_cost_le_0p03 | 459 | 13.1050 | -71.0394 | -37.8803 | -4.8782 | 0.0063 |
| m30_2c_1atr | supply | stack_7d_30d_score_3plus_cost_le_0p03 | 529 | 10.9902 | -71.0850 | -38.0907 | -4.6558 | 0.0083 |
| m30_2c_1atr | demand | h1_stack_cost_le_0p03 | 488 | 9.2324 | -45.0626 | -11.8271 | 21.7966 | 0.1413 |
| m15_3c_1p5atr | supply | h1_stack_cost_le_0p03 | 210 | 5.1949 | -39.5247 | -16.1931 | 7.0021 | 0.0647 |
| m15_3c_1p5atr | supply | intraday_stack_cost_le_0p03 | 346 | 3.9717 | -56.1423 | -27.2470 | 1.8530 | 0.0407 |
| m30_3c_1p5atr | supply | intraday_stack_cost_le_0p03 | 238 | 3.8034 | -43.6492 | -21.2515 | 2.1412 | 0.0370 |

## Robust Passes

_No rows._

## Interpretation

A confluence rule is promotable only if it is positive in train and OOS, clears PF 1.15, has at least 150 trades, and is positive in at least 6 years.

If the best confluence rows are still thin, then the conclusion is severe but useful: price-area stacking is not enough by itself. The next research step should model path behavior after the tap: rejection speed, volume/ATR expansion after reclaim, and whether the zone becomes accepted or rejected after 15-60 minutes.

## Files

- `multitimeframe_sd_confluence_events.csv`
- `multitimeframe_sd_confluence_feature_tables.csv`
- `multitimeframe_sd_confluence_rule_validation.csv`
- `multitimeframe_sd_confluence_random_benchmark.csv`
- `multitimeframe_sd_confluence_summary.json`
