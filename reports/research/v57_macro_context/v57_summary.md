# V5.7 Macro / market / news context report

Engine: V5.0 (unchanged). LIVE_TRADING_ENABLED = `False`. No broker / live / IBKR. No order execution. No strategy decisions altered.


## 1. Proxy data availability

| symbol | available | rows | first_date | last_date  | description                      |
| ------ | --------- | ---- | ---------- | ---------- | -------------------------------- |
| SPY    | True      | 4119 | 2010-01-04 | 2026-05-19 | Broad equity / trend             |
| ^VIX   | True      | 4120 | 2010-01-04 | 2026-05-20 | Implied volatility               |
| TLT    | True      | 4119 | 2010-01-04 | 2026-05-19 | Long-duration Treasuries (rates) |
| IEF    | True      | 4119 | 2010-01-04 | 2026-05-19 | Intermediate Treasuries (rates)  |
| HYG    | True      | 4120 | 2010-01-04 | 2026-05-20 | High-yield credit                |
| LQD    | True      | 4120 | 2010-01-04 | 2026-05-20 | Investment-grade credit          |
| GLD    | True      | 4119 | 2010-01-04 | 2026-05-19 | Gold                             |

## 2. FRED macro data

`FRED_API_KEY` was present at run time. Series fetched:

| series_id | rows | first_date | last_date  | description                                            |
| --------- | ---- | ---------- | ---------- | ------------------------------------------------------ |
| DGS10     | 4098 | 2010-01-04 | 2026-05-20 | 10-Year Treasury Constant Maturity Rate (daily, %)     |
| DGS2      | 4098 | 2010-01-04 | 2026-05-20 | 2-Year Treasury Constant Maturity Rate (daily, %)      |
| T10Y2Y    | 4098 | 2010-01-04 | 2026-05-20 | 10Y-2Y Treasury Spread (daily, %)                      |
| FEDFUNDS  | 196  | 2010-01-01 | 2026-04-01 | Effective Federal Funds Rate (monthly, %)              |
| CPIAUCSL  | 195  | 2010-01-01 | 2026-04-01 | Consumer Price Index for All Urban Consumers (monthly) |
| UNRATE    | 195  | 2010-01-01 | 2026-04-01 | Unemployment Rate (monthly, %)                         |

## 3. Macro regime snapshot (last 10 rows)

| date       | trend | vol | rates  | credit  | combined                                     |
| ---------- | ----- | --- | ------ | ------- | -------------------------------------------- |
| 2026-05-07 | up    | mid | stable | neutral | trend=up|vol=mid|rates=stable|credit=neutral |
| 2026-05-08 | up    | mid | stable | neutral | trend=up|vol=mid|rates=stable|credit=neutral |
| 2026-05-11 | up    | mid | stable | neutral | trend=up|vol=mid|rates=stable|credit=neutral |
| 2026-05-12 | up    | mid | stable | neutral | trend=up|vol=mid|rates=stable|credit=neutral |
| 2026-05-13 | up    | mid | up     | neutral | trend=up|vol=mid|rates=up|credit=neutral     |
| 2026-05-14 | up    | mid | stable | neutral | trend=up|vol=mid|rates=stable|credit=neutral |
| 2026-05-15 | up    | mid | up     | neutral | trend=up|vol=mid|rates=up|credit=neutral     |
| 2026-05-18 | up    | mid | up     | neutral | trend=up|vol=mid|rates=up|credit=neutral     |
| 2026-05-19 | up    | mid | up     | risk_on | trend=up|vol=mid|rates=up|credit=risk_on     |
| 2026-05-20 | nan   | mid | up     | risk_on | vol=mid|rates=up|credit=risk_on              |

## 4. Strategy trade context (V5.2 Stage 1 corpus)

Re-ran all three strategies (defaults UNCHANGED) on the frozen SPY Jan-Jun 2022 corpus, producing 29 closed trades across `bull_call`, `bear_put`, `bull_put`. Each trade is annotated with macro / market context drawn from the available proxies and FRED series. **Trade P&L and engine results are NOT mutated by annotation.**


### 4a. Win/loss context summary per strategy

