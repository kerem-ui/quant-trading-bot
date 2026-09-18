# Phase 3C — Strategy revalidation report

These results certify reproducible accounting under a frozen historical research convention. They do not prove alpha, profitability outside this sample, trading capacity or live readiness. No strategy parameters were tuned in response to these results.

## Frozen identity and inputs

Run: `phase3c-20260918-certified-v3`. Executed runtime commit: `8a9fde562badad337eb49f653c6965d9f7b34032`.
Frozen specification: `4bf062986ebd7616bc8cedb0f62577d62d2f0758f4feff4a4d28f30e778eaeca`.
Dataset identity: `bae5a18d37240390372df1b4980ff80b2aec748fc708ddcbbec5a5dde4f6a953`.
Run-manifest seal: `57ec90d1e2baf4a7a0a531172753b3640c676c418243c5e48e28830a7b8454eb`.
Inputs: 25 immutable legacy-normalized ETF CSV files, 101,171 rows, 11,158,084 bytes. Source hashes match the Phase 2C inventory. All expected sessions between each ETF's first and last available dates are present; OHLCV fields are finite and positive prices/nonnegative volume are required.
39 legacy report files retain their original hashes. 146 runtime source files and the lock/configuration files are fingerprinted. Source and configuration guards passed before and after execution.
Git text fingerprints canonicalize CRLF/LF; market inputs and generated outputs retain exact-byte hashes. Both Git newline checkout modes passed the frozen guards. Legacy report bytes also remain unchanged within each run.
VOO starts 2010-09-09, VTWO 2010-09-22 and XLRE 2015-10-08; the other selected series start 2010-01-04. All end 2026-05-19. Provider retrieval metadata is absent: original vendor provenance cannot be independently authenticated. No synthetic fallback or download was used.

## Frozen specifications

### S01: binary-phase3b

Universe: SPY, QQQ, IWM, DIA, TLT, IEF, GLD, SLV, UUP.

- **cadence:** weekly entries/resizing; actual-held exits and central risk daily, next session execution
- **entry:** binary score >=1; trailing 20-session absolute move >4 * base roundtrip 10bp cost hurdle
- **exit:** score <0.25 or three closes below EMA50 after minimum hold; ATR14*3 trailing hard stop always active
- **minimum_hold:** 20 sessions from executed entry for soft exits; hard stops/risk override
- **signal:** 0.35/0.35/0.30 blend of trailing-return z-scores (20/60/120, trailing normalization 252)
- **sizing:** long-only inverse realized volatility20, target10%, strategy15% cap, central risk then 2% no-trade band

### S02: price-only-v1-phase3b

Universe: SPY, QQQ, IWM, DIA, XLK, XLF, XLE, XLV, XLI, XLY, XLP, XLU, XLB, XLRE, GLD, SLV, TLT, IEF.

- **cadence:** monthly entries/resizes/exits; daily risk
- **entry:** top 20% score, >=3 eligible names; raw close >=5, trailing raw ADV21 min10 >=10M; active factor values finite
- **exit:** monthly no-longer-selected target zero; central risk daily
- **minimum_hold:** none beyond monthly allocation cadence; risk may exit earlier
- **signal:** eligible-only percentile ranks: 12m-ex-1m momentum/3m momentum/1m reversal/lowvol/liquidity
- **sizing:** equal positive weights min(4%,1/selected count); no leverage-up; central caps; no band

### S03: hedge-ratio-matched-phase3b

Universe: SPY, IVV, VOO, DIA, GLD, IAU, SLV, XLF, KBE, XLE, XOP, QQQ, XLK, IWM, VTWO.

