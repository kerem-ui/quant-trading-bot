# S02 (CORE) - V3 Analytics Report

_loaded 18 symbols x 4119 bars (2010-01-04 -> 2026-05-19). If yfinance was unreachable this is SYNTHETIC data (illustrative only, not market data) - see console log above._

> Research/backtest only. No broker/live/options. No strategy defaults changed. S02 is the core strategy (S01 satellite, S03 research-only).

## Headline

| metric | value |
|---|---|
| start | 2010-01-04 |
| end | 2026-05-19 |
| n_days | 4119 |
| cagr | 0.0209 |
| annual_vol | 0.0258 |
| sharpe | 0.8153 |
| sortino | 0.9645 |
| max_drawdown | -0.0448 |
| max_dd_duration_days | 487 |
| calmar | 0.4672 |
| annual_turnover | 1.5719 |
| total_transaction_cost | 14900.2635 |
| cost_drag_pct_of_initial | 0.0149 |
| avg_gross_exposure | 0.1503 |
| trading_cost | 14900 |
| borrow_cost | 0 |

## 1. ETF-level contribution

| index | total_contribution | avg_weight_all_days | avg_weight_when_held | days_held | pct_days_held | annual_turnover |
|---|---|---|---|---|---|---|
| SLV | 0.0451 | 0.0077 | 0.0400 | 792 | 0.1923 | 0.1101 |
| XLK | 0.0445 | 0.0132 | 0.0399 | 1367 | 0.3319 | 0.1468 |
| GLD | 0.0421 | 0.0124 | 0.0399 | 1277 | 0.3100 | 0.1060 |
| QQQ | 0.0347 | 0.0170 | 0.0399 | 1756 | 0.4263 | 0.1273 |
| XLV | 0.0345 | 0.0100 | 0.0400 | 1033 | 0.2508 | 0.0930 |
| XLE | 0.0314 | 0.0076 | 0.0400 | 784 | 0.1903 | 0.0759 |
| XLF | 0.0233 | 0.0112 | 0.0400 | 1158 | 0.2811 | 0.0783 |
| XLY | 0.0205 | 0.0099 | 0.0400 | 1021 | 0.2479 | 0.0881 |
| XLI | 0.0179 | 0.0083 | 0.0400 | 857 | 0.2081 | 0.1175 |
| XLP | 0.0118 | 0.0079 | 0.0400 | 818 | 0.1986 | 0.0881 |
| XLU | 0.0110 | 0.0097 | 0.0400 | 1000 | 0.2428 | 0.0857 |
| IWM | 0.0053 | 0.0064 | 0.0400 | 658 | 0.1598 | 0.0832 |
| DIA | 0.0053 | 0.0042 | 0.0400 | 427 | 0.1037 | 0.0587 |
| XLRE | 0.0049 | 0.0037 | 0.0400 | 381 | 0.0925 | 0.0343 |
| TLT | 0.0035 | 0.0065 | 0.0398 | 674 | 0.1636 | 0.0636 |
| IEF | 0.0035 | 0.0030 | 0.0400 | 313 | 0.0760 | 0.0440 |
| SPY | 0.0026 | 0.0080 | 0.0400 | 825 | 0.2003 | 0.1126 |
| XLB | 0.0024 | 0.0034 | 0.0400 | 350 | 0.0850 | 0.0587 |

**Best:** SLV +0.0451, XLK +0.0445, GLD +0.0421, QQQ +0.0347, XLV +0.0346
**Worst:** XLB +0.0024, SPY +0.0026, IEF +0.0035, TLT +0.0035, XLRE +0.0049

Yearly contribution by ETF:

