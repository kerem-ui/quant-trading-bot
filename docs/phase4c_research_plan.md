# Phase 4C preregistration: frozen S05 historical expansion

This is a **pre-performance research plan**, not a completed research result.
No Phase 4C market data has been downloaded and no validation or holdout
performance has been calculated at registration. S05 economic parameters,
accounting, execution, risk, analytics and locked dependencies are unchanged.

The authoritative machine-readable plan is
`research/phase4c/s05-v1/preregistration.json`. Its exact file SHA-256 is
`d9e95f76bc8a38812f441ef06304cfebd5c11a90f6e8c6d9c61f7a69b65ff30a`.
It also contains the existing Phase 2 canonical JSON manifest checksum.
The publication commit must be recorded and verified on the existing remote
before any new historical data request or performance run. A timestamp inside a
local JSON file alone is not publication evidence.

The baseline is `0d46cd9d21a8fe2b3ab041cb5067f0b331a4383a` on
`phase4-options-analytics`. Frozen Phase 4B specification file SHA-256:
`996afd429eb4461408c8a5c2cce81fdd7e9f214e02cefbfabcfbad14b563b4f0`.
No parameter is to be changed in response to validation or holdout results.

## Research history and period labels

The original playbook, V5.9 feature/power scripts, Phase 4B freeze and results
show previously examined options/IV-VRP research in 2022 and January 2023.
The older script name containing `oos` does not make January 2023 untouched.
No later S05-specific tuning was identified in inspected tracked records.
Unrecorded experimentation cannot be determined from the current repository.

Phase 3C documents underlying ETF research through May 19, 2026, including
explicit chronological comparisons. Furthermore these historical dates precede
the S05 freeze. Consequently the final period is a **retrospective
post-specification holdout**, not genuinely untouched OOS or prospective evidence.

| Partition | Requested dates | Treatment |
|---|---|---|
| Development | Existing data through 2023-01-31 | Already observed; no new alpha claim |
| Validation | 2023-02-01 to 2024-12-31 | New S05 evaluation, previously observed underlying regimes |
| Final holdout | 2025-01-01 to 2026-08-31 | Open only after validation outputs are sealed |

The verified UTC registration date is September 18, 2026; August is the latest
complete month. The current project calendar gives 482 validation and 416
holdout sessions. Actual provider availability can shorten the end only through
a separately sealed availability addendum **before any new performance**.
No favorable subperiod selection, automatic later extension or removal of
unfavorable interior gaps is permitted.

## Frozen strategy and permitted replication

Retain provider-only ATM IV30, bracketed total-variance interpolation, EWMA
lambda .94/annual252 with 20 valid-return warm-up, 252-session percentile window
with at least126 valid IV observations, percentile>=.70 and IV30-RV>=.05.
Retain first-session-of-ISO-week entry, 30-45 DTE, delta selection, mechanical
wings, one contract per leg, one condor, all loss/funding caps and atomic bid/ask
execution. Gross debit profit/stop exits remain D<=.5C and D>=2C, independent of
fees. DTE<=21 and short-strike breach exits are unchanged.

SPY and QQQ remain the core research symbols. The Phase 4C user request permits
IWM as a conditional replication if entitled; it does not rewrite the immutable
Phase 4B universe. Each symbol and evaluation period has a separate flat-start
$100,000 ledger. There is no pooled funded portfolio and no performance-based
selection of symbols. SPY-only can produce a partial SPY report, not a completed
multi-symbol certification.

Each period uses causal pre-period feature history with no pre-period orders or
positions. The period ends under the existing normal terminal liquidation
convention; report forced closes separately. No post-boundary quote may be
borrowed to complete a period. An indefensible exit invalidates that run rather
than producing a midpoint fill. Calendar-year diagnostics preserve the continuous
ledger inside their parent period and include changes in open marked positions.
These boundary choices are declared before results, not selected afterward.

## Minimum acquisition and provenance

Use the existing Theta v3 daily Greek EOD path, and supplement with daily EOD
quotes only if necessary. Request one symbol/date with all expirations through
45 calendar DTE and both rights/all listed strikes, preserving exact identities.
Zero-to-45 coverage supports IV30 interpolation and existing positions through
exit/expiry; no LEAPS, 60/90-day surface, intraday or full-market download is needed.