- **cadence:** monthly causal same-sector pair selection: corr252>=0.65,coint p<=0.10,half-life2..45; weekly entry/resize; daily exits/risk
- **entry:** long spread z<=-2, short spread z>=2; re-arm only after |z|<=0.5
- **exit:** |z|<=0.5 or >=3.5, correlation<0.50, max signal holding20, or pair deselection; evaluated daily
- **gross:** 2*risk_per_pair initial component gross, netted book scaled to target gross0.60 before caps; nonzero net permitted within limits
- **minimum_hold:** none; max holding20 signal-state sessions (not a promise of 20 filled sessions)
- **signal:** spread=A-beta*B; trailing OLS covariance/variance beta252; trailing spread z60
- **sizing:** quantities k*(+1,-beta) long or k*(-1,+beta) short; positive beta; common proportional risk/execution scale; atomic book reject

Risk limits are unchanged: portfolio target volatility 10%, gross 1.5, absolute net 1.0, per-name 15%, sector 40%, daily loss 2% triggering a 50% reduction, portfolio drawdown 20%, strategy drawdown 12%; leverage-up disabled for directional books. S02 retains its stricter 4% allocation cap. Caps constrain approved allocations, not a promise that closing marked weights never drift above their original allocation.
Each separate account starts with $1,000,000. Adjusted research prices, next-session open, modeled commission 1bp + half-spread 2bp + slippage 2bp per side; no impact/minimum commission. Cash interest 0; negative cash cannot be freely financed. S03 base borrow 50bp annual on carried net shorts /252. Capacity is disabled in the frozen base; zero capacity-limited orders does not establish real-world liquidity.

## Base verified performance

| Strategy | Starting equity | Ending equity | Total return | CAGR | Volatility | Sharpe | Sortino | Max drawdown |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S01 | 1,000,000.00 | 952,481.82 | -4.75% | -0.30% | 2.23% | -0.12 | -0.16 | -12.28% |
| S02 | 1,000,000.00 | 1,365,254.27 | 36.53% | 1.92% | 2.52% | 0.77 | 1.05 | -4.33% |
| S03 | 1,000,000.00 | 970,385.60 | -2.96% | -0.18% | 0.54% | -0.34 | -0.45 | -4.52% |

CAGR/volatility use 252 sessions/year. Sharpe has a zero hurdle. Sortino uses RMS negative returns across all sessions; undefined ratios remain null, never zero. First-day losses and pre-window equity are included. Full-period results include warm-up and idle cash.

| Strategy | One-way turnover | Annual turnover | Nonzero filled orders | Rejected | Capacity limited | Avg gross / net | Max gross / abs net | Avg nonzero / max name exposure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S01 | 31.92 | 1.95 | 248 | 0 | 0 | 9.05% / 9.05% | 90.55% / 90.55% | 14.62% / 17.42% |
| S02 | 26.45 | 1.62 | 1060 | 0 | 0 | 15.07% / 15.07% | 23.98% / 23.98% | 4.00% / 6.07% |
| S03 | 22.70 | 1.39 | 368 | 0 | 0 | 3.07% / -0.07% | 61.90% / 20.11% | 11.76% / 15.90% |

## Dollar P&L reconciliation

| Strategy | Market P&L | Dividend cash | Cash interest | Financing | Borrow | Transaction cost | Net P&L | Compounding error ($) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S01 | -31,188.25 | 0.00 | 0.00 | 0.00 | 0.00 | -16,329.93 | -47,518.18 | 1.4e-09 |
| S02 | 380,477.98 | 0.00 | 0.00 | 0.00 | 0.00 | -15,223.71 | 365,254.27 | 3.49e-09 |
| S03 | -17,107.09 | 0.00 | 0.00 | 0.00 | -1,272.52 | -11,234.79 | -29,614.40 | 9.31e-10 |

Cost columns are signed deductions. Starting equity plus these components equals ending equity. Explicit dividend cash is zero because adjusted prices already contain the research adjustment. Every daily return, ledger event and marked quantity was reconciled, including all cost scenarios.

| Strategy | Commission | Modeled spread | Additional slippage | Impact |
| --- | --- | --- | --- | --- |
| S01 | 3,265.99 | 6,531.97 | 6,531.97 | 0.00 |
| S02 | 3,044.74 | 6,089.48 | 6,089.48 | 0.00 |
| S03 | 2,246.96 | 4,493.92 | 4,493.92 | 0.00 |

