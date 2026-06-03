# AAPL — Company Data Availability (SEC EDGAR, read-only)

- Ticker: **AAPL**  CIK: **0000320193**
- Requested range: 2019-01-01 → 2024-12-31
- SEC submissions available this run (live or cached): **True** (if False, nothing was reachable and no cache existed).
- SEC User-Agent: DEFAULT placeholder User-Agent (set QUANTBOT_SEC_USER_AGENT to your 'Name email' for real fetching).
- Prices (yfinance/cache) available: **True**.
- Filings total (recent block): **1000**; in supported forms ('10-K', '10-Q', '8-K') within range: **75**.


## Company facts availability (XBRL us-gaap)

| field                | candidate_tags                                                                                             | matched_tag                                         | available | n_observations | unit |
| -------------------- | ---------------------------------------------------------------------------------------------------------- | --------------------------------------------------- | --------- | -------------- | ---- |
| revenue              | RevenueFromContractWithCustomerExcludingAssessedTax, Revenues, SalesRevenueNet                             | RevenueFromContractWithCustomerExcludingAssessedTax | True      | 113            | USD  |
| net_income           | NetIncomeLoss                                                                                              | NetIncomeLoss                                       | True      | 334            | USD  |
| total_assets         | Assets                                                                                                     | Assets                                              | True      | 144            | USD  |
| total_liabilities    | Liabilities                                                                                                | Liabilities                                         | True      | 142            | USD  |
| cash_and_equivalents | CashAndCashEquivalentsAtCarryingValue, CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents       | CashAndCashEquivalentsAtCarryingValue               | True      | 226            | USD  |
| operating_cash_flow  | NetCashProvidedByUsedInOperatingActivities, NetCashProvidedByUsedInOperatingActivitiesContinuingOperations | NetCashProvidedByUsedInOperatingActivities          | True      | 132            | USD  |
| total_debt           | LongTermDebt, LongTermDebtNoncurrent, DebtLongtermAndShorttermCombinedAmount                               | LongTermDebt                                        | True      | 52             | USD  |

_Fields map to ordered candidate tags; we use the first present and never guess a missing one._


## Filing counts by form (in scope)

| form | n_filings |
| ---- | --------- |
| 8-K  | 51        |
| 10-Q | 18        |
| 10-K | 6         |

## Limitations

- Only the submissions `recent` block is parsed (older shards are a future extension).
- XBRL tags vary by filer/era; unavailable fields are reported, not inferred.
- Section extraction is best-effort (heading regex), not a legal parse.
- LSEG/Datastream not implemented. LSEG/Datastream is a future, optional enrichment (fundamentals, Reuters news, analyst estimates, macro). Not implemented; not required for the SEC EDGAR company research stage. Would be read-only, env-var auth, cached, no broker, LIVE_TRADING_ENABLED stays False.
