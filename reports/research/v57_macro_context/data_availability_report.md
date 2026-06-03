# V5.7 data availability report

## Market proxies (yfinance + ETF cache)
| symbol | available | rows | first_date | last_date  | description                      |
| ------ | --------- | ---- | ---------- | ---------- | -------------------------------- |
| SPY    | True      | 4119 | 2010-01-04 | 2026-05-19 | Broad equity / trend             |
| ^VIX   | True      | 4120 | 2010-01-04 | 2026-05-20 | Implied volatility               |
| TLT    | True      | 4119 | 2010-01-04 | 2026-05-19 | Long-duration Treasuries (rates) |
| IEF    | True      | 4119 | 2010-01-04 | 2026-05-19 | Intermediate Treasuries (rates)  |
| HYG    | True      | 4120 | 2010-01-04 | 2026-05-20 | High-yield credit                |
| LQD    | True      | 4120 | 2010-01-04 | 2026-05-20 | Investment-grade credit          |
| GLD    | True      | 4119 | 2010-01-04 | 2026-05-19 | Gold                             |

## FRED macro series
`FRED_API_KEY` present at run time: **True**

| series_id | rows | first_date | last_date  | description                                            |
| --------- | ---- | ---------- | ---------- | ------------------------------------------------------ |
| DGS10     | 4098 | 2010-01-04 | 2026-05-20 | 10-Year Treasury Constant Maturity Rate (daily, %)     |
| DGS2      | 4098 | 2010-01-04 | 2026-05-20 | 2-Year Treasury Constant Maturity Rate (daily, %)      |
| T10Y2Y    | 4098 | 2010-01-04 | 2026-05-20 | 10Y-2Y Treasury Spread (daily, %)                      |
| FEDFUNDS  | 196  | 2010-01-01 | 2026-04-01 | Effective Federal Funds Rate (monthly, %)              |
| CPIAUCSL  | 195  | 2010-01-01 | 2026-04-01 | Consumer Price Index for All Urban Consumers (monthly) |
| UNRATE    | 195  | 2010-01-01 | 2026-04-01 | Unemployment Rate (monthly, %)                         |