## Legacy versus corrected

**Legacy / non-certified:** stored outputs are shown as historical claims, not as authoritative performance. Their reported CAGR is inconsistent with their own ending equity.

| Strategy | Legacy equity | Corrected equity | Legacy return | Corrected return | Legacy stated CAGR | Legacy equity-implied CAGR | Corrected CAGR | Legacy Sharpe | Corrected Sharpe |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S01 | 1,243,604.77 | 952,481.82 | 24.36% | -4.75% | 1.59% | 1.34% | -0.30% | 0.35 | -0.12 |
| S02 | 1,385,444.13 | 1,365,254.27 | 38.54% | 36.53% | 2.09% | 2.01% | 1.92% | 0.82 | 0.77 |
| S03 | 1,018,722.60 | 970,385.60 | 1.87% | -2.96% | 0.20% | 0.11% | -0.18% | 0.25 | -0.34 |

Confirmed mechanisms affecting comparability: Phase 1 actual cash/quantity economics, rejected fills, next-open timing, exactly-once net costs and quantity drift; Phase 3A explicit calendars/funding/borrow; Phase 3B daily actual-held exits, adjusted ATR inputs, eligible-only rankings and S03 quantity hedges. Current runs reject no orders, so current rejected-order counts do not prove how much historical rejected-order handling contributed.
Interest and financing remain zero, so their newly explicit frameworks add no direct dollar contribution here. Short borrow does contribute to S03. Capacity is disabled and impact zero, so no capacity cap or impact penalty drives these base results. There is no defensible exact dollar decomposition of every historical fix: the old code/config/data retrieval histories and stored accounting are insufficient for an isolated causal attribution. Worse corrected performance is evidence about the frozen strategy, not a reason to restore invalid accounting.

## Chronological evidence — previously observed periods

| Strategy | Period | Return | Drawdown | Annual turnover | Mean gross / net | Filled orders | Trading / borrow cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S01 | 2010-2014 | 0.51% | -8.64% | 5.04 | 25.22% / 25.22% | 189 | 12,985.31 / -0.00 |
| S01 | 2015-2019 | -5.23% | -6.75% | 1.35 | 4.41% / 4.41% | 59 | 3,344.62 / -0.00 |
| S01 | 2020-2026 | 0.00% | 0.00% | 0.00 | 0.00% / 0.00% | 0 | -0.00 / -0.00 |
| S02 | 2010-2014 | 8.70% | -3.60% | 1.32 | 12.57% / 12.57% | 266 | 3,404.25 / -0.00 |
| S02 | 2015-2019 | 6.48% | -3.40% | 1.72 | 16.25% / 16.25% | 348 | 4,786.70 / -0.00 |
| S02 | 2020-2026 | 17.95% | -4.33% | 1.77 | 16.11% / 16.11% | 446 | 7,032.77 / -0.00 |
| S03 | 2010-2014 | 1.24% | -0.35% | 1.07 | 2.92% / -0.04% | 84 | 2,686.77 / 371.34 |
| S03 | 2015-2019 | -3.36% | -3.70% | 1.93 | 4.55% / -0.25% | 164 | 4,776.46 / 593.04 |
| S03 | 2020-2026 | -0.82% | -0.95% | 1.22 | 2.03% / 0.04% | 120 | 3,771.57 / 308.14 |

Windows inherit preceding cash, positions, warm-up and risk state. They are not independently reset or optimized accounts.

## Expanding-history walk-forward boundaries