Acquire a coherent new provider-derived warm-up panel from January 2022 onward
for each entitled symbol. Do not splice ambiguous old provider analytics with a
new model vintage. Preserve the old processed corpus as already observed evidence.
The earlier panel supplies at most the frozen trailing window and never extra
performance; insufficient valid IV still prevents eligibility. The old corpus is
14 processed partitions /1,248,482 rows, with SPY through January2023 and QQQ
January2022 only. It cannot supply the requested expanded experiment.

Preserve bid/ask, IV, delta, spot, identity and all supplied diagnostic Greeks,
quote sizes, volume and timestamp fields. OI is optional and never a new filter.
Missing numeric values remain null; no local-IV fallback. Record provider model
metadata/defaults without inventing historical rates or dividends. Raw provider
bytes remain distinguishable from normalized tables and legacy transformed inputs.

For RV, use the existing yfinance path to obtain one coherent adjusted-close
history from January2010 through the study end, preserving raw source capture,
retrieval time, checksums and dated Parquet provenance. Do not splice adjustment
vintages or substitute raw underlying spot for adjusted returns. Earlier history
seeds the frozen recursive EWMA; only prior/current returns enter each feature.

All data must follow raw capture -> `theta-v3-1` / Phase2 normalization ->
versioned Parquet -> sealed dataset manifest -> DuckDB/research. The explicit
request date supplies an undated daily observation; a stale last-trade or report
creation timestamp cannot silently become its valuation date. Exact timestamp
fields remain separate. Request/response/coverage/normalization/Git/checksums
must remain recoverable. Local data-root paths are supplied through configuration,
not committed in small research metadata. Original datasets are immutable.

## Quality and execution gates

Before performance report every requested date, missing session, 30-45 DTE expiry
coverage, IV30 bracket, strike/wing coverage, duplicate/full contract identity,
missing/non-finite/crossed/nonpositive quotes, invalid IV/delta, spot coverage and
timestamp availability. Preserve suspicious observations and explain unusability.
Conflicting identities, inconsistent dates, checksum failures, missing held-leg
marks or indefensible terminal exits stop an experiment. Missing signal inputs
prevent a candidate under existing rules, not through a new cleaning filter.

The publication and validation gates are requirements for the future Phase 4C
runner, **not a claim that a runner has been implemented in this registration
step**. Before acquiring/evaluating data, integrate and test:

1. Exact committed-and-pushed plan and unchanged S05 specification checks.
2. Requested/observed data manifest checks and causal period/feature slicing.
3. Quality audit before validation performance.
4. Validation batch covering all usable entitled symbols and costs, with report,
   ledger, metric, code, input and output hashes sealed before opening holdout.
5. One holdout batch under the same registered rules, even after poor validation.
6. Exact economic-output replay checks using identical inputs/code/specification.

Acquire warm-up/validation first; defer holdout acquisition until validation is
sealed, except non-performance availability metadata. This stricter sequence
reduces accidental inspection. A software/data defect permits a documented repair,
not a strategy change; retain failed artifacts and disclose any holdout exposure.

## Explicit-cost sensitivity

Evaluate multipliers0,1,2 on commission and additional explicit slippage only.
Base is $0.65 per contract per side and $1 per multi-leg execution. Gross bid/ask
premiums, spread rejection, signals, contracts, exits and risk limits remain
fixed. Zero explicit fees does not remove bid/ask crossing. Gross profit/stop
thresholds never move with fees. Fee-inclusive risk/funding budgets must use the
actual scenario fees; any changed admission is identified rather than forcing
identical trades. The base frozen specification file is never edited.

## Metrics and classification fixed in advance

The JSON defines all requested metrics and their denominators: daily/weekly
eligibility, threshold signals, selected structures, submitted/executed orders,
rejection reasons, completed trades, net win/loss distribution, expectancy,
gross/net P&L, capital return, deployed-risk return, drawdown, average/maximum/event
risk, turnover, commissions/slippage, durations, entryIV/RV/percentile, exits,
calendar-year and symbol results, missingness and concentration.

Return on deployed risk is completed net trade P&L divided by the sum of those
trades' entry fee-inclusive defined risks. Also report the gross-loss denominator.
This reused-capital statistic is not a portfolio return or annualized yield.
Report actual event risk maxima as well as EOD exposure, so same-day lifecycle
changes cannot disappear from the risk report. Existing strict Phase4B equity,
return, premium, fee and cash reconciliation applies (rtol1e-12, atol1e-8).