| index | 2010 | 2011 | 2012 | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SPY | 0.0000 | 0.0000 | 0.0002 | 0.0019 | 0.0001 | -0.0040 | -0.0014 | 0.0017 | -0.0039 | 0.0000 | -0.0018 | 0.0023 | 0.0002 | 0.0036 | 0.0055 | -0.0013 | -0.0004 |
| QQQ | 0.0000 | -0.0013 | -0.0025 | 0.0013 | 0.0060 | 0.0012 | -0.0020 | 0.0057 | -0.0015 | 0.0034 | 0.0099 | 0.0047 | -0.0036 | 0.0097 | 0.0028 | 0.0029 | -0.0018 |
| IWM | 0.0000 | -0.0037 | 0.0000 | 0.0082 | -0.0020 | -0.0027 | 0.0000 | 0.0026 | 0.0019 | 0.0000 | 0.0000 | -0.0016 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0025 |
| DIA | 0.0000 | 0.0000 | 0.0011 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0083 | -0.0049 | 0.0003 | 0.0000 | 0.0000 | -0.0014 | 0.0001 | 0.0017 | 0.0000 | 0.0000 |
| XLK | 0.0000 | 0.0000 | -0.0027 | 0.0000 | 0.0035 | 0.0042 | 0.0043 | 0.0057 | 0.0027 | 0.0030 | 0.0068 | 0.0038 | -0.0057 | 0.0127 | 0.0041 | 0.0020 | 0.0001 |
| XLF | 0.0000 | 0.0000 | 0.0020 | 0.0091 | 0.0029 | -0.0038 | 0.0000 | 0.0074 | -0.0018 | 0.0000 | -0.0012 | 0.0035 | -0.0020 | 0.0000 | 0.0044 | 0.0027 | 0.0000 |
| XLE | 0.0000 | 0.0006 | -0.0000 | 0.0024 | -0.0005 | 0.0000 | 0.0000 | -0.0017 | 0.0018 | 0.0000 | 0.0000 | 0.0037 | 0.0229 | 0.0005 | 0.0005 | 0.0000 | 0.0012 |
| XLV | 0.0000 | -0.0029 | 0.0037 | 0.0148 | 0.0070 | 0.0035 | 0.0007 | 0.0008 | 0.0046 | 0.0014 | 0.0015 | 0.0000 | 0.0003 | -0.0008 | 0.0000 | 0.0000 | 0.0000 |
| XLI | 0.0000 | 0.0035 | 0.0000 | 0.0001 | -0.0000 | 0.0000 | 0.0030 | 0.0024 | -0.0003 | 0.0000 | -0.0009 | 0.0007 | 0.0041 | -0.0026 | 0.0023 | 0.0035 | 0.0021 |
| XLY | 0.0000 | -0.0009 | -0.0006 | 0.0131 | -0.0012 | 0.0025 | -0.0013 | 0.0000 | 0.0007 | 0.0029 | 0.0046 | 0.0026 | -0.0048 | 0.0043 | 0.0024 | -0.0039 | 0.0000 |
| XLP | 0.0000 | 0.0017 | 0.0007 | 0.0019 | 0.0000 | 0.0048 | 0.0016 | 0.0000 | -0.0037 | 0.0020 | 0.0000 | 0.0000 | 0.0014 | 0.0014 | 0.0000 | -0.0001 | 0.0000 |
| XLU | 0.0000 | 0.0027 | -0.0013 | 0.0000 | 0.0028 | -0.0019 | 0.0054 | -0.0001 | 0.0000 | 0.0097 | -0.0095 | 0.0000 | 0.0017 | -0.0007 | -0.0000 | 0.0049 | -0.0027 |
| XLB | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0011 | 0.0000 | -0.0010 | 0.0023 | 0.0006 | 0.0000 | 0.0000 | 0.0020 | -0.0001 | -0.0032 | 0.0000 | 0.0000 | 0.0007 |
| XLRE | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0055 | -0.0005 | 0.0043 | -0.0044 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| GLD | 0.0000 | 0.0099 | 0.0022 | 0.0000 | 0.0000 | 0.0000 | -0.0035 | 0.0003 | -0.0004 | -0.0016 | 0.0094 | 0.0009 | 0.0008 | -0.0006 | 0.0050 | 0.0171 | 0.0026 |
| SLV | 0.0000 | 0.0006 | 0.0028 | 0.0012 | 0.0000 | 0.0000 | 0.0031 | 0.0009 | 0.0000 | 0.0019 | 0.0173 | 0.0003 | 0.0000 | -0.0038 | -0.0037 | 0.0179 | 0.0066 |
| TLT | 0.0000 | 0.0009 | -0.0025 | 0.0000 | 0.0016 | 0.0021 | 0.0001 | 0.0000 | 0.0000 | 0.0036 | -0.0023 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| IEF | 0.0000 | -0.0003 | 0.0002 | 0.0000 | 0.0000 | 0.0002 | 0.0001 | 0.0000 | 0.0000 | 0.0025 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0007 | 0.0000 |