| Strategy | Measurement dates | Return | Drawdown | Annual turnover | Mean gross | Filled orders | Total trading/borrow cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S01 | 2013-04-15 — 2016-07-19 | -10.41% | -12.28% | 6.19 | 26.74% | 149 | 10,231.22 |
| S01 | 2016-07-20 — 2019-10-24 | 0.00% | 0.00% | 0.00 | 0.00% | 0 | -0.00 |
| S01 | 2019-10-25 — 2023-02-01 | 0.00% | 0.00% | 0.00 | 0.00% | 0 | -0.00 |
| S01 | 2023-02-02 — 2026-05-14 | 0.00% | 0.00% | 0.00 | 0.00% | 0 | -0.00 |
| S02 | 2013-04-15 — 2016-07-19 | 6.63% | -3.40% | 1.44 | 16.27% | 215 | 2,522.03 |
| S02 | 2016-07-20 — 2019-10-24 | 4.62% | -3.16% | 1.85 | 16.16% | 231 | 3,393.49 |
| S02 | 2019-10-25 — 2023-02-01 | 7.89% | -4.33% | 1.78 | 16.19% | 232 | 3,490.28 |
| S02 | 2023-02-02 — 2026-05-14 | 10.16% | -4.17% | 1.72 | 16.03% | 224 | 3,638.03 |
| S03 | 2013-04-15 — 2016-07-19 | -1.52% | -2.45% | 1.66 | 4.40% | 100 | 3,079.78 |
| S03 | 2016-07-20 — 2019-10-24 | -1.28% | -1.28% | 1.64 | 3.67% | 84 | 2,949.29 |
| S03 | 2019-10-25 — 2023-02-01 | -0.41% | -0.61% | 1.27 | 1.87% | 70 | 2,186.52 |
| S03 | 2023-02-02 — 2026-05-14 | -0.28% | -0.74% | 1.10 | 2.09% | 50 | 1,895.80 |

These reuse the existing four expanding-history boundaries on the continuous causal engine path. No fold-specific parameter fit or risk reset occurs. The helper leaves its initial history segment and last three sessions outside the four diagnostic measurement blocks; the full run and three main chronological periods include all 4,119 sessions. This is not untouched OOS.

## Deterministic cost and borrow sensitivity

| Strategy | Scenario | Ending equity | Return | Sharpe | Trading cost | Borrow cost | Filled orders |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S01 | base | 952,481.82 | -4.75% | -0.12 | 16,329.93 | -0.00 | 248 |
| S01 | trading_0x | 957,579.47 | -4.24% | -0.11 | -0.00 | -0.00 | 248 |
| S01 | trading_2x | 948,687.67 | -5.13% | -0.13 | 31,573.85 | -0.00 | 242 |
| S02 | base | 1,365,254.27 | 36.53% | 0.77 | 15,223.71 | -0.00 | 1060 |
| S02 | trading_0x | 1,383,402.88 | 38.34% | 0.80 | -0.00 | -0.00 | 1060 |
| S02 | trading_2x | 1,347,340.81 | 34.73% | 0.74 | 30,239.75 | -0.00 | 1060 |
| S03 | base | 970,385.60 | -2.96% | -0.34 | 11,234.79 | 1,272.52 | 368 |
| S03 | borrow_0bp | 971,630.89 | -2.84% | -0.32 | 11,242.71 | -0.00 | 368 |
| S03 | borrow_100bp | 969,141.88 | -3.09% | -0.35 | 11,226.88 | 2,543.44 | 368 |
| S03 | trading_0x | 981,461.49 | -1.85% | -0.21 | -0.00 | 1,278.79 | 368 |
| S03 | trading_2x | 959,432.51 | -4.06% | -0.46 | 22,345.75 | 1,266.29 | 368 |

Zero trading cost retains S03 base borrow. Borrow 0/100bp scenarios retain base trading fees. Only specified charge assumptions change; S01 entry cost screening stays at base. Cost-driven changes to equity, quantities and risk pause timing are economic feedback, so ending-equity differences need not equal the arithmetic fee difference.

## Strategy diagnostics

### S01

