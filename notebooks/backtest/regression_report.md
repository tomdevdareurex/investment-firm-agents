# B5 regression re-run

## sma/sma200_regime_analysis.ipynb
status: **dry-run**

key figures unchanged

<details><summary>key lines after</summary>

    Reproduction, SMA200/monthly, 2007-03-15 -> 2026-10-19, cash=bil: CAGR 9.62%, Sharpe 0.69, max DD -25.8%, 1.5 switches/yr
    Backtest notebook (window sweep, same settings): CAGR 9.62%, Sharpe 0.69, max DD -25.8%, 1.5 switches/yr
    CAGR                             10.84%               10.28%                 10.35%                9.73%                  9.05%
    Sharpe                             0.52                 0.65                   0.65                 0.61                   0.52
    Switches                              0                   43                     43                   43                      0
    Switches / yr                      0.00                 1.31                   1.31                 1.31                   0.00
    CAGR                             11.15%                9.62%                  9.70%                9.31%                  9.24%
    Sharpe                             0.57                 0.69                   0.70                 0.67                   0.57
    Switches                              0                   29                     29                   29                      0
    Switches / yr                      0.00                 1.48                   1.48                 1.48                   0.00
    CAGR                                 11.05%               10.61%                 10.69%                9.41%                  8.93%
    Sharpe                                 0.51                 0.64                   0.65                 0.54                   0.51
    Switches                                  0                  139                    139                  139                      0
    Switches / yr                          0.00                 1.50                   1.50                 1.50                   0.00
    Sharpe decomposition: ln(SR_s/SR_bh) = ln(excess-return ratio) - ln(volatility ratio)   (approximate: Sharpe uses the volatility of excess returns)
    SPY: actual SMA200 Sharpe 0.76 vs placebo median 0.50 (B&H 0.60); share of placebos with Sharpe >= actual: p = 0.005
    S&P 500 long: actual SMA200 Sharpe 0.69 vs placebo median 0.44 (B&H 0.54); share of placebos with Sharpe >= actual: p = 0.000

</details>

## sma/sma_trend_backtest.ipynb
status: **dry-run**

key figures unchanged

<details><summary>key lines after</summary>

    CAGR                          10.92%                 10.99%         11.15%       2.39%
    Sharpe                          0.69                   0.70           0.53         NaN
    Max DD                       -25.41%                -25.18%        -55.42%      -0.00%
    Time in market 75.9% | switches 39 (1.2/yr) | cost drag 0.06%/yr

</details>

## timesfm/timesfm_forecast_backtest.ipynb
status: **dry-run**

key figures unchanged

<details><summary>key lines after</summary>

    Net of costs; Sharpe / Sortino on returns in excess of T-bills
    CAGR                        9.79%                    8.02%                 8.40%                      8.56%          9.77%        7.26%            5.94%          9.96%
    Sharpe                       0.50                     0.46                  0.46                       0.56           0.63         0.37             0.36           0.48
    Max DD                    -44.10%                  -32.05%               -42.27%                    -20.66%        -25.41%      -54.12%          -31.30%        -55.42%
    Switches                       47                       73                    33                         55             39           29              160              0
    Switches / yr                1.59                     2.47                  1.12                       1.86           1.32         0.98             5.41           0.00
    CAGR                  2.18%
    Sharpe                  NaN
    Max DD               -0.00%
    Switches                  0
    Switches / yr          0.00
    Sharpe by cost per switch (buy & hold 0.48)
    * Backtest (R1 TimesFM median, net): CAGR 9.79%, Sharpe 0.50, max DD -44.1%, 81% in market | buy & hold 9.96% / 0.48 / -55.4% | SMA200 9.77% / 0.63 / -25.4%.

</details>