## 2. Factor analysis

Isolated single-factor sleeves:

| factor | cagr | sharpe | max_drawdown | annual_turnover |
|---|---|---|---|---|
| momentum_12m_ex_1m | 0.0198 | 0.7619 | -0.0433 | 0.9364 |
| momentum_3m | 0.0163 | 0.6693 | -0.0488 | 1.7522 |
| one_month_reversal | 0.0169 | 0.6077 | -0.0837 | 2.7337 |
| low_volatility | 0.0146 | 1.1149 | -0.0241 | 0.6118 |
| liquidity | 0.0204 | 0.7836 | -0.0474 | 0.2719 |

Blend Sharpe = 0.815. Leave-one-out:

| dropped | sharpe | d_sharpe | d_cagr |
|---|---|---|---|
| momentum_12m_ex_1m | 0.7676 | -0.0476 | -0.0044 |
| momentum_3m | 0.7438 | -0.0715 | -0.0012 |
| one_month_reversal | 0.7947 | -0.0206 | -0.0015 |
| low_volatility | 0.8057 | -0.0095 | 0.0004 |
| liquidity | 0.9043 | 0.0890 | 0.0015 |

Sleeve return correlation:

| index | momentum_12m_ex_1m | momentum_3m | one_month_reversal | low_volatility | liquidity |
|---|---|---|---|---|---|
| momentum_12m_ex_1m | 1.0000 | 0.7100 | 0.6400 | 0.5900 | 0.8000 |
| momentum_3m | 0.7100 | 1.0000 | 0.4300 | 0.5800 | 0.6900 |
| one_month_reversal | 0.6400 | 0.4300 | 1.0000 | 0.4700 | 0.7600 |
| low_volatility | 0.5900 | 0.5800 | 0.4700 | 1.0000 | 0.5600 |
| liquidity | 0.8000 | 0.6900 | 0.7600 | 0.5600 | 1.0000 |

Factor stability by sub-period (sleeve Sharpe):

| factor | 2010-2014 | 2015-2019 | 2020-2026 |
|---|---|---|---|
| momentum_12m_ex_1m | 0.7170 | 0.5450 | 0.9320 |
| momentum_3m | 0.8760 | 0.0470 | 0.9070 |
| one_month_reversal | 0.5490 | 1.3710 | 0.3230 |
| low_volatility | 1.5880 | 0.9900 | 0.9120 |
| liquidity | 0.7900 | 0.8970 | 0.7330 |

Weight sensitivity: default Sharpe 0.815, equal-weight 0.804, random [0.743, 0.988], 100% positive -> edge_is_robust = **True**.

## 3. Regime analysis

| index | n_days | cum_return | ann_return | ann_vol | sharpe | max_drawdown |
|---|---|---|---|---|---|---|
| SPY bull (>200dma) | 3349.0000 | 0.3162 | 0.0209 | 0.0227 | 0.9241 | -0.0335 |
| SPY bear (<200dma) | 770.0000 | 0.0662 | 0.0212 | 0.0366 | 0.5910 | -0.0336 |
| high-vol regime | 2054.0000 | 0.2310 | 0.0258 | 0.0300 | 0.8650 | -0.0448 |
| low-vol regime | 2065.0000 | 0.1400 | 0.0161 | 0.0209 | 0.7755 | -0.0243 |
| SPY up days | 2279.0000 | 6.0225 | 0.2405 | 0.0200 | 10.7688 | -0.0087 |
| SPY down days | 1827.0000 | -0.8004 | -0.1993 | 0.0241 | -9.1948 | -0.8004 |

Crisis windows:

| index | n_days | cum_return | max_drawdown | spy_cum_return |
|---|---|---|---|---|
| Euro crisis 2011 (2011-07-01->2011-10-31) | 85.0000 | -0.0004 | -0.0314 | -0.0441 |
| Vol spike 2015-08 (2015-08-01->2015-09-30) | 42.0000 | -0.0182 | -0.0228 | -0.0849 |
| Q4 2018 selloff (2018-10-01->2018-12-31) | 63.0000 | -0.0221 | -0.0328 | -0.1353 |
| COVID crash 2020 (2020-02-15->2020-04-15) | 41.0000 | -0.0188 | -0.0448 | -0.1724 |
| 2022 bear (2022-01-01->2022-10-31) | 209.0000 | 0.0038 | -0.0222 | -0.1774 |

