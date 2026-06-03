# S01_trend_following

> Research/backtest only. No live trading. No profitability is promised. Costs, slippage, spread (and S03 borrow) are modelled but real-world results will differ. If run on synthetic data, results are illustrative only and not based on market data.

**Data source:** loaded 18 symbols x 4119 bars (2010-01-04 -> 2026-05-19). If yfinance was unreachable this is SYNTHETIC data (illustrative only, not market data) - see console log above.  
**Config:** `{'execution': 'next_open', 'rebalance': 'weekly', 'borrow_cost_bps_annual': 0.0}`

## Headline metrics

| Metric | Value |
|---|---|
| start | 2010-01-04 |
| end | 2026-05-19 |
| n_days | 4119 |
| initial_capital | 1,000,000.0000 |
| final_equity | 1,243,604.7684 |
| total_return | 0.2436 |
| cagr | 0.0159 |
| annual_vol | 0.0481 |
| sharpe | 0.3529 |
| sortino | 0.3746 |
| max_drawdown | -0.1155 |
| max_dd_duration_days | 1814 |
| calmar | 0.1380 |
| ulcer_index | 5.4235 |
| win_rate | 0.5374 |
| avg_win | 0.0021 |
| avg_loss | -0.0023 |
| hist_var_95 | 0.0047 |
| hist_es_95 | 0.0078 |
| annual_turnover | 4.9353 |
| total_transaction_cost | 42,317.5154 |
| cost_drag_pct_of_initial | 0.0423 |
| avg_gross_exposure | 0.3048 |
| avg_net_exposure | 0.3048 |
| n_risk_events | 1 |

## Yearly returns

| Year | Return |
|---|---|
| 2010 | 0.82% |
| 2011 | 5.22% |
| 2012 | -0.49% |
| 2013 | 0.63% |
| 2014 | -2.43% |
| 2015 | -5.79% |
| 2016 | 6.21% |
| 2017 | 0.45% |
| 2018 | -4.27% |
| 2019 | 6.72% |
| 2020 | 5.31% |
| 2021 | 0.69% |
| 2022 | -4.55% |
| 2023 | 4.80% |
| 2024 | -2.37% |
| 2025 | 12.67% |
| 2026 | 4.26% |

## Stress periods

| Window | Days | Cumulative | Worst day |
|---|---|---|---|
| Euro crisis 2011 | 85 | 1.55% | -1.31% |
| Vol spike 2015-08 | 42 | 0.00% | 0.00% |
| Q4 2018 selloff | 63 | -0.13% | -0.47% |
| COVID crash 2020 | 41 | -2.13% | -1.36% |
| 2022 bear | 209 | -4.37% | -1.32% |

## Exposure diagnostics

| Measure | Value |
|---|---|
| all-day avg gross | 0.3048 |
| all-day avg net | 0.3048 |
| days / active days | 4119 / 3322 (80.7%) |
| active-day avg gross | 0.3780 |
| active-day median gross | 0.3057 |
| active-day max gross | 0.9330 |
| active-day avg net | 0.37798 |
| active-day \|net\|/gross | 1.0000 |

_All-day average understates an opportunistic book (e.g. S03 is flat most days); the active-day figures are the honest gauge._

## Turnover attribution (one-way |Δw|)

| Component | Annualised | Share |
|---|---|---|
| entries | 2.252 | 45.6% |
| exits | 2.260 | 45.8% |
| resizing/rotation | 0.424 | 8.6% |

## Cost attribution

| Component | $ |
|---|---|
| trading (buy) | 21,190 |
| trading (sell) | 21,127 |
| trading total | 42,318 |
| borrow (S03 short leg) | 0 (0.0% of total) |
| **total** | **42,318** |

## Benchmark comparison

_Internal benchmark: S02. External: SPY buy-&-hold. Aligned on common dates._

| Benchmark | strat_sharpe | bench_sharpe | excess_cagr | information_ratio | beta_to_bench | correlation | tracking_error | down_capture |
|---|---|---|---|---|---|---|---|---|
| S02_factor | 0.3529 | 0.8153 | -0.0050 | -0.0876 | 0.5892 | 0.3167 | 0.0468 | 0.7618 |
| SPY_buyhold | 0.3529 | 0.8562 | -0.1251 | -0.7626 | 0.0464 | 0.1654 | 0.1702 | 0.0936 |

## Risk events

Total risk interventions: **1**
- 2011-05-06: de-risk x0.5: prior-day loss -2.22%
