# S02 Factor Blend (CORE)

> Research/backtest only. No live trading. No profitability is promised. Costs, slippage, spread (and S03 borrow) are modelled but real-world results will differ. If run on synthetic data, results are illustrative only and not based on market data.

**Data source:** loaded 18 symbols x 4119 bars (2010-01-04 -> 2026-05-19). If yfinance was unreachable this is SYNTHETIC data (illustrative only, not market data) - see console log above.  
**Config:** `{'execution': 'next_open', 'rebalance': 'monthly', 'borrow_cost_bps_annual': 0.0}`

## Headline metrics

| Metric | Value |
|---|---|
| start | 2010-01-04 |
| end | 2026-05-19 |
| n_days | 4119 |
| initial_capital | 1,000,000.0000 |
| final_equity | 1,385,444.1327 |
| total_return | 0.3854 |
| cagr | 0.0209 |
| annual_vol | 0.0258 |
| sharpe | 0.8153 |
| sortino | 0.9645 |
| max_drawdown | -0.0448 |
| max_dd_duration_days | 487 |
| calmar | 0.4672 |
| ulcer_index | 0.9976 |
| win_rate | 0.5536 |
| avg_win | 0.0011 |
| avg_loss | -0.0012 |
| hist_var_95 | 0.0025 |
| hist_es_95 | 0.0040 |
| annual_turnover | 1.5719 |
| total_transaction_cost | 14,900.2635 |
| cost_drag_pct_of_initial | 0.0149 |
| avg_gross_exposure | 0.1503 |
| avg_net_exposure | 0.1503 |
| n_risk_events | 0 |

## Yearly returns

| Year | Return |
|---|---|
| 2010 | 0.00% |
| 2011 | 1.04% |
| 2012 | 0.31% |
| 2013 | 5.54% |
| 2014 | 2.13% |
| 2015 | 0.58% |
| 2016 | 0.89% |
| 2017 | 3.68% |
| 2018 | -0.48% |
| 2019 | 3.52% |
| 2020 | 3.30% |
| 2021 | 2.74% |
| 2022 | 0.89% |
| 2023 | 2.06% |
| 2024 | 2.52% |
| 2025 | 4.72% |
| 2026 | 1.03% |

## Stress periods

| Window | Days | Cumulative | Worst day |
|---|---|---|---|
| Euro crisis 2011 | 85 | -0.04% | -0.84% |
| Vol spike 2015-08 | 42 | -1.82% | -0.83% |
| Q4 2018 selloff | 63 | -2.21% | -0.63% |
| COVID crash 2020 | 41 | -1.88% | -1.53% |
| 2022 bear | 209 | 0.38% | -0.67% |

## Exposure diagnostics

| Measure | Value |
|---|---|
| all-day avg gross | 0.1503 |
| all-day avg net | 0.1503 |
| days / active days | 4119 / 3847 (93.4%) |
| active-day avg gross | 0.1609 |
| active-day median gross | 0.1600 |
| active-day max gross | 0.2000 |
| active-day avg net | 0.16093 |
| active-day \|net\|/gross | 1.0000 |

_All-day average understates an opportunistic book (e.g. S03 is flat most days); the active-day figures are the honest gauge._

## Turnover attribution (one-way |Δw|)

| Component | Annualised | Share |
|---|---|---|
| entries | 0.790 | 50.3% |
| exits | 0.780 | 49.6% |
| resizing/rotation | 0.002 | 0.1% |

## Cost attribution

| Component | $ |
|---|---|
| trading (buy) | 7,490 |
| trading (sell) | 7,410 |
| trading total | 14,900 |
| borrow (S03 short leg) | 0 (0.0% of total) |
| **total** | **14,900** |

## Benchmark comparison

_Internal benchmark: S02. External: SPY buy-&-hold. Aligned on common dates._

| Benchmark | strat_sharpe | bench_sharpe | excess_cagr | information_ratio | beta_to_bench | correlation | tracking_error | down_capture |
|---|---|---|---|---|---|---|---|---|
| SPY_buyhold | 0.8154 | 0.8562 | -0.1201 | -0.8221 | 0.1136 | 0.7532 | 0.1528 | 0.1183 |

## Risk events

Total risk interventions: **0**