Explicit 2020 / 2022:

| index | n_days | cum_return | spy_cum_return | max_drawdown |
|---|---|---|---|---|
| COVID 2020 (02-15..04-15) | 41.0000 | -0.0188 | -0.1724 | -0.0448 |
| Bear 2022 (01-01..10-31) | 209.0000 | 0.0038 | -0.1774 | -0.0222 |
| Full 2020 | 253.0000 | 0.0330 | 0.1833 | -0.0448 |
| Full 2022 | 251.0000 | 0.0089 | -0.1818 | -0.0222 |

## 4. Risk analysis

Max-drawdown window: 2020-02-19 -> 2020-03-23 (depth -0.0448)

Exposure by bucket:

| index | avg_gross | max_gross |
|---|---|---|
| tech_equity | 0.0303 | 0.0800 |
| precious_metals | 0.0201 | 0.0800 |
| broad_equity | 0.0122 | 0.0800 |
| financials | 0.0112 | 0.0400 |
| healthcare | 0.0100 | 0.0400 |
| consumer_disc | 0.0099 | 0.0400 |
| utilities | 0.0097 | 0.0400 |
| rates | 0.0096 | 0.0800 |
| industrials | 0.0083 | 0.0400 |
| consumer_staples | 0.0079 | 0.0400 |
| energy | 0.0076 | 0.0400 |
| small_cap | 0.0064 | 0.0400 |
| real_estate | 0.0037 | 0.0400 |
| materials | 0.0034 | 0.0400 |

Risk contribution by bucket (annualized; sums to ann vol):

| index | ann_risk |
|---|---|
| tech_equity | 0.0069 |
| precious_metals | 0.0055 |
| utilities | 0.0020 |
| consumer_disc | 0.0018 |
| broad_equity | 0.0017 |
| energy | 0.0016 |
| financials | 0.0013 |
| healthcare | 0.0013 |
| small_cap | 0.0012 |
| industrials | 0.0009 |
| consumer_staples | 0.0007 |
| real_estate | 0.0004 |
| materials | 0.0004 |
| rates | 0.0002 |

Drawdown contribution by bucket (max-DD window):

| index | dd_contrib |
|---|---|
| tech_equity | -0.0252 |
| utilities | -0.0160 |
| broad_equity | -0.0035 |
| precious_metals | -0.0006 |
| financials | 0.0000 |
| consumer_disc | 0.0000 |
| consumer_staples | 0.0000 |
| energy | 0.0000 |
| materials | 0.0000 |
| industrials | 0.0000 |
| healthcare | 0.0000 |
| rates | 0.0000 |
| small_cap | 0.0000 |
| real_estate | 0.0000 |

## 5. Benchmark analysis

| benchmark | strat_cagr | bench_cagr | excess_cagr | strat_sharpe | bench_sharpe | tracking_error | beta_to_bench | correlation | information_ratio | down_capture |
|---|---|---|---|---|---|---|---|---|---|---|
| SPY_buyhold | 0.0210 | 0.1411 | -0.1201 | 0.8154 | 0.8562 | 0.1528 | 0.1136 | 0.7532 | -0.8221 | 0.1183 |
| equal_weight_basket | 0.0210 | 0.1193 | -0.0983 | 0.8154 | 0.9041 | 0.1154 | 0.1514 | 0.7889 | -0.8727 | 0.1588 |
| SHY_cash | 0.0210 | 0.0135 | 0.0074 | 0.8154 | 1.0124 | 0.0291 | -0.0034 | -0.0018 | 0.2584 | -0.1844 |

_Interpretation: S02 is a low-beta, downside-protective, cash-plus book - it trails SPY on raw CAGR but with far lower beta/drawdown and strong downside protection (low down-capture), and beats a SHY cash proxy on a risk-adjusted basis._

## Figures

- `reports/figures/s02_v3/equity.png`
- `reports/figures/s02_v3/drawdown.png`
- `reports/figures/s02_v3/rolling_vol.png`
- `reports/figures/s02_v3/rolling_sharpe.png`
- `reports/figures/s02_v3/contribution_by_etf.png`
- `reports/figures/s02_v3/exposure_by_bucket.png`
- `reports/figures/s02_v3/benchmark_growth.png`