| strategy  | pnl_bucket | n_trades | holding_days_mean | holding_days_median | spy_return_in_trade_pct_mean | spy_return_in_trade_pct_median | vix_at_entry_mean | vix_at_entry_median | vix_at_exit_mean | vix_at_exit_median | vix_change_in_trade_mean | vix_change_in_trade_median | dgs10_at_entry_mean | dgs10_at_entry_median | dgs10_change_in_trade_mean | dgs10_change_in_trade_median | hyg_lqd_ratio_at_entry_mean | hyg_lqd_ratio_at_entry_median | trend_at_entry_mode | vol_at_entry_mode | rates_at_entry_mode | credit_at_entry_mode | macro_regime_at_entry_mode                       |
| --------- | ---------- | -------- | ----------------- | ------------------- | ---------------------------- | ------------------------------ | ----------------- | ------------------- | ---------------- | ------------------ | ------------------------ | -------------------------- | ------------------- | --------------------- | -------------------------- | ---------------------------- | --------------------------- | ----------------------------- | ------------------- | ----------------- | ------------------- | -------------------- | ------------------------------------------------ |
| bear_put  | loss       | 3        | 17.6667           | 17.0000             | 2.6073                       | 1.3399                         | 30.6567           | 29.8300             | 25.0100          | 27.7500            | -5.6467                  | -3.9800                    | 2.8000              | 2.7600                | 0.0500                     | 0.2700                       | 0.6372                      | 0.6379                        | down                | high              | up                  | neutral              | trend=down|vol=high|rates=stable|credit=risk_off |
| bear_put  | win        | 7        | 11.4286           | 9.0000              | -3.5090                      | -3.9901                        | 24.5743           | 23.8500             | 27.3757          | 29.3500            | 2.8014                   | 3.4000                     | 2.0829              | 1.8300                | 0.0786                     | 0.0400                       | 0.6284                      | 0.6220                        | down                | mid               | up                  | risk_on              | trend=up|vol=mid|rates=up|credit=risk_on         |
| bull_call | loss       | 7        | 14.5714           | 16.0000             | -2.3433                      | -2.7264                        | 26.9243           | 29.4500             | 28.3143          | 27.7500            | 1.3900                   | 3.4000                     | 2.4343              | 2.5400                | 0.0100                     | 0.0400                       | 0.6337                      | 0.6379                        | down                | high              | up                  | risk_on              | trend=down|vol=high|rates=up|credit=risk_on      |
| bull_call | win        | 1        | 13.0000           | 13.0000             | 7.0920                       | 7.0920                         | 35.1300           | 35.1300             | 23.5300          | 23.5300            | -11.6000                 | -11.6000                   | 1.8600              | 1.8600                | 0.4600                     | 0.4600                       | 0.6273                      | 0.6273                        | down                | high              | stable              | neutral              | trend=down|vol=high|rates=stable|credit=neutral  |
| bull_put  | loss       | 9        | 11.8889           | 9.0000              | -3.0610                      | -3.5771                        | 25.1711           | 24.0200             | 26.6400          | 27.4700            | 1.4689                   | 2.4700                     | 2.2700              | 2.0500                | 0.1156                     | 0.1100                       | 0.6309                      | 0.6262                        | down                | mid               | up                  | risk_on              | trend=up|vol=mid|rates=up|credit=risk_on         |
| bull_put  | win        | 2        | 14.0000           | 14.0000             | 2.6551                       | 2.6551                         | 27.9650           | 27.9650             | 24.3200          | 24.3200            | -3.6450                  | -3.6450                    | 2.5650              | 2.5650                | 0.1150                     | 0.1150                       | 0.6384                      | 0.6384                        | down                | high              | stable              | risk_off             | trend=down|vol=high|rates=stable|credit=risk_off |

### 4b. Per-trade context table (head 12)