108 completed holding episodes; 0 terminal open episodes; median completed duration 22.00 sessions. Candidate trend-state persistence 97.90%. The five largest profitable episodes contribute 41.66% of positive episode gains.
Episodes shorter than 20 inclusive sessions contribute $-211,103.26; longer episodes contribute $163,585.08. This is descriptive holding-duration attribution, not a minimum-hold optimization. Hard stops and central risk may override soft holds. There are 81 off-cycle exit/risk decisions.
Actual holdings are active on 973 sessions; the last active close is 2015-11-23. The existing 12% drawdown pause leads to prolonged flat cash after the breach; no reset/re-entry rule is invented. Inactive subsequent periods are not successful strategy tests. The zero-cost outcome must be considered alongside the charged outcome.
Largest positive ETF contributor share: 56.79%. Net dollar contribution by ETF:

| ETF | Net P&L |
| --- | --- |
| TLT | 39,815.30 |
| DIA | 9,453.48 |
| IEF | 9,030.30 |
| SPY | 7,300.08 |
| UUP | 4,516.19 |
| QQQ | -6,373.23 |
| IWM | -17,270.98 |
| GLD | -24,493.71 |
| SLV | -69,495.62 |

### S02

Mean daily adjacent score-rank correlation 0.96; average active holding breadth 4.03; mean active holdings HHI 0.25. Largest positive ETF contribution share 13.76%.
Pre-ranking eligibility changes the selected set in 0 of 184 examined monthly decisions relative to post-ranking masking at the same decision-time inputs. This isolates the ranking-eligibility diagnostic; it is not a separate legacy-accounting performance backtest.
Net dollar contribution by ETF:

| ETF | Net P&L |
| --- | --- |
| XLK | 50,243.41 |
| GLD | 48,158.91 |
| QQQ | 40,104.63 |
| XLE | 39,417.07 |
| SLV | 38,962.31 |
| XLV | 33,977.84 |
| XLI | 22,781.55 |
| XLY | 21,102.76 |
| XLF | 18,315.40 |
| XLU | 12,440.51 |
| IWM | 10,194.73 |
| XLP | 9,420.47 |
| XLB | 5,871.62 |
| DIA | 5,286.36 |
| TLT | 4,234.90 |
| IEF | 3,228.31 |
| XLRE | 1,460.72 |
| SPY | 52.77 |

Executed-holdings-weighted eligible percentile factor exposures:

| Factor | Average percentile exposure |
| --- | --- |
| liquidity | 0.60 |
| low_volatility | 0.51 |
| momentum_12m_ex_1m | 0.85 |
| momentum_3m | 0.64 |
| one_month_reversal | 0.53 |

Nonlinear composite ranks have no unique additive factor P&L. Held-factor ranks are exposure diagnostics, not independent funded factor returns.

### S03

Selected pairs: GLD / SLV, IAU / SLV, IVV / DIA, IVV / VOO, IWM / VTWO, QQQ / XLK, SPY / DIA, SPY / IVV, SPY / VOO, VOO / DIA, XLE / XOP, XLF / KBE. Completed pair episodes: 55; median episode duration 11.00 sessions. Largest positive pair contribution share 98.63%.
Accepted virtual pair quantities sum to actual netted holdings; fees allocated by absolute component deltas; net-short borrow allocated to short contributors. Not separate capital ledgers.
Selected candidates and executed pairs differ: pairs selected without an entry signal produce no fictitious trade. Pooled beta means across different ETF pairs are not a beta-stability test; the per-pair ranges/SDs are the meaningful drift diagnostics.
The beta=2 hedge earns zero pre-cost P&L for delta-A=2, delta-B=1 per unit scalar; equal-dollar legs generally do not. Observed pair P&L below is calculated from accepted executed component quantities and reconciles to actual account P&L, not from an equal-dollar spread proxy.