Classification is per symbol; these are descriptive gates for continued research,
not statistical significance, power guarantees or proof of alpha:

- Adequacy: >=30 completed base trades total, >=10 in each evaluation period;
  each period must have >=95% observed chain sessions and valid underlying-price
  sessions relative to the requested calendar. IV/candidate coverage is also
  reported without deleting missing slots.
- RESEARCH-VALIDATED: integrity/adequacy pass; positive net P&L under both base
  and2x explicit costs in both periods; at least3 positive realized close-year
  totals with>=3 trades each; largest winner<=25% and top5 winners<=60% of all
  positive trade P&L; largest positive year<=60% of positive-year P&L.
- RESEARCH-REJECTED: integrity/adequacy pass and base net P&L is nonpositive in
  both validation and holdout. No rescue optimization is allowed.
- RESEARCH-UNCERTAIN: all other completed cases, including mixed signs,
  concentrated gains, cost fragility, limited trades or weak coverage.
- Unrun or data/software-invalid studies receive no completed research verdict.

Overall core status is validated only if both SPY and QQQ validate, rejected only
if both reject, otherwise uncertain; incomplete core data prevents certification.
IWM cannot rescue failed core outcomes. Thirty trades still gives weak rare-tail
information; even a validated label does not certify commercial viability.

Descriptive regimes are entry trailing63-session adjusted-return sign and IV
percentile70-to-below85 versus85-to100. They never enter strategy rules. Report
concentration, period resets, terminal exits and one-lot capital drag explicitly.

## Entitlement, stopping point and data spending

At preflight the configured local Theta endpoint on port25503 was unreachable;
port25510 also had no listener and no Java process was found. No account values
were read. Current account entitlement and symbol availability therefore **cannot
be determined**. This is a setup blocker, not evidence that the subscription is
insufficient. Start the existing authenticated Theta v3 Terminal before probing
actual access. Do not purchase or upgrade automatically.

The official [daily Greek EOD documentation](https://docs.thetadata.us/operations/option_history_greeks_eod.html)
lists Standard/Pro access. The official
[subscription table](https://docs.thetadata.us/Articles/Getting-Started/Subscriptions.html)
lists Options Standard history from2016, covering this planned2022 warm-up onward.
These public capabilities do not verify this account or guarantee every symbol/date.
No Pro-only endpoint, higher-order Greeks or new stocks subscription is justified
by this frozen daily S05 requirement; underlying RV has its existing provider.
If authenticated access denies the necessary data, report the exact response and
required entitlement for approval before any paid change or substitution.

Storage planning from immutable existing manifests: 1,248,482 processed rows occupy
36,739,259 Parquet bytes (29.43 bytes/row) and51,454,006 compressed legacy-source
bytes. A stationary chain-count proxy over1,169 sessions from2022 throughAugust2026
is about9.0m SPY+QQQ rows or about0.25GiB normalized Parquet. IWM at the observed QQQ
row density would add about3.8m rows/0.10GiB. These are illustrative compressed
normalized baselines, not total storage budgets: modern chain density, additional
metadata, quote supplements, exact raw JSON and audit/replay outputs can be much
larger. Raw-provider storage cannot be reliably determined before a bounded sample.
Old compressed normalized CSV size must not be presented as provider raw size.

No new performance, quality-audit outcome, cost sensitivity or final classification
is available until the data block is resolved. Do not reuse the observed Phase4B
one-trade result as Phase4C evidence. OI, intraday data, alternative analytics
vendors and new paid feeds are not currently justified; later recommendations
must identify a specific unresolved question in the completed frozen experiment.

## Verification scope

`tests/test_phase4c_preregistration.py` covers the seal, exact frozen spec, dates,
warm-up scope, symbol separation, cost-only scenarios, data/null conventions,
registered publication/holdout requirements, predefined criteria and metrics.
The tests initially failed because the registration was absent (1 failure,
13 setup errors), then all14 passed after the plan was created. These check
registration integrity, not nonexistent performance-run gates or new-data results.
Full existing regression and dependency results are recorded separately in the
readiness record. No production source, strategy/configuration, historical data,
old research output, dependency or OneDrive file is changed by this step.