| strategy  | fill_open           | fill_close          | close_reason          | realized_pnl | holding_days | spy_return_in_trade_pct | vix_at_entry | vix_change_in_trade | trend_at_entry | vol_at_entry | macro_regime_at_entry                            |
| --------- | ------------------- | ------------------- | --------------------- | ------------ | ------------ | ----------------------- | ------------ | ------------------- | -------------- | ------------ | ------------------------------------------------ |
| bull_call | 2022-01-04 00:00:00 | 2022-01-13 00:00:00 | dte_exit              | -305.1000    | 9            | -2.7264                 | 16.9100      | 3.4000              | up             | mid          | trend=up|vol=mid|rates=up|credit=risk_on         |
| bull_call | 2022-01-19 00:00:00 | 2022-01-27 00:00:00 | dte_exit              | -301.6000    | 8            | -4.5401                 | 23.8500      | 6.6400              | flat           | mid          | trend=flat|vol=mid|rates=up|credit=risk_on       |
| bull_call | 2022-02-23 00:00:00 | 2022-03-07 00:00:00 | dte_exit              | -92.1000     | 12           | -0.5972                 | 31.0200      | 5.4300              | down           | high         | trend=down|vol=high|rates=up|credit=risk_on      |
| bull_call | 2022-03-08 00:00:00 | 2022-03-21 00:00:00 | profit_target         | 258.9000     | 13           | 7.0920                  | 35.1300      | -11.6000            | down           | high         | trend=down|vol=high|rates=stable|credit=neutral  |
| bull_call | 2022-04-05 00:00:00 | 2022-04-25 00:00:00 | dte_exit              | -361.6000    | 20           | -4.9930                 | 21.0300      | 5.9900              | up             | mid          | trend=up|vol=mid|rates=up|credit=risk_on         |
| bull_call | 2022-04-26 00:00:00 | 2022-05-16 00:00:00 | dte_exit              | -332.1000    | 20           | -3.8476                 | 33.5200      | -6.0500             | down           | high         | trend=down|vol=high|rates=up|credit=risk_on      |
| bull_call | 2022-05-24 00:00:00 | 2022-06-10 00:00:00 | dte_exit              | -126.6000    | 17           | -1.0384                 | 29.4500      | -1.7000             | down           | high         | trend=down|vol=high|rates=stable|credit=risk_off |
| bull_call | 2022-06-14 00:00:00 | 2022-06-30 00:00:00 | force_close_final_bar | -5.6000      | 16           | 1.3399                  | 32.6900      | -3.9800             | down           | high         | trend=down|vol=high|rates=up|credit=neutral      |
| bear_put  | 2022-01-04 00:00:00 | 2022-01-13 00:00:00 | dte_exit              | 227.9000     | 9            | -2.7264                 | 16.9100      | 3.4000              | up             | mid          | trend=up|vol=mid|rates=up|credit=risk_on         |
| bear_put  | 2022-01-19 00:00:00 | 2022-01-27 00:00:00 | dte_exit              | 85.4000      | 8            | -4.5401                 | 23.8500      | 6.6400              | flat           | mid          | trend=flat|vol=mid|rates=up|credit=risk_on       |
| bear_put  | 2022-02-01 00:00:00 | 2022-02-10 00:00:00 | dte_exit              | 36.9000      | 9            | -0.8014                 | 21.9600      | 1.9500              | down           | mid          | trend=down|vol=mid|rates=up|credit=risk_on       |
| bear_put  | 2022-02-15 00:00:00 | 2022-02-24 00:00:00 | dte_exit              | 195.9000     | 9            | -3.9901                 | 25.7000      | 4.6200              | down           | high         | trend=down|vol=high|rates=up|credit=neutral      |

### 4c. Event overlap (CPI / FOMC) — context only, NOT a signal

13 manual events loaded (6 CPI, 4 FOMC, 3 FOMC_MINUTES). Of 29 trades: **27** overlapped >=1 event (17 overlapped a CPI release, 20 overlapped an FOMC statement/minutes). Event overlap is annotation only — trades and P&L are unchanged.


**Per-(strategy, win/loss) event overlap:**

