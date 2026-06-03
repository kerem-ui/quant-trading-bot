# S03_pairs_mean_reversion

> Research/backtest only. No live trading. No profitability is promised. Costs, slippage, spread (and S03 borrow) are modelled but real-world results will differ. If run on synthetic data, results are illustrative only and not based on market data.

**Data source:** loaded 18 symbols x 4119 bars (2010-01-04 -> 2026-05-19). If yfinance was unreachable this is SYNTHETIC data (illustrative only, not market data) - see console log above.  
**Config:** `{'execution': 'next_open', 'rebalance': 'weekly', 'borrow_cost_bps_annual': 50.0}`

## Headline metrics

| Metric | Value |
|---|---|
| start | 2010-01-04 |
| end | 2026-05-19 |
| n_days | 4119 |
| initial_capital | 1,000,000.0000 |
| final_equity | 1,018,722.5955 |
| total_return | 0.0187 |
| cagr | 0.0020 |
| annual_vol | 0.0082 |
| sharpe | 0.2548 |
| sortino | 0.1227 |
| max_drawdown | -0.0310 |
| max_dd_duration_days | 2598 |
| calmar | 0.0659 |
| ulcer_index | 1.5099 |
| win_rate | 0.5184 |
| avg_win | 0.0010 |
| avg_loss | -0.0009 |
| hist_var_95 | 0.0002 |
| hist_es_95 | 0.0011 |
| annual_turnover | 1.6037 |
| total_transaction_cost | 15,262.7048 |
| cost_drag_pct_of_initial | 0.0153 |
| avg_gross_exposure | 0.0419 |
| avg_net_exposure | -0.0010 |
| n_risk_events | 0 |

## Yearly returns

| Year | Return |
|---|---|
| 2010 | 0.00% |
| 2011 | 0.73% |
| 2012 | 0.64% |
| 2013 | 0.80% |
| 2014 | 0.00% |
| 2015 | 2.08% |
| 2016 | 0.79% |
| 2017 | -0.89% |
| 2018 | 0.28% |
| 2019 | -0.78% |
| 2020 | -0.31% |
| 2021 | -0.33% |
| 2022 | 1.42% |
| 2023 | 0.11% |
| 2024 | -0.00% |
| 2025 | 0.11% |
| 2026 | -1.25% |

## Stress periods

| Window | Days | Cumulative | Worst day |
|---|---|---|---|
| Euro crisis 2011 | 85 | 0.00% | 0.00% |
| Vol spike 2015-08 | 42 | 0.53% | -0.11% |
| Q4 2018 selloff | 63 | -0.02% | -0.07% |
| COVID crash 2020 | 41 | 0.00% | 0.00% |
| 2022 bear | 209 | 1.74% | -0.44% |

## Exposure diagnostics

| Measure | Value |
|---|---|
| all-day avg gross | 0.0419 |
| all-day avg net | -0.0010 |
| days / active days | 4119 / 518 (12.6%) |
| active-day avg gross | 0.3330 |
| active-day median gross | 0.3000 |
| active-day max gross | 0.6000 |
| active-day avg net | -0.00766 |
| active-day \|net\|/gross | 0.0565 |

_All-day average understates an opportunistic book (e.g. S03 is flat most days); the active-day figures are the honest gauge._

## Turnover attribution (one-way |Δw|)

| Component | Annualised | Share |
|---|---|---|
| entries | 0.787 | 49.1% |
| exits | 0.764 | 47.7% |
| resizing/rotation | 0.053 | 3.3% |

## Cost attribution

| Component | $ |
|---|---|
| trading (buy) | 6,734 |
| trading (sell) | 6,734 |
| trading total | 13,468 |
| borrow (S03 short leg) | 1,795 (11.8% of total) |
| **total** | **15,263** |

## Benchmark comparison

_Internal benchmark: S02. External: SPY buy-&-hold. Aligned on common dates._

| Benchmark | strat_sharpe | bench_sharpe | excess_cagr | information_ratio | beta_to_bench | correlation | tracking_error | down_capture |
|---|---|---|---|---|---|---|---|---|
| S02_factor | 0.2548 | 0.8153 | -0.0189 | -0.6982 | -0.0042 | -0.0134 | 0.0272 | -0.0009 |
| SPY_buyhold | 0.2548 | 0.8562 | -0.1390 | -0.8431 | -0.0001 | -0.0016 | 0.1716 | 0.0004 |

## Risk events

Total risk interventions: **0**