| Pair | Market P&L | Trading cost | Borrow | Net P&L | Active sessions | Beta min/max | Beta SD |
| --- | --- | --- | --- | --- | --- | --- | --- |
| GLD / SLV | -2,165.39 | 639.54 | 87.53 | -2,892.47 | 41 | 2.73 / 4.95 | 0.88 |
| IAU / SLV | -2,298.28 | 603.14 | 80.96 | -2,982.39 | 37 | 0.55 / 0.97 | 0.17 |
| IVV / DIA | 738.65 | 614.92 | 43.04 | 80.68 | 42 | 0.89 / 1.79 | 0.25 |
| IVV / VOO | 62.37 | 293.51 | 37.12 | -268.26 | 18 | 1.05 / 1.06 | 0.00 |
| QQQ / XLK | 1,498.31 | 2,195.45 | 316.36 | -1,013.51 | 113 | 3.34 / 5.44 | 0.65 |
| SPY / DIA | -859.66 | 1,046.93 | 87.22 | -1,993.81 | 59 | 0.88 / 1.79 | 0.26 |
| SPY / IVV | 71.33 | 148.23 | 12.98 | -89.88 | 9 | 1.03 / 1.03 | 0.00 |
| VOO / DIA | 357.11 | 449.39 | 29.16 | -121.44 | 32 | 0.81 / 1.64 | 0.20 |
| XLE / XOP | -21,941.96 | 3,754.67 | 451.82 | -26,148.45 | 192 | 0.06 / 0.26 | 0.04 |
| XLF / KBE | 7,430.43 | 1,489.00 | 126.33 | 5,815.11 | 55 | 0.19 / 0.58 | 0.14 |

Diagnostics at actual causal selection dates (selected candidates only; these are selection statistics, not independent proof of cointegration):

| Statistic | Mean | Minimum | Maximum |
| --- | --- | --- | --- |
| beta | 1.82 | 0.06 | 6.61 |
| coint_pvalue | 0.04 | 0.00 | 0.10 |
| correlation | 0.93 | 0.75 | 1.00 |
| half_life | 9.35 | 2.43 | 26.84 |

## Research history, status and limitations

The whole source period is previously observed development/research data. Reports and scripts explicitly examined the same three subperiods, many factor weights, individual factors, binary/conviction trends and multiple pairs. Untouched OOS does not exist in the available evidence; a demonstrably observed-but-untuned holdout cannot be established. No current period is relabeled fresh validation merely because it is in a walk-forward table.

| Strategy | Status | Failed predefined gates |
| --- | --- | --- |
| S01 | RESEARCH-REJECTED | base_positive, double_cost_positive, chronological_stability, contribution_breadth |
| S02 | RESEARCH-VALIDATED | none |
| S03 | RESEARCH-REJECTED | base_positive, double_cost_positive, chronological_stability, contribution_breadth |

The predefined gates require 5 years, 30 completed episodes, positive base and 2x returns, two positive main periods, drawdown<=20%, and no single positive contributor above 50%. Rejection requires nonpositive base and 2x results and at most one positive main period. Otherwise evidence is uncertain. These are transparent descriptive triage rules, not statistical confidence claims.
Nominal observation length is 16.35 trading years; effective active samples may be much smaller. Episodes and pairs overlap and are not independent draws. Historical variant testing, universe selection and surviving ETFs bias interpretation. Positive Sharpe or CAGR does not establish alpha, and frozen daily execution does not establish scalable liquidity. The S02 factor composite lacks unique additive factor P&L; S03 overlapping pairs lack independent capital accounts.

- All periods previously examined; no demonstrable untouched OOS or untuned validation period.
- Fixed surviving ETF universe; selection and multiple-testing history; no point-in-time universe reconstruction.
- Legacy normalized cache bytes verified; original provider response/retrieval metadata absent; origin not independently authenticated.
- Adjusted research accounting, not raw-share dividend/corporate-action or live broker reconciliation.
- Daily next-open modeled execution; no observed bid/ask/depth; default capacity disabled, no scale-up capacity certification.
- Interest disabled, financing prohibited, S03 fixed borrow 50bp on carried net shorts /252; no locate or historical borrow data.
- No combined funded multi-strategy ledger; combined certification deferred.
- Performance triage is descriptive, not alpha proof; chronological windows are diagnostic, not fresh OOS.
- Full periods include warm-up and idle cash; annualization 252 sessions; risk-free hurdle zero.
- Final positions remain marked open, without invented terminal liquidation costs.