| strategy  | pnl_bucket | n_trades | trades_with_any_event | trades_with_cpi | trades_with_fomc | trades_with_high_importance | mean_events_per_trade |
| --------- | ---------- | -------- | --------------------- | --------------- | ---------------- | --------------------------- | --------------------- |
| bear_put  | loss       | 3        | 3                     | 1               | 3                | 3                           | 1.3333                |
| bear_put  | win        | 7        | 7                     | 5               | 4                | 6                           | 1.2857                |
| bull_call | loss       | 7        | 6                     | 4               | 5                | 6                           | 1.2857                |
| bull_call | win        | 1        | 1                     | 1               | 1                | 1                           | 2.0000                |
| bull_put  | loss       | 9        | 8                     | 6               | 5                | 7                           | 1.2222                |
| bull_put  | win        | 2        | 2                     | 0               | 2                | 1                           | 1.0000                |

**Per-trade event overlap (head 12):**

| strategy  | fill_open           | fill_close          | realized_pnl | event_count_during_trade | cpi_event_during_trade | fomc_event_during_trade | high_importance_event_during_trade | events_during_trade                                                       |
| --------- | ------------------- | ------------------- | ------------ | ------------------------ | ---------------------- | ----------------------- | ---------------------------------- | ------------------------------------------------------------------------- |
| bull_call | 2022-01-04 00:00:00 | 2022-01-13 00:00:00 | -305.1000    | 1                        | True                   | False                   | True                               | CPI:CPI release                                                           |
| bull_call | 2022-01-19 00:00:00 | 2022-01-27 00:00:00 | -301.6000    | 1                        | False                  | True                    | True                               | FOMC:FOMC January meeting statement                                       |
| bull_call | 2022-02-23 00:00:00 | 2022-03-07 00:00:00 | -92.1000     | 0                        | False                  | False                   | False                              |                                                                           |
| bull_call | 2022-03-08 00:00:00 | 2022-03-21 00:00:00 | 258.9000     | 2                        | True                   | True                    | True                               | CPI:CPI release; FOMC:FOMC March meeting statement / first 2022 rate hike |
| bull_call | 2022-04-05 00:00:00 | 2022-04-25 00:00:00 | -361.6000    | 2                        | True                   | True                    | True                               | FOMC_MINUTES:March FOMC minutes release; CPI:CPI release                  |
| bull_call | 2022-04-26 00:00:00 | 2022-05-16 00:00:00 | -332.1000    | 2                        | True                   | True                    | True                               | FOMC:FOMC May meeting statement; CPI:CPI release                          |
| bull_call | 2022-05-24 00:00:00 | 2022-06-10 00:00:00 | -126.6000    | 2                        | True                   | True                    | True                               | FOMC_MINUTES:May FOMC minutes release; CPI:CPI release                    |
| bull_call | 2022-06-14 00:00:00 | 2022-06-30 00:00:00 | -5.6000      | 1                        | False                  | True                    | True                               | FOMC:FOMC June meeting statement                                          |
| bear_put  | 2022-01-04 00:00:00 | 2022-01-13 00:00:00 | 227.9000     | 1                        | True                   | False                   | True                               | CPI:CPI release                                                           |
| bear_put  | 2022-01-19 00:00:00 | 2022-01-27 00:00:00 | 85.4000      | 1                        | False                  | True                    | True                               | FOMC:FOMC January meeting statement                                       |
| bear_put  | 2022-02-01 00:00:00 | 2022-02-10 00:00:00 | 36.9000      | 1                        | True                   | False                   | True                               | CPI:CPI release                                                           |
| bear_put  | 2022-02-15 00:00:00 | 2022-02-24 00:00:00 | 195.9000     | 1                        | False                  | True                    | False                              | FOMC_MINUTES:January FOMC minutes release                                 |

## 5. Strongest SPY return windows (cache-only)

| ticker | window_days | start_date | end_date   | direction | return_pct | start_price | end_price |
| ------ | ----------- | ---------- | ---------- | --------- | ---------- | ----------- | --------- |
| SPY    | 5           | 2020-03-23 | 2020-03-30 | up        | 17.3582    | 204.9449    | 240.5195  |
| SPY    | 5           | 2020-03-09 | 2020-03-16 | down      | -12.5369   | 250.6099    | 219.1912  |
| SPY    | 5           | 2011-08-01 | 2011-08-08 | down      | -12.8281   | 99.1640     | 86.4432   |
| SPY    | 5           | 2020-03-13 | 2020-03-20 | down      | -14.5457   | 246.1228    | 210.3225  |
| SPY    | 5           | 2020-03-05 | 2020-03-12 | down      | -17.9693   | 276.4084    | 226.7397  |
| SPY    | 21          | 2020-02-18 | 2020-03-18 | down      | -28.7263   | 307.7266    | 219.3282  |
| SPY    | 21          | 2020-02-13 | 2020-03-16 | down      | -28.8406   | 308.0282    | 219.1912  |
| SPY    | 21          | 2020-02-19 | 2020-03-19 | down      | -28.9147   | 309.1980    | 219.7943  |
| SPY    | 21          | 2020-02-20 | 2020-03-20 | down      | -31.6974   | 307.9277    | 210.3225  |
| SPY    | 21          | 2020-02-21 | 2020-03-23 | down      | -32.7513   | 304.7566    | 204.9449  |
| SPY    | 63          | 2020-03-23 | 2020-06-22 | up        | 39.9358    | 204.9449    | 286.7913  |
| SPY    | 63          | 2020-03-20 | 2020-06-19 | up        | 35.4887    | 210.3225    | 284.9632  |
| SPY    | 63          | 2020-03-18 | 2020-06-17 | up        | 30.6220    | 219.3282    | 286.4908  |
| SPY    | 63          | 2020-03-19 | 2020-06-18 | up        | 30.3951    | 219.7943    | 286.6011  |
| SPY    | 63          | 2019-12-19 | 2020-03-23 | down      | -29.7714   | 291.8254    | 204.9449  |

## 6. AAPL example (yfinance, optional)

yfinance fetch succeeded for AAPL (1509 rows, 2019-01-02 -> 2024-12-30).

| ticker | window_days | start_date | end_date   | direction | return_pct | start_price | end_price |
| ------ | ----------- | ---------- | ---------- | --------- | ---------- | ----------- | --------- |
| AAPL   | 21          | 2020-07-24 | 2020-08-24 | up        | 36.1382    | 89.6724     | 122.0785  |
| AAPL   | 21          | 2020-07-28 | 2020-08-26 | up        | 35.9220    | 90.2897     | 122.7235  |
| AAPL   | 21          | 2020-07-23 | 2020-08-21 | up        | 34.1960    | 89.8951     | 120.6356  |
| AAPL   | 21          | 2020-07-27 | 2020-08-25 | up        | 31.8954    | 91.7977     | 121.0770  |
| AAPL   | 21          | 2020-07-29 | 2020-08-27 | up        | 31.7712    | 92.0204     | 121.2564  |
| AAPL   | 63          | 2020-06-03 | 2020-09-01 | up        | 65.3813    | 78.6976     | 130.1511  |
| AAPL   | 63          | 2020-06-04 | 2020-09-02 | up        | 63.3618    | 78.0198     | 127.4546  |
| AAPL   | 63          | 2020-03-23 | 2020-06-22 | up        | 60.3786    | 54.1637     | 86.8670   |
| AAPL   | 63          | 2020-06-02 | 2020-08-31 | up        | 59.9216    | 78.2667     | 125.1654  |
| AAPL   | 63          | 2020-05-28 | 2020-08-26 | up        | 59.3095    | 77.0346     | 122.7235  |

## 7. Data availability summary

- Market proxies available: 7 / 7
- FRED series available: 6 (live + cache)
- Events: 13 manual events loaded
- AAPL example: ran


## 8. Guardrails honored

- `LIVE_TRADING_ENABLED = False` (runtime).
- No broker / live / IBKR / order-execution imports anywhere in   `quantbot.macro`, `quantbot.research`, or `quantbot.events`.
- No strategy decisions or engine logic altered. The strategy   re-runs reproduce the V5.3 / V5.4 / V5.5 / V5.6 archived baselines   exactly.
- No packages installed. yfinance and FRED handled with graceful   fallback.
- No credentials read into source, logs, or output files.   `FRED_API_KEY` is consulted via `os.environ.get(...)` only.