## Reproducibility and acceptance

All 11 predefined runs passed cash/quantity/mark, daily P&L-component and equity-return reconciliation. Actual symbol episodes and S03 pair attributions reconcile to executed holdings/costs. The source/configuration/legacy-output guards and output manifest checks passed. Strategy code, risk/accounting engines, market data, parameter values and dependencies remain unchanged. No combined-strategy certificate is issued.
Generated data and detailed run files remain in ignored `runs/phase3c/`; only portable freeze metadata, small summary evidence, code/tests and documentation belong in Git. See `phase3c_research_protocol.md` for exact offline reproduction commands. A second machine needs separately restored hash-identical source blobs; a code clone alone intentionally contains no market data.
The Phase 3C research-reproducibility acceptance criterion is satisfied conditional on the declared legacy-data and execution conventions. Research rejection/uncertainty is an allowed result, not a failed accounting certificate. No Phase 4 work has started.

## Exact verification results

| Check | Passed | Skipped | Failed | Warnings | Collection errors |
| --- | --- | --- | --- | --- | --- |
| Full suite | 1558 | 14 | 0 | 0 | 0 |
| Phase 1A (full-suite subset) | 38 | 0 | 0 | 0 | 0 |
| Phase 1B (full-suite subset) | 65 | 0 | 0 | 0 | 0 |
| Phase 1C (full-suite subset) | 75 | 0 | 0 | 0 | 0 |
| Phase 2B (full-suite subset) | 42 | 0 | 0 | 0 | 0 |
| Phase 2C (full-suite subset) | 20 | 0 | 0 | 0 | 0 |
| Phase 3A (full-suite subset) | 44 | 0 | 0 | 0 | 0 |
| Phase 3B (full-suite subset) | 44 | 0 | 0 | 0 | 0 |
| Phase 3C focused | 23 | 0 | 0 | 0 | 0 |
| S01/S02/S03 existing strategy and analytics modules (full-suite subset) | 59 | 0 | 0 | 0 | 0 |

Final full-suite elapsed seconds: 360.74.
The 14 skips are existing SEC-cache-dependent tests without populated local company caches. No economically correct assertion was weakened.

Dependency checks: Python 3.12.10; uv 0.11.8; uv lock --check --offline resolves 72 packages; uv pip check: all 72 compatible; uv sync --locked --offline --all-extras --group dev --dry-run: no changes.

Test-first history: The initial new reporting interface failed collection before implementation. The missing-held-mark reporting regression failed before its guard. Complete-freeze tuple serialization and report-directory guard regressions failed before correction/implementation. A real fresh-checkout rehearsal reproduced12 code/config byte-hash mismatches from Git newlines, followed by a failing newline portability regression and a passing byte-exact market-input control. The research-only fingerprint correction passed all23 focused tests and all1558 full-suite tests with14 existing cache skips. No economic assertion or strategy setting was weakened.

## Files changed

- `.gitattributes`
- `README.md`
- `docs/phase3c_research_protocol.md`
- `docs/phase3c_research_report.md`
- `scripts/report_phase3c.py`
- `src/quantbot/research/certification.py`
- `src/quantbot/research/phase3c.py`
- `tests/test_phase3c_research.py`
- `research/phase3c/phase3c-20260918-v3/freeze.json`
- `research/phase3c/phase3c-20260918-v3/summary.json`
- `research/phase3c/phase3c-20260918-v3/run_identity.json`
- `research/phase3c/phase3c-20260918-v3/repeatability.json`
- `research/phase3c/phase3c-20260918-v3/verification.json`

Source/test/documentation and small portable metadata only are eligible for Git. Market inputs, large generated ledgers and databases remain untracked. Original OneDrive source hashes were rechecked. Phase1/2/3A/3B production modules and locked dependencies are unchanged.
