> **Research status:** Performance claims and files under `reports/backtests/` and `reports/core/` are preserved **legacy / non-certified** results. Phase 3C uses separate frozen specifications and reconciled runs; see [the research protocol](docs/phase3c_research_protocol.md) and [Phase 3C results](docs/phase3c_research_report.md). No historical result is proof of alpha or live readiness.

> **S05 current implementation:** Phase 4B adds the explicitly approved, frozen defined-risk short-volatility research strategy. Its dedicated offline runner is separate from generic equity activation flags. See [S05 conventions](docs/phase4b_s05.md) and [bounded results](docs/phase4b_s05_results.md). Historical milestone statements below remain historical.

# quant_trading_bot — Quantitative Trading **Research / Backtesting** Bot

> **Research and backtesting only. This project does NOT trade.**
> There is no broker connectivity and no live order execution anywhere in the
> codebase. `quantbot.LIVE_TRADING_ENABLED` is hard-coded to `False` and the
> simulated broker refuses to run if it is ever flipped. **No profitability is
> promised.** Backtested results — especially on synthetic data — are
> illustrative only and do not predict real-world performance.

A modular Python research stack that turns ideas from *Inside the Black Box*,
*Options, Futures, and Other Derivatives*, and *Option Volatility & Pricing*
into testable, cost-aware, look-ahead-safe backtests.

---

## 1. What is implemented (v1)

| Strategy | Status | Side | Rebalance | Notes |
|---|---|---|---|---|
| **S01** Multi-Asset Vol-Targeted Trend Following | ✅ active | long-only | weekly | inverse-vol sizing, ATR trailing stop, cost filter |
| **S03** Pairs / Stat-Arb Mean Reversion | ✅ active | hedge-ratio matched (long+short ETF legs) | weekly | **monthly walk-forward pair reselection**, borrow cost on short leg |
| **S02** Cross-Sectional Factor Blend | ✅ active | long-only | monthly | price-only factors (v1 limitation) |
| S04 Carry / Term Structure | ⛔ inactive | — | — | needs futures-chain data (not available v1) |
| **S05** Implied-versus-realized volatility | research only | defined-risk short-vol condor | weekly entry / daily exits | frozen Phase 4B rules; one observed SPY trade, QQQ IV history insufficient |
| S06-S08 Options vol strategies | inactive | - | - | no strategy implementation |
| S09 Synthetic Arbitrage Scanner | 🔍 scanner only | — | — | flags parity/box/convexity violations; never auto-trades |
| S10 Tail Hedge Overlay | ⛔ inactive | — | — | risk overlay, not standalone alpha |

### Strategy roles (V2.3 — evidence-based, see `scripts/research_edge.py`)

After V2.2 falsification diagnostics on real yfinance data:

| Strategy | Role (`role` in strategy_configs.json) | Why |
|---|---|---|
| **S02** factor blend | **`core`** | Robust on every test: all 5 price factors individually positive, stable across 2010‑14/15‑19/20‑26 sub‑periods, ~weight‑insensitive (100% of random factor‑weightings Sharpe>0). Sharpe ≈0.82. The book to run. |
| **S01** trend following | **`satellite_experimental`** | Real trend premium (per‑trade net‑PnL skew +7.25; long‑held trades carry all the gains) but a churn tax suppresses it. Run only as an experimental satellite; a config‑flagged conviction mode is under research. |
| **S03** pairs | **`research_only_no_alpha`** | Falsified: **0 of 13** same‑sector ETF pairs survive a strict OOS + cost bar (best full net −1.2%). Near‑identical clones have ~0 spread after costs; sector twins don’t mean‑revert. **Not traded as alpha.** |

Use `scripts/run_core.py` (S02 core, S01 satellite, S03 excluded) and
`scripts/report_s02.py` (deep S02 attribution + robustness). S01’s opt‑in
conviction experiment is **off by default** (`s01_execution_mode: "binary"`);
no numeric defaults changed.

#### V2.4 stabilization checkpoint (frozen baseline before V3)

This is the stable checkpoint after V2.3. **No new strategies / options /
broker / live trading; no default strategy parameters changed.** State:
- **101 tests pass** (`python -m pytest`) — 93 V2.4 + 8 V3 analytics.
- Roles fixed: S02 `core`, S01 `satellite_experimental`, S03 `research_only_no_alpha`.
- Hard guard intact: `quantbot.LIVE_TRADING_ENABLED is False`; `SimulatedBroker`
  refuses to run if flipped. S05–S10 remain inactive `NotImplementedError` stubs.
- Report snapshots archived: `reports/_v1_archive`, `reports/_v2_archive`,
  `reports/_v23_archive` (V2.3→V2.4 snapshot + `CHECKPOINT.txt`); live reports
  in `reports/backtests` and `reports/core/s02_attribution.md`.
- Canonical entry points: `scripts/run_core.py`, `scripts/report_s02.py`,
  `scripts/research_edge.py` (read-only diagnostics).

#### V3 — S02 core analytics layer (reporting only)

Pure read-only analytics for the S02 core strategy; **no strategy logic,
defaults, config, broker, live, or options changes**. Module
`src/quantbot/reporting/s02_analytics.py` (ETF contribution, factor analysis,
regime analysis, risk analysis, benchmark analysis). Run
`python scripts/report_s02_v3.py` to produce:
- `reports/core/s02_v3_report.md`, `reports/core/s02_v3_metrics.json`
- `reports/core/s02_v3_tables/*.csv` (14 tables)
- `reports/figures/s02_v3/*.png` (7 figures)

Per-symbol contribution exactly reconstructs `result.returns`; risk
contribution sums to annualized portfolio vol. Key reads: S02 is a low-beta
(~0.11), downside-protective, cash-plus book — e.g. in 2022 S02 ≈ +0.9% vs
SPY ≈ −18%; factor edge is weight-robust (`edge_is_robust = True`).
**101 tests pass.**

##### V3 stabilization checkpoint (frozen baseline before V4)

V3 (reporting-only) is now frozen. **Nothing strategy-side changed.** State:
- 101 tests pass; `report_s02_v3.py` regenerates deterministically.
- Guards verified: `LIVE_TRADING_ENABLED is False`; no broker/live/options
  code; S05–S10 still inactive `NotImplementedError` stubs.
- Roles unchanged: S02 `core`, S01 `satellite_experimental`,
  S03 `research_only_no_alpha`.
- V3 snapshot archived: **`reports/_v3_archive/`** (core/, figures/,
  `CHECKPOINT.txt`). Archive lineage: `_v1_archive`, `_v2_archive`,
  `_v23_archive`, `_v3_archive`. Live outputs remain under `reports/core/`
  and `reports/figures/s02_v3/`.

##### V4 historical options data integration — checkpoint (frozen baseline before V5)

V4 added a **historical** options data layer for future options research.
**Nothing strategy-side changed.** State:
- **Provider:** ThetaData **Options Standard**, via the local Theta Terminal
  **v3** at `http://127.0.0.1:25503`. Credentials handled out-of-band by
  `creds.txt` next to the Terminal jar — this codebase never reads, prints,
  or writes credentials.
- **Endpoints used:** `/v3/option/list/expirations`, `/v3/option/history/eod`
  (price bulk via `expiration=*`), `/v3/option/history/greeks/eod` (per
  expiration; verified Options-Standard accessible). The Pro-only
  `/greeks/all` endpoint is intentionally **not** called.
- **Samples downloaded** (`max_dte=30`, EOD + Greeks enrichment):
  - SPY 2022-01-03 → 2022-01-31 — 66,536 canonical rows
  - QQQ 2022-01-03 → 2022-01-31 — 65,388 canonical rows
  - SPY 2022-02-01 → 2022-02-28 — 74,776 canonical rows
- **Coverage:** IV ≈ 85–87% non-NaN across all samples (deep-ITM/wing rows
  correctly mapped to NaN); Greeks (delta/gamma/theta/vega/rho) **100%**.
  Hard validator rejects: **0** on every sample.
- **137 tests pass**; guards verified — `LIVE_TRADING_ENABLED is False`,
  no broker/live/IBKR imports, no order execution, no options strategy or
  backtest engine added, S05–S10 still inactive `NotImplementedError` stubs.
- Canonical inputs for V5 live under `data/options/processed/<SYM>/YYYY/`.
  Snapshots + quality report + metadata archived in **`reports/_v4_archive/`**
  with `CHECKPOINT.txt`. Archive lineage now: `_v1_archive`, `_v2_archive`,
  `_v23_archive`, `_v3_archive`, **`_v4_archive`**.
- Entry points: `scripts/options_sample_workflow.py`,
  `scripts/options_enrich_greeks.py`, `scripts/options_quality_report.py`.

**Next stage:** V5 — options backtest **planning only** (no implementation,
no live trading, no broker).

##### V5.0 / V5.1 options backtest engine — proof-of-engine checkpoint

V5.0 added the central historical-options backtest engine and a single
proof strategy used solely to exercise the plumbing. V5.1 freezes that
state before any data widening or further strategy work. **Nothing
strategy-side outside the new options stack changed.** State:
- **173 tests pass** (`python -m pytest`) — V5 adds
  `tests/test_options_contract_selector.py`, `test_options_fill_model.py`,
  `test_options_spreads.py`, `test_options_backtest_engine.py`,
  `test_options_v5_causality.py`.
- New engine: `src/quantbot/options/backtest_engine.py` — enforces
  `decision_date < fill_date` on every order, marks open positions
  daily, settles expirations to intrinsic, force-closes the last bar,
  charges `OptionsCostModel` on every leg, and rejects `is_naked=True`
  candidates via `quantbot.options.risk.evaluate_candidate`.
- Proof strategy: `quantbot.options.strategies.spy_bull_call`
  (`SPYBullCallSpread`, debit vertical, weekly Monday decisions,
  next-day fills, DTE-exit / profit-target / stop rules). Defined-risk
  by construction.
- Driver: `scripts/run_options_backtest.py` — runs SPY 2022-01 + 2022-02
  end-to-end on the V4 local processed files (141,312 rows / 39
  trading days). Two consecutive runs produce byte-identical output.
- Run result (mechanics only, **not** a profitability conclusion): 3
  closed trades, 5 rejections (concurrency + per-trade debit caps),
  final equity $99,539.70 (−0.46%), max drawdown −0.63%, total cost
  $50.30. Engine self-check passes: causality True, all positions
  closed at final bar True.
- Guards verified: `LIVE_TRADING_ENABLED is False`, no broker / live /
  IBKR imports anywhere in the V5 code, no new data fetched in V5,
  no credentials read/printed/written, S05–S10 still inactive stubs.
- V5.0 outputs archived in **`reports/_v50_archive/`** with
  `CHECKPOINT.txt` and `v50_proof_run.txt`. Archive lineage now:
  `_v1_archive`, `_v2_archive`, `_v23_archive`, `_v3_archive`,
  `_v4_archive`, **`_v50_archive`**.

**V5.0 establishes engine correctness, not strategy profitability.**
Two months of one underlying with one debit-vertical structure is far
too narrow a sample to draw any conclusion about options strategy
edge. The next stage requires **wider historical options data** (longer
date range, broader DTE coverage, additional underlyings, and at least
one credit-side defined-risk structure for cross-validation) before any
strategy-quality claim is made. V5.x remains research/backtest only.

##### V5.2 Stage 1 — SPY 2022 H1 corpus checkpoint (data only, no strategy work)

V5.2 Stage 1 extends the SPY options corpus from the V4 baseline
(Jan–Feb 2022, `max_dte=30`) into the **2022 bear market through Q2**
at `max_dte=45`. **Nothing strategy-side changed.** State:
- **6 contiguous months on disk:** SPY 2022-01 → 2022-06,
  **124 trading days**, **566,018 canonical processed rows**, **22.3 MB**
  processed (`data/options/processed/SPY/2022/2022-{01..06}.csv.gz`).
  Jan/Feb at `max_dte=30` (V4); Mar/Apr/May/Jun at `max_dte=45` (V5.2).
- **Coverage:** validator hard rejects **0** on every monthly file;
  all-5 Greeks NaN-free **100%** on every month; IV non-NaN
  **84.83% – 89.97%** per month (deep-ITM/wings correctly NaN). NYSE
  holidays (MLK, Washington's Birthday, Good Friday, Memorial Day,
  Juneteenth) all handled transparently.
- **Pipeline edits this stage** (script-level only, no engine/strategy
  changes): `scripts/options_enrich_greeks.py` got two small
  resilience touches — skip per-expiration HTTP 472 / "no data"
  responses on edge-of-band expirations (added during the March
  sanity pull), and raise the loader's per-call timeout from 90 s to
  240 s (added after the June monthly OPEX timed out under the 2022
  vol spike). Neither edit changes a strategy parameter, an engine
  rule, or a risk default.
- **Known quirks documented in the checkpoint** (none block V5.3):
  EOD-bulk row duplication on certain mid-May/June days (does NOT
  reach the processed file; greeks endpoint dedupes by per-exp
  querying); multi-chunk EOD processed-file overwrite recoverable
  by the subsequent greeks pass.
- **173 tests pass** — same suite, no V5.2 test additions (data and
  one script constant; nothing engine-side to test).
- Guards verified: `LIVE_TRADING_ENABLED is False`, no broker / live
  / IBKR imports, no order execution, no new options strategies
  beyond V5.0's `spy_bull_call`, no credentials read/printed/written.
- V5.2 Stage 1 outputs archived in **`reports/_v52_stage1_archive/`**
  with `CHECKPOINT.txt`, aggregate quality report,
  `metadata_snapshot.json`, and `processed_manifest.json` (per-file
  row count, IV/Greeks coverage, and SHA-256 hash for every monthly).
  Archive lineage: `_v1_archive`, `_v2_archive`, `_v23_archive`,
  `_v3_archive`, `_v4_archive`, `_v50_archive`, **`_v52_stage1_archive`**.

**Next stage (V5.3):** run the existing V5.0 `OptionsBacktestEngine`
with the existing `SPYBullCallSpread` proof strategy AS-IS on the full
6-month corpus — per-month trade table, cumulative equity curve, sub-
period split, cost sensitivity sweep, rejection analytics, daily
Greeks aggregates. Purpose: stress-test the engine on a realistic
regime, **not** validate strategy edge. Stage 2 / Stage 3 of the data
expansion (out to 2023) remain pending separate approval.

##### V5.3 options strategy testing checkpoint (mechanics, not edge)

V5.3 cross-validates the V5.0 engine across **three defined-risk vertical
spreads** on the frozen V5.2 Stage 1 SPY corpus. **No new data was
fetched, no engine logic changed, no V5.0-strategy defaults changed.**
State:
- **186 tests pass** (`python -m pytest`) — was 173 after V5.2 Stage 1;
  V5.3 adds **+12 spread-builder tests** (`tests/test_options_spreads.py`)
  covering defined-risk identity, leg-sign correctness, debit/credit
  pricing reconciliation, max-width strict bounds, and reject paths
  for bear put + bull put.
- **Two new defined-risk structures** added (additive only):
  `quantbot.options.spreads.build_bear_put_spread` (debit) and
  `build_bull_put_spread` (CREDIT; protective long-wing required by
  construction — naked-short-put is impossible). Both wired through
  the existing `OptionsBacktestEngine` and `OptionsRiskLimits` gates
  with no engine code change.
- **Two new strategies** (defaults conservative, OTM):
  `quantbot.options.strategies.spy_bear_put.SPYBearPutSpread` and
  `quantbot.options.strategies.spy_bull_put.SPYBullPutSpread`. Both
  mirror `SPYBullCallSpread`'s cadence and exit rules; only the
  directional bias differs.
- **Driver:** `scripts/run_options_v53.py` runs all 3 strategies
  back-to-back on the full Jan–Jun 2022 corpus and prints a
  side-by-side comparison. Output is byte-identical across two
  consecutive runs (engine has no RNG).
- **Comparative results** (mechanics only — NOT a strategy-edge
  conclusion; bear regime trivially favors bearish structures):

  | strategy | type | trades | rej | win % | total ret | max DD |
  |---|---|---:|---:|---:|---:|---:|
  | bull_call | DEBIT | 8 | 18 | 12.5% | −1.27% | −1.38% |
  | bear_put  | DEBIT | 10 | 16 | 70.0% | +0.65% | −0.44% |
  | bull_put  | CREDIT | 11 | 15 | 18.2% | −1.47% | −1.74% |

  Engine self-checks pass on all 3 runs: `decision_date < fill_date`
  on every order, zero open positions at final bar, Greeks signatures
  directionally correct per structure type.
- Guards verified: `LIVE_TRADING_ENABLED is False`, no broker / live /
  IBKR imports anywhere in `src/` or `scripts/`, no order execution,
  no naked / unlimited-risk structures (`is_naked=True` never set;
  `allow_naked=True` never set), no new data fetched, no ThetaData
  calls, no credentials read/printed/written.
- V5.3 outputs archived in **`reports/_v53_archive/`** with
  `CHECKPOINT.txt` and `v53_run.txt` (full captured driver output).
  Archive lineage: `_v1_archive`, `_v2_archive`, `_v23_archive`,
  `_v3_archive`, `_v4_archive`, `_v50_archive`, `_v52_stage1_archive`,
  **`_v53_archive`**.

**V5.3 is a mechanics + credit-side-accounting verification, not a
profitability conclusion.** Six months of one underlying with three
structures and unchanged defaults is far too narrow to claim edge for
any structure. The bear-put +0.65% is the mechanically consistent
outcome of a bear regime (SPY drew down from ~$478 to ~$365 over the
period), not evidence of strategy edge. The bull-call and bull-put
losses are likewise expected when bullish structures meet a bear tape.

**Next stage (V5.4):** robustness testing on the same frozen corpus
and same three strategies — cost-sensitivity sweep, liquidity-gate
sensitivity, concurrency-cap sensitivity, sub-period split,
rolling-window stability checks. No new data, no new strategies, no
engine logic changes, defaults still frozen.

##### V5.4 robustness diagnostics checkpoint (no edge established)

V5.4 runs robustness sensitivity sweeps against the same three V5.3
defined-risk verticals on the same frozen V5.2 Stage 1 SPY corpus. **No
new data, no engine logic changes, no V5.3 strategy default changes.**
State:
- **186 tests pass** (unchanged from V5.3; V5.4 added zero new tests
  because it only composes existing classes with parameter overrides).
- **Determinism preserved**: two consecutive runs of
  `scripts/run_options_v54.py` produce byte-identical artifacts across
  all 7 CSV/MD files (verified `diff -r`).
- **Baseline matches V5.3 archive exactly** — `bull_call −1.27%`,
  `bear_put +0.65%`, `bull_put −1.47%`. No engine state drift.
- **Cost-sensitivity sweep** (4 cost scenarios × 3 strategies = 12 runs):
  no strategy flips sign under any cost setting, but **bear_put's
  positive return is fragile** — total return shrinks from +0.90%
  (low_cost) to +0.20% (wide_bid_ask), a 4.5× collapse; Sharpe falls
  from +1.92 to +0.40 across the same range. A modest slippage
  assumption swing nearly erases the only positive signal.
- **Spread-filter sensitivity sweep** (3 thresholds × 3 strategies = 9
  runs): bear_put and bull_put are completely insensitive to
  `spread_max_pct ∈ {0.15, 0.25, 0.35}`; bull_call is meaningfully
  sensitive (strict 0.15 fires 121 extra fill-stage rejections), but
  the resulting "improvement" is noise on 7 trades.
- **Monthly / regime split**: bear_put wins 4 of 6 months (losses on
  counter-trend rallies in April and June); bull_call wins only March
  (the bear-market bounce); bull_put loses every single month.
- **Rejection analysis**: zero engine-level liquidity rejections across
  all three strategies — the dominant binding constraint is
  `max_concurrent_positions=1` (~12–15 rejections per strategy), then
  `debit_gt_500.0` (6 for bull_call, 1 for bear_put, 0 for bull_put).
- **Artifacts**: `reports/options/v54_robustness/v54_summary.md`,
  `baseline_results.csv`, `cost_sensitivity.csv`,
  `spread_filter_sensitivity.csv`, `monthly_breakdown.csv`,
  `trade_diagnostics.csv`, `rejection_analysis.csv`. Driver:
  `scripts/run_options_v54.py`. Output is reproducible by re-running
  the driver; the driver implements its own Markdown table formatter
  to avoid the `tabulate` package install.
- Guards verified: `LIVE_TRADING_ENABLED is False`, no broker / live /
  IBKR imports, no order execution, no new data fetched, no ThetaData
  calls, no new strategies, no naked / unlimited-risk constructs in
  production code, no credentials read/printed/written, no packages
  installed.
- V5.4 outputs archived in **`reports/_v54_archive/`** with
  `CHECKPOINT.txt` and the seven robustness artifacts. Archive lineage:
  `_v1_archive`, `_v2_archive`, `_v23_archive`, `_v3_archive`,
  `_v4_archive`, `_v50_archive`, `_v52_stage1_archive`, `_v53_archive`,
  **`_v54_archive`**.

**V5.4 establishes NO strategy edge.** The only positive baseline
(`bear_put +0.65%`) is regime-explained (bear-market period) and
cost-fragile (4.5× shrinkage under wider bid/ask). Bull_call and
bull_put losses in a bear regime are mechanically expected. Six months
of one underlying with 8–11 trades per strategy is far too small for
statistical claims. **Bear_put remains a candidate for wider-data
falsification**, not a strategy to deploy.

**Next stage (V5.5):** rolling-window stability analysis — re-run each
strategy starting from every week in Jan–Jun (~26 start offsets) and
report the distribution of total returns / Sharpe / drawdown / trade
counts. Test whether bear_put's +0.65% survives or collapses across
start-week shifts. Same frozen corpus, same three strategies, no new
data, no engine changes. Macro / company / news research layers come
**later**, only after options strategy stability is better understood
and a wider data corpus exists. V5.x remains research/backtest only.

##### V5.5 rolling-window stability checkpoint (bear_put sign-stable, magnitude-fragile)

V5.5 runs each of the three V5.3 defined-risk verticals on the same
frozen V5.2 Stage 1 corpus with the entry schedule shifted by 0..19 ISO
weeks (20 offsets per strategy, 60 total runs). **No new data, no
engine logic changes, no V5.3 strategy default changes, no parameter
overrides anywhere — only the chain start date is varied.**
State:
- **186 tests pass** (unchanged from V5.4; V5.5 added zero new tests).
- **Determinism preserved**: two consecutive runs of
  `scripts/run_options_v55.py` produce byte-identical artifacts across
  all 5 CSV/MD files (verified `diff -r`).
- **Baseline at offset 0 matches V5.4 archive exactly** for all three
  strategies (`bull_call −1.2658%`, `bear_put +0.6490%`, `bull_put
  −1.4701%`). Engine produces deterministic output across 60 fresh
  runs.
- **bear_put sign is stable, magnitude is fragile**:

  | metric | bear_put |
  |---|---:|
  | mean total return | **+0.254%** |
  | median total return | +0.253% |
  | std total return | **0.183%** (~72% of mean — noise ≈ signal) |
  | min total return | +0.004% (essentially flat after costs) |
  | max total return | +0.649% (= baseline = the **best** of all 20 starts) |
  | % runs positive | **100% (20/20)** |
  | mean max drawdown | −0.420% |

  The baseline +0.65% sits at the upper extreme of the distribution;
  18 of 20 alternative starts produce less than half the baseline
  return. Sign stability is consistent with a regime-explained
  outcome (a structurally bearish strategy run over a bear-market
  window), **not** independent evidence of edge — the 20 windows
  share most of the chain.
- **bull_call and bull_put are negative across all 20 shifted starts**
  (0% positive runs in each). This is mechanically expected for
  bullish structures in a bear regime and tells us nothing about
  their behaviour in other regimes.
- **Timing-sensitivity ranking** (by std of total return): bull_put
  (0.292%) > bull_call (0.274%) > bear_put (0.183%). bear_put is
  least timing-sensitive in absolute terms, consistent with being
  aligned with the dominant regime force.
- **Artifacts**: `reports/options/v55_stability/v55_summary.md`,
  `rolling_window_results.csv` (60 rows), `stability_summary.csv`,
  `shifted_trade_counts.csv`, `shifted_rejection_summary.csv`.
  Driver: `scripts/run_options_v55.py`.
- Guards verified: `LIVE_TRADING_ENABLED is False`, no broker / live /
  IBKR imports, no order execution, no new data fetched, no ThetaData
  calls, no new strategies, no naked / unlimited-risk constructs,
  no credentials read/printed/written, no packages installed.
- V5.5 outputs archived in **`reports/_v55_archive/`** with
  `CHECKPOINT.txt` and the 5 stability artifacts. Archive lineage:
  `_v1_archive`, `_v2_archive`, `_v23_archive`, `_v3_archive`,
  `_v4_archive`, `_v50_archive`, `_v52_stage1_archive`, `_v53_archive`,
  `_v54_archive`, **`_v55_archive`**.

**V5.5 establishes NO strategy edge.** bear_put's sign-stability is
necessary but far from sufficient evidence of edge — the 20 shifted
windows are highly correlated (they share most of the same chain),
the magnitude varies 160× (from +0.004% to +0.65%), and the std is
roughly the same order of magnitude as the mean. bull_call and
bull_put remain consistently negative because they are wrong-direction
in the test window by design.

**Next stage (V5.6):** non-overlapping window analysis on the same
frozen corpus and same three strategies. Split Jan–Jun 2022 into 2 or
3 strict non-overlapping windows; run each strategy independently on
each window with fresh capital; check whether bear_put remains
positive on each piece independently or whether its positivity is
concentrated in one or two months. This addresses the V5.5 caveat that
overlapping windows are not independent observations. Same hard
limits: no new data, no ThetaData, no new strategies, no engine logic
changes, no strategy default changes, no parameter optimization, no
broker / live / IBKR. Macro / news research layers still deferred
until the options stability picture is clearer.

##### V5.6 non-overlapping window checkpoint (5/5 independent windows survive directional pattern)

V5.6 runs each of the three V5.3 defined-risk verticals on
**independent, non-overlapping** sub-windows of the same frozen V5.2
Stage 1 SPY corpus, addressing the V5.5 caveat that shifted-start
windows share most of the data. Two splits run side-by-side on the
same chain: **3-way** (Jan-Feb / Mar-Apr / May-Jun) and **2-way**
(Jan-Mar / Apr-Jun), plus the full-period baseline as a sanity check.
**No new data, no engine logic changes, no strategy default changes,
no parameter overrides.** State:
- **186 tests pass** (unchanged from V5.5; V5.6 added zero new tests).
- **Determinism preserved**: two consecutive runs of
  `scripts/run_options_v56.py` produce byte-identical artifacts across
  all 5 CSV/MD files.
- **Full-period baseline matches V5.4 archive exactly**: `bull_call
  −1.2658%`, `bear_put +0.6490%`, `bull_put −1.4701%`.
- **bear_put positive in 5 of 5 independent non-overlapping windows**
  — sign survives partitioning:

  | split | window | bull_call | bear_put | bull_put |
  |---|---|---:|---:|---:|
  | 3-way | Jan–Feb (39 d) | −0.46% | **+0.55%** | −0.71% |
  | 3-way | Mar–Apr (43 d) | −0.19% | **+0.16%** | −0.31% |
  | 3-way | May–Jun (42 d) | −0.33% | **+0.10%** | −0.62% |
  | 2-way | Jan–Mar (62 d) | −0.44% | **+0.28%** | −0.80% |
  | 2-way | Apr–Jun (62 d) | −0.69% | **+0.15%** | −0.69% |

  bear_put range across independent windows: **+0.10% to +0.55%**.
  Full-period baseline +0.65% is **larger than any individual
  sub-window** (each sub-window force-closes at boundary, costing
  ~0.10–0.50 pp).
- **bull_call and bull_put negative in all 5 windows** — mechanically
  expected for bullish-direction strategies in a bear regime.
- **Regime-directional pattern** (`bear_put > 0 AND bull_call < 0 AND
  bull_put < 0`) holds in **5/5 windows** — cleanest possible
  regime-consistency signature for a bear-market test sample.
- **All 18 engine self-checks pass** (`decision_date < fill_date` on
  every order; force-close at window boundary works on every run).
- **Artifacts**: `reports/options/v56_nonoverlap/v56_summary.md`,
  `nonoverlap_results.csv` (18 rows), `window_summary.csv` (6 rows),
  `nonoverlap_trade_counts.csv`, `nonoverlap_rejection_summary.csv`.
  Driver: `scripts/run_options_v56.py`.
- Guards verified: `LIVE_TRADING_ENABLED is False`, no broker / live /
  IBKR imports, no order execution, no new data fetched, no ThetaData
  calls, no new strategies, no naked / unlimited-risk constructs, no
  credentials read/printed/written, no packages installed.
- V5.6 outputs archived in **`reports/_v56_archive/`** with
  `CHECKPOINT.txt` and the 5 non-overlap artifacts. Archive lineage:
  `_v1_archive`, `_v2_archive`, `_v23_archive`, `_v3_archive`,
  `_v4_archive`, `_v50_archive`, `_v52_stage1_archive`, `_v53_archive`,
  `_v54_archive`, `_v55_archive`, **`_v56_archive`**.

**V5.6 establishes NO strategy edge.** bear_put's 5/5 independent-window
positivity is *stronger* than V5.5's overlapping-window stability but
remains a regime artifact: every one of the 5 windows still sits inside
**one broad 2022 bear-market regime**. A directionally bearish strategy
should mechanically win in a bear regime regardless of how the period is
partitioned. bull_call and bull_put losses in all 5 windows are likewise
mechanically expected. The cumulative V5.3–V5.6 evidence on bear_put
amounts to *"consistent in this regime"* — not edge.

**Next stage (decision point — pick one):**

- **Path A (V5.7 macro/news context overlay)** — read-only annotation
  of existing V5.3–V5.6 trades with SPY %-change during the holding
  period, VIX level at entry/exit, and headline-event flags from a
  free static source. Useful for interpreting *when* bear_put wins vs
  loses, but cannot on its own falsify or validate edge. Small effort,
  no broker / live / new fetch.
- **Path B (V5.2 Stage 2 wider data fetch)** — extend SPY to
  2022-07 → 2023-06 at `max_dte=45` in monthly chunks using the
  existing V5.2 protocol. Forces bear_put through late-bear
  continuation, Q4 2022 rally, and 2023 H1 recovery — the only path
  that can actually falsify bear_put. Medium effort, ~5–6 hours wall
  clock split across sessions.
- **Path C (do nothing)** — V5.6 is the end of the analytics-only
  stack on the V5.2 Stage 1 corpus. No further passes against this
  6-month dataset would add genuinely new evidence; the bear regime
  is the binding constraint, not the analysis method.

**Recommendation (deferred to user approval):** Path B is the only
path that can actually falsify bear_put. Path A is a useful parallel
research-quality enhancement and can run before or after Path B.
Macro / news / company-research layers come **later** regardless of
which path is chosen. V5.x remains research/backtest only.

##### V5.7 read-only macro / market / news research layer checkpoint

V5.7 adds a **read-only research layer** that loads macro proxies,
optional FRED series, and a manual events CSV, and annotates strategy
trades with context — **without altering any strategy decision, engine
logic, or default parameter**. State:
- **210 tests pass** (was 186 after V5.6; **+24 new V5.7 tests** in
  `tests/test_v57_research_layer.py`, all toy-data only — no network,
  no broker).
- **Three new packages**: `quantbot.macro` (FRED loader + yfinance
  proxies + indicators + regime classifier), `quantbot.research`
  (price-move detection + trade-context annotation + reporting),
  `quantbot.events` (manual events CSV stub — no live news provider).
  Driver: `scripts/run_research_v57.py`.
- **V5.0 engine + V5.3 strategies + V5.4 / V5.5 / V5.6 drivers all
  byte-unchanged**. V5.7 is purely additive.
- **Data sources supported, this run:**
  - Existing ETF cache: SPY, TLT, IEF, GLD (4 / 7 proxies)
  - yfinance live fetch (cached): ^VIX, HYG, LQD, AAPL (4 new fetches)
  - FRED: **0 series** — `FRED_API_KEY` not set; loader degraded
    silently (no live HTTP calls issued; key never read into a
    printable variable).
  - Manual events: **0** — `data/events/manual_events.csv` absent;
    empty frame returned as designed.
- **AAPL example ran**: 2019-01-01 → 2024-12-31; strongest 21-day move
  +36.14% ending 2020-08-24; strongest 63-day move +65.38% over
  2020-06-03 → 2020-09-01 (post-COVID rally — matches historical
  context exactly).
- **SPY trade-context report ran**: re-ran all 3 V5.3 strategies on
  the frozen V5.2 Stage 1 corpus, producing **29 annotated trades**
  (10 bear_put + 8 bull_call + 11 bull_put), each annotated with SPY
  return in trade, VIX entry / change, HYG/LQD ratio, and regime
  labels. Textbook directional + vega signature confirmed:
  bear_put wins when SPY falls and VIX rises during the trade
  (mean SPY −3.51%, mean VIX change +2.80); bear_put loses on
  counter-trend rallies (mean SPY +2.61%, mean VIX change −5.65).
- **Determinism**: 6 of 9 artifacts byte-identical across re-runs;
  3 artifacts differ only at the 14th–15th decimal place (yfinance
  CSV-round-trip artifact in the proxy cache; Markdown summary
  applies `.4f` formatting and is byte-identical).
- **Artifacts**:
  `reports/research/v57_macro_context/v57_summary.md`,
  `data_availability_report.md`, `proxy_availability.csv`,
  `fred_availability.csv`, `macro_regime_snapshot.csv`,
  `strategy_trade_context.csv`, `win_loss_context_summary.csv`,
  `strongest_moves_context_SPY.csv`,
  `strongest_moves_context_AAPL.csv`.
- Guards verified: `LIVE_TRADING_ENABLED is False`; no broker /
  live / IBKR / order-execution imports in any new package
  (grep on actual `from ... import ...` statements; docstring
  mentions of "IBKR" allowed as guard wording); no new ThetaData
  fetches; no strategy / engine / default changes; `FRED_API_KEY`
  consulted via `os.environ.get(...)` only, masked from any error
  string; no packages installed.
- V5.7 outputs archived in **`reports/_v57_archive/`** with
  `CHECKPOINT.txt` and 9 artifacts. Archive lineage:
  `_v1_archive`, `_v2_archive`, `_v23_archive`, `_v3_archive`,
  `_v4_archive`, `_v50_archive`, `_v52_stage1_archive`, `_v53_archive`,
  `_v54_archive`, `_v55_archive`, `_v56_archive`, **`_v57_archive`**.

**V5.7 explains — it does not predict.** The annotation layer can
quantitatively answer "why did bear_put win on these specific trades?"
(SPY direction and VIX dynamics during the trade) but cannot turn a
regime artifact into edge. **Wider data (V5.2 Stage 2) remains the
only path to actually falsify the bear_put baseline.** An IBKR
research adapter is explicitly **deferred** to a future checkpoint and
is not part of V5.7.

**Next stage (decision point — pick one):**
- **Path A**: V5.2 Stage 2 wider data fetch (SPY 2022-07 → 2023-06 at
  `max_dte=45`) — the only path that can actually falsify bear_put.
- **Path B**: populate `data/events/manual_events.csv` with 2022 H1
  CPI / FOMC dates and re-run V5.7 — pure-data step, no new code,
  unlocks the `event_*_in_trade` columns.
- **Path C**: stabilization-only stop — freeze the research layer as
  built; no further analysis on this corpus would add new information.

V5.x remains research/backtest only. No broker, no IBKR, no live
trading.

##### V5.7 FRED rerun checkpoint (official macro data now integrated)

The V5.7 research layer was re-run with `FRED_API_KEY` available, so
**official FRED macro series now augment the yfinance/proxy context**.
**No strategy decision, default, or backtest result changed** — the
three strategy re-runs still reproduce the V5.3–V5.6 baselines exactly
(`bull_call −$1,265.80`, `bear_put +$649.00`, `bull_put −$1,470.10` on
$100k). State:
- **6 FRED series fetched + cached** under `data/macro/fred/`:
  DGS10, DGS2, T10Y2Y (daily); FEDFUNDS, CPIAUCSL, UNRATE (monthly).
  Atomic CSV writes; provenance in `data/macro/fred/metadata.json`
  (which contains **no API key**). Re-running the driver serves all 6
  from cache with **zero live FRED HTTP calls** (cache stable).
- **`rates` dimension now present** in the regime panel — every
  `macro_regime` label gained a `rates=up|stable|down` token (e.g.
  `trend=up|vol=mid|rates=up|credit=risk_on`). `strategy_trade_context.csv`
  now populates `dgs10_at_entry/exit/change` and `rates_at_entry` for
  all 29 trades.
- **New context insight** (descriptive, *not* a signal): bear_put
  losers entered when DGS10 was ~70 bp higher (~2.80% vs ~2.08% for
  winners) — the rate move had largely already priced in. With all 4
  regime dimensions populated, winner vs loser regime *modes* now
  separate (`trend=up|vol=mid|rates=up|credit=risk_on` for wins vs
  `trend=down|vol=high|rates=stable|credit=risk_off` for losses),
  refining V5.6's incomplete-dimension grouping.
- **210 tests pass** (unchanged suite).
- Guards verified: `LIVE_TRADING_ENABLED is False`; no broker / live /
  IBKR / order-execution imports; no ThetaData fetch (options
  metadata last fetch unchanged); no strategy / default / parameter
  changes; no trading signals; no package installs; `FRED_API_KEY`
  consulted via `os.environ.get(...)` only — never printed, logged,
  written to cache/metadata/reports, and masked in any error string
  (report mentions are the env-var name in guard wording, not the
  value).
- FRED-enabled outputs archived in **`reports/_v57_fred_archive/`**
  with `CHECKPOINT.txt`, the updated reports, and a FRED cache
  metadata snapshot. Archive lineage: …, `_v56_archive`,
  `_v57_archive` (no-FRED snapshot), **`_v57_fred_archive`**
  (FRED-enabled snapshot).

**The rates/DGS10 context is still annotation, not edge.** It describes
an existing single-regime artifact more completely; it does not predict
or trade. Next possible steps remain: **(A)** populate
`data/events/manual_events.csv`; **(B)** add an IBKR **read-only**
research adapter (separate module, own guardrails + tests; deferred
until separately approved); **(C)** proceed to V5.2 Stage 2 wider SPY
data expansion (the only falsification path). V5.x remains
research/backtest only.

##### V5.7 event-aware checkpoint (CPI / FOMC annotation, descriptive only)

The V5.7 research layer now annotates each strategy trade with **CPI /
FOMC event overlap**, driven by a manually-curated
`data/events/manual_events.csv` (13 events for SPY Jan–Jun 2022: 6 CPI
releases, 4 FOMC statements, 3 FOMC minutes). **Event overlap is
descriptive context only — it is NOT a trading signal, does NOT filter
trades, and does NOT change any strategy decision or P&L.** State:
- **219 tests pass** (was 210 after the FRED checkpoint; **+9 event
  tests**). The legacy `load_events` 3-column contract is unchanged;
  a new `load_events_detailed` preserves `event_name / source /
  importance`, and `annotate_event_overlap` / `summarize_event_overlap`
  add the richer columns.
- **Strategy P&L unchanged** — the three re-runs reproduce the V5.3–V5.6
  baselines exactly (`bull_call −$1,265.80`, `bear_put +$649.00`,
  `bull_put −$1,470.10`). Engine + all 3 strategy files byte-identical.
- **New trade-context columns**: `event_CPI_in_trade`,
  `event_FOMC_in_trade`, `event_FOMC_MINUTES_in_trade`,
  `event_count_during_trade`, `cpi_event_during_trade`,
  `fomc_event_during_trade`, `high_importance_event_during_trade`,
  `events_during_trade`, `nearest_event_before_entry`,
  `days_since_nearest_event_before_entry`.
- **Event overlap result** (29 trades): 27 overlapped ≥1 event (holdings
  ~2–3 weeks vs 13 events over 6 months → near-universal, *not*
  discriminating on its own); 17 overlapped a CPI release; 20 overlapped
  an FOMC statement/minutes.
- **Descriptive observation** (NOT edge, n far too small): bear_put
  losses (3) all overlapped an FOMC event — the worst loss (−$307.60)
  spanned the 2022-03-16 first-hike FOMC statement (SPY relief-rallied);
  bear_put's biggest wins clustered around CPI prints. Recorded purely
  as "when did it lose?" research context.
- **New artifacts**: `event_overlap_summary.csv`, `event_flag_panel.csv`,
  plus a new section 4c in `v57_summary.md`. Driver:
  `scripts/run_research_v57.py`.
- Guards verified: `LIVE_TRADING_ENABLED is False`; no broker / live /
  IBKR / order-execution imports; no trading signals (events never
  filter trades); no ThetaData fetch (options metadata unchanged); no
  strategy / default / parameter changes; no package installs; no
  credentials printed/committed (events CSV + reports contain no
  `api_key=` assignments).
- Event-aware outputs archived in **`reports/_v57_event_archive/`** with
  `CHECKPOINT.txt`, the updated reports, and a snapshot of
  `manual_events.csv`. Archive lineage: …, `_v57_archive` (no FRED/no
  events), `_v57_fred_archive` (FRED, no events), **`_v57_event_archive`**
  (FRED + events).

**Event annotation explains, it does not predict.** The CPI/FOMC overlap
enriches the "why did this trade win/lose?" narrative for a single bear
regime; it cannot turn a regime artifact into edge. The **next real edge
test remains wider SPY data expansion** (V5.2 Stage 2, 2022-07 →
2023-06). A **SEC EDGAR / company-filings research layer is deferred to a
V5.8 / V6-prep company research layer** and is not part of V5.7. An IBKR
read-only research adapter likewise remains deferred. V5.x remains
research/backtest only — no broker, no IBKR, no live trading.

##### V5.2 Stage 2A checkpoint — SPY Jul–Sep 2022 corpus (data only)

V5.2 Stage 2A is the first group of the wider-data expansion that will
eventually test whether `bear_put` survives non-bear regimes. **Data prep
only — no strategy / engine / default changes.** State:
- **3 contiguous months on disk:** SPY 2022-07, 2022-08, 2022-09 at
  `max_dte=45`, **64 trading days**, **286,648 canonical rows**,
  **11.30 MB** processed.
- **Coverage:** validator hard rejects **0** every month; all-5 Greeks
  NaN-free **100%** every month; IV non-NaN **87.5% / 88.0% / 90.3%**
  (Jul/Aug/Sep); **0 processed duplicate rows** every month.
- **Regime context:** Jul–mid-Aug bear-market summer rally (SPY ~$377 →
  ~$430), then renewed decline through September toward the Oct 2022
  bear-low (~$357 close) — the regime contrast Stage 1 lacked.
- **Cumulative corpus:** SPY 2022-01 → 2022-09 (9 contiguous months; Jan/Feb
  `max_dte=30`, Mar–Sep `max_dte=45`). Quality report now covers **188 SPY
  date-files / 841,766 canonical rows**.
- **Pipeline behaviour:** 2-chunk EOD splits used for Aug (23 wkdays) and
  Sep (22 wkdays); the multi-chunk processed-overwrite was repaired by the
  successful Greeks regeneration every time (all trading days present, 0
  duplicates). EOD-bulk raw row-duplication appeared on some days but never
  reached the processed file. 2–3 edge-of-band HTTP 472 skips per month,
  handled. No timeouts (240s Greeks timeout held).
- **219 tests pass** (suite unchanged; Stage 2A added data + metadata only).
- Guards verified: `LIVE_TRADING_ENABLED is False`, no broker / live / IBKR
  imports, no order execution, exactly 3 options strategies, no
  engine/default/parameter changes, no ThetaData stock endpoints (spot from
  local cache), no credentials read/printed/written, no package installs.
- Stage 2A archived in **`reports/_v52_stage2a_archive/`** with
  `CHECKPOINT.txt`, aggregate quality report, `metadata_snapshot.json`, and
  `processed_manifest.json` (per-file rows / size / coverage / dup-count /
  SHA-256). Archive lineage: …, `_v57_event_archive`,
  **`_v52_stage2a_archive`**.

**Next stage (V5.2 Stage 2B):** SPY Oct / Nov / Dec 2022 at `max_dte=45`,
one month at a time, same pipeline and quality gates. October 2022 contains
the bear-market low (~$348) followed by the Q4 rally — a key
regime-transition month for the eventual `bear_put` falsification test. The
V5.3–V5.7 analysis stack will be re-run on the full wider corpus only after
Stage 2 collection is complete. V5.x remains research/backtest only.

##### V5.2 Stage 2B checkpoint — SPY Oct–Dec 2022 corpus (full-year 2022 complete)

V5.2 Stage 2B completes calendar-year 2022 and captures the critical regime
transition. **Data prep only — no strategy / engine / default changes.**
State:
- **3 contiguous months on disk:** SPY 2022-10, 2022-11, 2022-12 at
  `max_dte=45`, **63 trading days**, **254,860 canonical rows**,
  **10.04 MB** processed.
- **Coverage:** validator hard rejects **0** every month; all-5 Greeks
  NaN-free **100%** every month; IV non-NaN **90.8% / 88.8% / 85.9%**
  (Oct/Nov/Dec); **0 processed duplicate rows** every month; per-day max
  DTE ≥ 37 every trading day (30–45 band fully covered).
- **Regime transition captured:** October bear-market low (~$356
  intramonth) → November Q4 recovery rally ($371 → $408) → December fade
  ($407 → $382). Combined with Stage 2A, the corpus now spans a full
  down-up-down cycle across 2022 H2.
- **Cumulative corpus: continuous full-year SPY Jan–Dec 2022** (12 months;
  Jan/Feb `max_dte=30`, Mar–Dec `max_dte=45`). Quality report covers
  **251 SPY date-files / 1,096,626 canonical rows** (corpus crossed 1 M
  rows).
- **Pipeline behaviour:** Nov + Dec used 2-chunk EOD splits, repaired by
  Greeks regeneration (all days present, 0 dups). Edge-of-band HTTP 472
  skips rose seasonally at quarter-end (Oct 12, Nov 16, Dec 16) but are
  benign — genuinely-empty far-edge expirations; the tradable 30–45 DTE
  band stays fully covered. December showed elevated zero-bid (16.3%) and
  spread-too-wide (24.3%) warnings consistent with thin holiday-week
  liquidity (informational, not gate failures). No timeouts.
- **219 tests pass** (suite unchanged; Stage 2B added data + metadata only).
- Guards verified: `LIVE_TRADING_ENABLED is False`, no broker / live / IBKR
  imports, no order execution, exactly 3 options strategies, no
  engine/default/parameter changes, no ThetaData stock endpoints (spot from
  local cache), no credentials read/printed/written, no package installs,
  no 2023 data fetched.
- Stage 2B archived in **`reports/_v52_stage2b_archive/`** with
  `CHECKPOINT.txt`, aggregate quality report, `metadata_snapshot.json`, and
  `processed_manifest.json` (per-file rows / size / coverage / dup-count /
  SHA-256). Archive lineage: …, `_v52_stage2a_archive`,
  **`_v52_stage2b_archive`**.

**Next stage (Stage 2B strategy / edge check):** run the three frozen
strategies on the existing data — full Jan–Dec 2022, Oct–Dec 2022, and full
2022 H2 (Jul–Dec) — using the expectancy / tradability lens. The focus is
whether `bear_put` (already weakened in Stage 2A: Jul–Sep ≈ −0.03%) goes
firmly negative across the Q4 recovery, which would confirm the
regime-artifact hypothesis. Only **after** that analysis is reviewed should
Stage 2C (Jan–Mar 2023) be considered. V5.x remains research/backtest only.

##### V5.2 Stage 2B strategy / edge check — full-year 2022 verdict (no deployable edge)

The three frozen defined-risk verticals were run on the existing full-year
SPY Jan–Dec 2022 corpus across 8 windows with an expectancy / tradability
lens. **Read-only analysis — no new data, no ThetaData, no
strategy/engine/default changes, no parameter optimization.** Findings:
- **Jan–Jun baseline reproduced V5.3 exactly** (`bull_call −1.27%`,
  `bear_put +0.65%`, `bull_put −1.47%`); driver output deterministic
  (result CSVs byte-identical on re-run); **219 tests pass**.
- **`bear_put` did NOT survive the Q4 recovery.** Oct–Dec 2022:
  **−0.33%, 20% win rate, profit factor 0.27, expectancy −$65/trade** —
  its worst window by every metric. Expectancy decays monotonically as
  non-bear regime is added: +$64.90 (Jan–Jun) → +$33.93 (Jan–Sep) →
  −$5.70 (Jul–Sep) → **−$65.00 (Oct–Dec)**; full-year residue just
  **+0.15%**. **`bear_put` is rejected as a regime-independent tradable
  edge** — a pure regime-directional bet.
- **Mirror image confirmed:** `bull_put` turned **positive in the recovery**
  (Oct–Dec +0.10%, 80% win, PF 1.55; November +0.32% at 100% win), its
  only positive window; `bull_call` improved toward flat (−0.04% vs
  −1.27% in the H1 bear). In the bear, bear_put wins / bull_put loses; in
  the recovery, bull_put wins / bear_put loses. Each strategy's sign is
  set by whether the regime matches its directional bias — driven by spot
  direction **and** vega (VIX 30→22 in Q4).
- **No defined-risk vertical is deployable.** None shows positive
  expectancy across **both** bear and recovery regimes; each has profit
  factor > 1 only in its favorable regime. These are regime-directional
  bets with no proven structural edge. Research finding, not a trading
  recommendation.
- **What is validated (mechanics, not edge):** the V5.0 engine across 24
  (window × strategy) runs; the V5.2 full-year data pipeline (1,096,626
  rows, 100% Greeks, 0 hard rejects, 0 dup rows); and the V5.3–V5.7
  research/reporting stack.
- Guards verified: `LIVE_TRADING_ENABLED is False`, no broker / live /
  IBKR imports, no order execution, no trading signals (the check measures,
  never trades), no new data fetch (SPY range ends 2022-12-30), exactly 3
  strategies, no engine/default/parameter changes, no package installs, no
  credentials.
- Archived in **`reports/_v52_stage2b_strategy_archive/`** with
  `CHECKPOINT.txt`, the 5 analysis artifacts, and a driver snapshot.

**Next stage:** a **V5.7.1 / V5.8 Edge-Tradability final report** that
consolidates the V5.3–V5.6 stability work and the Stage 2A/2B strategy
checks into one decision document — stating that the engine, data, and
research pipeline are validated, and that **no defined-risk vertical is a
deployable edge on the available SPY 2022 evidence**. A single confirmatory
2023 quarter (Stage 2C, Jan–Mar 2023) is **optional** — it would only add
out-of-sample confirmation of an already-clear regime-directional
conclusion, and is not required to reach the verdict. V5.x remains
research/backtest only.

##### V5.7.1 / V5.8 Edge-Tradability final report — VERDICT: no deployable edge

The consolidation report (`reports/research/v571_tradability/`) applies a
Roman-Paolucci tradability lens (profitability ≠ edge; decompose expectancy;
test sign + magnitude stability across regimes; reject backtest profit that
fails a regime shift) across all V5.3–V5.7 + Stage 2A/2B evidence on the
full-year SPY 2022 corpus. **Read-only: no new data, no ThetaData, no
strategy/engine/default changes, no parameter optimization. 219 tests pass.**

**Final verdicts (full-year 2022):**

| strategy | full-year ret | expectancy/trade | profit factor | windows + (of 5) | verdict |
|---|---:|---:|---:|---:|---|
| bull_call | −1.68% | −$98.60 | 0.39 | **0/5** | NOT deployable; no persistent positive expectancy |
| bear_put | +0.15% | +$7.72 | 1.09 | 3/5 | **REJECTED as regime-independent edge** — regime-directional bearish bet |
| bull_put | −2.07% | −$98.72 | 0.28 | 1/5 | NOT deployable; positive **only** in Q4 recovery — regime-directional credit bet |

- **Is any current strategy deployable?** **No.** No vertical keeps profit
  factor > 1 outside its favorable regime.
- **Was bear_put falsified?** **Yes.** Expectancy/trade decays
  +$64.90 (Jan–Jun) → −$65.00 (Oct–Dec); PF 2.41 → 0.27; sign flips with the
  regime. The Jan–Jun +0.65% was a clean-bear artifact.
- **Mirror image:** bear_put wins in the bear / loses in the recovery;
  bull_put loses in the bear / wins in the recovery — directional + vega
  exposure, not structural edge.
- **What IS validated:** the V5.0 engine (causality, MTM, settlement,
  force-close, defined-risk debit/credit accounting), the V5.2 ThetaData
  pipeline (full-year SPY 2022: 1,096,626 rows, 100% Greeks, 0 hard rejects,
  0 dup rows), IV/Greeks enrichment, cost/spread sensitivity, the
  rolling/non-overlapping stability framework, and the V5.7 macro/FRED/event
  read-only research layer. **What is NOT validated:** a deployable edge,
  regime-independent profitability, any live/paper/IBKR execution, or
  macro signals as trading filters.
- **2023 data?** Optional only. Full-year 2022 already reached the verdict;
  a single Stage 2C quarter would merely re-confirm the regime-directional
  reading. Fetch further data only for a **specific new hypothesis**.
- **Next research directions (ranked):** (A) new strategy research not based
  on pure direction — IV/volatility-risk-premium, range-filtered defined-risk
  credit structures (iron condors / credit spreads with IV-rank gates),
  calendar/diagonals; each must clear the same falsification stack before any
  edge claim. (B) read-only company/fundamentals layer (SEC EDGAR 10-K/10-Q/
  8-K, balance-sheet/liquidity context). (C) optional SPY 2023-Q1 confirmation.
  (D) paper trading — **not yet** (no edge established).
- Artifacts: `reports/research/v571_tradability/` (`v571_summary.md`,
  `strategy_final_verdict.csv`, `expectancy_decomposition_full_year.csv`,
  `regime_dependence_summary.csv`, `validated_vs_not_validated.md`,
  `next_research_plan.md`). Builder: `scripts/build_v571_tradability_report.py`.

**This is a research finding, not a trading recommendation. No defined-risk
vertical is deployable. No broker, no IBKR, no live trading.
`LIVE_TRADING_ENABLED` remains False.**

##### V5.7.1 / V5.8 Edge-Tradability final report — stabilization checkpoint (FROZEN)

The Edge-Tradability final report is **frozen**. **Read-only checkpoint: no
new data, no ThetaData, no strategy/engine/default changes, no parameter
optimization.** State:
- **219 tests pass.** Report builder is **fully deterministic** — re-running
  reproduces all 6 artifacts byte-identical (it reads the already-computed
  Stage 2B CSVs; no backtest re-run, no fetch).
- **Verdict frozen:** **no deployable edge** found in `bull_call`,
  `bear_put`, or `bull_put`. The three V5.3 defined-risk verticals are
  **retired/rejected for deployment** — they remain in the codebase only as
  research/validation strategies (engine exercisers), not as tradable
  strategies. `bear_put` is rejected as a regime-independent edge (Oct–Dec
  −0.33%, PF 0.27, expectancy −$65/trade); `bull_put` is positive only in the
  Q4 recovery; `bull_call` shows no persistent positive expectancy.
- **Validated (frozen):** V5.0 engine + defined-risk debit/credit accounting +
  no-look-ahead causality; the V5.2 ThetaData pipeline (full-year SPY 2022:
  1,096,626 rows, 100% Greeks, 0 hard rejects, 0 dup rows); IV/Greeks
  enrichment; cost/spread sensitivity; rolling/non-overlapping stability
  framework; macro/FRED/event read-only research + tradability lens.
- Guards verified: `LIVE_TRADING_ENABLED is False`, no broker / live / IBKR
  imports, no order execution, no trading signals, exactly 3 strategies, no
  new data fetch (SPY range ends 2022-12-30), no package installs, no
  credentials.
- Archived in **`reports/_v571_tradability_archive/`** with `CHECKPOINT.txt`,
  the 6 report artifacts, and a builder snapshot. Archive lineage: …,
  `_v52_stage2b_strategy_archive`, **`_v571_tradability_archive`**.

**Next stage — options research FOUNDATION UPGRADE (then new strategies):**
before designing any new strategy, build a feature foundation —
**IV/RV spread, IV percentile/rank, volatility skew (put/call skew, risk
reversal), term structure (front vs back IV), and liquidity/cost features
(spread%, volume, OI)** — then design **non-directional or regime-aware**
options strategies whose thesis is a vol-premium / range / term-structure
condition rather than pure direction (IV/VRP defined-risk premium selling,
range-filtered iron condors / credit spreads with IV-rank gates,
calendar/diagonals). Every new structure must clear the same falsification
stack (V5.3→V5.6 + Stage 2A/2B-style regime splits + expectancy/tradability
lens) before any edge claim. A read-only SEC EDGAR / fundamentals layer is a
parallel option; paper trading (V6) is deferred until a regime-robust edge is
demonstrated out-of-sample. 2023 data remains optional (specific-hypothesis
only). V5.x remains research/backtest only.

##### V5.8 Options Research Feature Layer — checkpoint (read-only feature foundation, FROZEN)

V5.8 builds the read-only SPY 2022 options **feature foundation** that future
strategy research will consume. **No new data, no ThetaData, no
engine/strategy/default changes, no parameter optimization, no edge claimed.**
State:
- **New module `quantbot.options.features`** (pure, causal functions) +
  driver `scripts/run_build_options_features.py` + `tests/test_v58_options_features.py`.
- **Features include:** realized vol (5/21/63d), IV summary (ATM + 25d/30d
  call+put IV), **causal** IV percentile / IV rank (63d, 126d), IV-vs-RV
  spread/ratio, skew (put/call/put-call), term structure (near/mid/far ATM
  IV, slope, ratio), and liquidity/cost diagnostics. Outputs in
  `data/options/features/SPY/2022/` (7 files incl. a 251×38 master
  `daily_options_research_panel.csv`); reports in
  `reports/options/v58_research_features/` (7 files).
- **Coverage:** 251 feature dates; ATM IV + 25d/30d wing IV 100%; RV
  21d/63d 96.0%/87.6%; IV rank/percentile 63d/126d 92.0%/83.7% (early dates
  NaN by causal design); skew 100%; term structure near/mid 100%, far/slope
  92.4%.
- **Observations (descriptive, not signals):** ATM IV exceeded 21d realized
  vol on only **~40.2%** of dates (2022 was a frequently **negative-VRP**
  regime — naive short-vol ideas need caution); **put_skew +0.039 /
  put-call skew +0.070** (classic equity-index downside-rich shape); mild
  term-structure **backwardation** on average (`max_dte=45` limits this to
  the short end); liquidity usable (~3,604 usable contracts/day) but **open
  interest missing throughout** (V4 pipeline didn't populate OI).
- **Determinism:** re-running the builder reproduces all 7 feature files +
  7 reports **byte-identical**; existing processed options files
  **unmutated** (SHA-256 unchanged).
- **234 tests pass** (+15 V5.8 feature tests). Guards verified:
  `LIVE_TRADING_ENABLED is False`, no broker/live/IBKR imports, no order
  execution, no trading signals (features only), exactly 3 (rejected)
  strategies, no new data fetch (SPY range ends 2022-12-30), no package
  installs, no credentials.
- Archived in **`reports/_v58_features_archive/`** with `CHECKPOINT.txt`,
  the 7 reports, and a `feature_files_manifest.json` (per-file SHA-256).
  Archive lineage: …, `_v571_tradability_archive`, **`_v58_features_archive`**.

**No edge is claimed; the three vertical strategies remain rejected for
deployment.** Next stage is **new options strategy research** consuming these
features — IV/volatility-risk-premium, range-filtered defined-risk credit
structures (iron condors / credit spreads with IV-rank gates),
calendar/diagonals only if a future dataset extends DTE coverage, and
regime-aware selection only after strict out-of-sample falsification. Every
new structure must clear the same falsification stack before any edge claim.
V5.x remains research/backtest only.

##### Company & Fundamentals Research Layer (V5.8 / V6-prep) — checkpoint (read-only, FROZEN)

A new **read-only SEC EDGAR company/fundamentals research layer** was added as
V6-prep, in parallel to the (still paused) options work. **No trading signals,
no strategy/engine/default changes, no options data fetch, no ThetaData, no
broker/live/IBKR.** State:
- **New package `quantbot.company`**: `sec_edgar` (stdlib-`urllib` client —
  configurable `QUANTBOT_SEC_USER_AGENT`, polite ~5 req/s throttle, atomic
  cache under `data/company/sec/`, never raises), `filing_index`,
  `company_facts`, `filing_parser` (stdlib HTML→text + best-effort sections),
  `company_report` (orchestrator), `lseg_placeholder`. Driver
  `scripts/run_company_research.py`; tests `tests/test_company_research.py`.
- **AAPL example works** (CIK `0000320193`): submissions fetched, **75**
  in-scope 10-K/10-Q/8-K filings indexed (of 1000 recent), all **7** XBRL
  fundamentals extracted (revenue, net_income, total_assets, total_liabilities,
  cash_and_equivalents, operating_cash_flow, total_debt), 3 recent filings
  parsed (the 2024-11-01 10-K detected business/risk_factors/mdna/liquidity/
  market_risk), and 12 strongest 21d/63d move windows lined up against SPY/VIX
  and nearby filings. **Company facts and filings are read-only research
  context only — never a signal, never wired into a strategy or backtest.**
- **Reports** in `reports/company/sec_edgar/`: `company_data_availability.md`,
  `AAPL_filing_index.csv`, `AAPL_company_facts_summary.csv`,
  `AAPL_recent_filings_summary.md`, `AAPL_macro_company_context.md`.
  Cache-first re-runs are **byte-identical** (no embedded timestamps).
- **262 tests pass** (+28 company tests, toy-fixture, never network). Guards
  verified: `LIVE_TRADING_ENABLED is False`, no broker/live/IBKR imports, no
  order execution, no ThetaData/options fetch, no strategy/engine/default
  changes, no package installs, no credentials printed (SEC needs no key; UA
  configurable and not hardcoded with private data).
- **LSEG/Datastream connector deferred** until an API entitlement is confirmed
  (`lseg_placeholder.is_available()` → False; design note only).
- Archived in **`reports/_company_research_archive/`** with `CHECKPOINT.txt`,
  the 5 reports, and a `cache_snapshot.txt` SEC-cache inventory.

**The paused V5.9 out-of-sample options path remains open and untouched** (no
2023 Q1 fetch, no new options strategy, no iron-condor builder). Layer is ready
to extend to more tickers (`build_company_research(ticker=...)`). Research only.

##### V5.9 OOS — SPY January 2023 first out-of-sample month — data checkpoint (FROZEN)

The V5.9 out-of-sample path has since **resumed for SPY January 2023 ONLY** —
a **controlled data pull, data-prep only, no edge run or claimed.** **No
February/March/full-2023 fetch, no QQQ/AAPL, no iron condor, no new strategy,
no engine/default/parameter changes, no broker/live/IBKR.** State:
- **20 trading days** (2023-01-03 → 2023-01-31; Jan 2 New Year's observed +
  Jan 16 MLK closed). EOD pulled in **2 chunks** (Jan 1–15 / Jan 16–31, to
  respect the `sample_workflow` 21-business-day cap; no raw overwrite); Greeks
  ran **single-pass** (52 band expirations, **17 HTTP-472 edge-of-band skips**,
  all expected). Underlying spot from the **local SPY cache** (never the
  ThetaData stock endpoint).
- **Canonical:** `data/options/processed/SPY/2023/2023-01.csv.gz` — **75,568
  rows** (EOD raw 75,098; Greeks 75,568), **IV coverage 87.5%**, **Greeks
  coverage 100%**, **0 hard rejects, 0 duplicate rows**, zero-bid 14.8%,
  zero-volume 44.3%, spread>25% 23.9% (wings), SPY spot **379.38 → 406.48**,
  0 NaN spot. Runtime ~38 min.
- **262 tests pass.** Guards verified: `LIVE_TRADING_ENABLED is False`, no
  broker/live/IBKR imports, no order execution, no trading signals, exactly 3
  (rejected) strategies, no iron-condor builder, **SPY 2023-01 is the only
  2023 options data on disk**, no engine/default changes, no package installs,
  no credentials.
- Archived in **`reports/_v59_oos_jan2023_archive/`** with `CHECKPOINT.txt`, a
  `processed_manifest.json` (processed + all 40 raw files: rows, bytes,
  SHA-256, coverage), and snapshots of the quality report and `metadata.json`.
  Archive lineage: …, `_v58_features_archive`, `_company_research_archive`,
  **`_v59_oos_jan2023_archive`**.

**No edge is claimed.** A single OOS month cannot confirm or reject a
vol-premium / IV-rank / skew hypothesis — more OOS breadth (further 2023
months / multi-name) is still required before any verdict. **Fetching
February (or anything beyond SPY 2023-01) is a separate, explicit approval.**
Research/backtest only.

##### V5.9 OOS feature / power check (SPY January 2023) — checkpoint (FROZEN)

The Jan-2023 OOS month was put through a read-only V5.8-style feature build +
limited power check, **using existing local data only — no new data, no
ThetaData, no new strategy, no iron condor, no threshold optimization, no
engine/default change.** State:
- **New read-only driver `scripts/run_v59_oos_feature_power_check.py`** builds
  Jan-2023 features over the **combined 2022+Jan-2023 chain** (rolling
  IV-rank/RV get causal late-2022 lookback), then **slices Jan-2023** to
  `data/options/features/SPY/oos_2023_01/` (7 files). The frozen 2022 feature
  files are **untouched** (SHA-256 unchanged). Re-running the driver is
  **byte-identical** (deterministic).
- **Jan-2023 built successfully:** 20 feature dates, **100% coverage** on every
  feature.
- **Power check (gates reuse the 2022 cutpoints unchanged):** Jan-2023 was a
  **vol-normalization** month (ATM IV ~0.221→~0.173), so `iv_rank_63d` stayed
  low (0.00–0.34). **The lead high-IV-rank and rich-put-skew gates fired ZERO
  times** (0/20 days); the IV-rank≥0.50 gate also 0; only **positive-VRP**
  fired (13/20 days, 3/5 ISO-week-starts, ≈1.2 est. realised credit trades).
  vs 2022 full-year bull_put (5/10/10/8). **No trade ledger exists — no P&L was
  invented, no edge is claimed.**
- **Not a data failure — a real regime result:** the pipeline ran clean; the
  pre-registered gates simply did not trigger in a calm month. Gates calibrated
  on a high-vol year can rarely fire in a quieter regime.
- **Decision implication:** Jan-2023 alone does **not** justify a month-by-month
  February fetch (a calm month can add zero lead-gate observations). **OOS
  expansion should pause** unless tied to a larger, regime-spanning,
  **pre-registered** hypothesis (full 2023 / multi-name) with explicit approval.
- **262 tests pass.** Guards verified: `LIVE_TRADING_ENABLED is False`, no
  broker/live/IBKR imports, no order execution, no new data fetch (on disk only
  SPY 2023-01 for 2023; no Feb/Mar/full-2023/QQQ/AAPL), no iron condor, exactly
  3 (rejected) strategies, no threshold optimization, no engine/default changes,
  no package installs, no credentials.
- Archived in **`reports/_v59_oos_power_archive/`** with `CHECKPOINT.txt`, the 4
  V5.9 OOS reports, and a `feature_files_manifest.json` (per-file SHA-256).
  Archive lineage: …, `_v59_oos_jan2023_archive`, **`_v59_oos_power_archive`**.

**No strategy, edge, or live-trading claim.** Research/backtest only.

Supporting layers: data loaders + validators, transaction-cost & slippage
model, indicators, RiskManager (vol targeting, caps, drawdown kill switch),
portfolio construction, a no-look-ahead backtest engine, options
payoff/pricing/Greeks/structures/parity utilities, performance metrics,
Markdown/CSV tearsheets, and a pytest suite (**137 tests**).

## 2. Constraints honored

- Research/backtest only — no broker, no live execution.
- **ETF-only** universe; **free daily OHLCV** (yfinance) with a deterministic
  **synthetic fallback** so the repo always runs offline.
- S01 & S02 **long-only**; S03 **hedge-ratio matched** with genuine long + short ETF legs.
- Transaction costs, slippage, bid/ask spread modelled on every trade; S03 also
  charges a daily **borrow cost** on the short leg.
- **No look-ahead**, enforced at two independent layers (causal strategy
  weights + next-bar execution; `Order` raises if `execution_date <= signal_date`).
- Next-bar execution only (`next_open` default).
- Risk management + drawdown kill switch always in the path.
- No naked short options anywhere; options structures are defined-risk only.

## Phase 2B analytical data storage

The opt-in Parquet/DuckDB layer uses an external data root and immutable source,
dataset and run manifests. It leaves existing backtest/archive paths unchanged.
See [the Phase 2B storage guide](docs/phase2b_data_storage.md) for schemas,
provenance conventions, configuration and the offline sample command.

## 3. Setup

```powershell
python -m pip install uv==0.11.8
$env:UV_PROJECT_ENVIRONMENT = 'C:\QuantEnvs\quant_trading_bot_phase2'
uv sync --locked --all-extras --group dev --python 3.12.10
```
Python 3.12 is required; the verified interpreter is CPython 3.12.10. The
committed `uv.lock` is the reproducible dependency source. See
[`docs/phase2a_environment.md`](docs/phase2a_environment.md) for clean Windows
setup and verification commands. `requirements.txt` is retained only as a
core-install compatibility pointer and is not the locked development workflow.

Optional config overrides (committed examples are used if these are absent):
```
configs/strategy_configs.json   # canonical strategy + risk params (used directly)
configs/data_config.json        # copy from data_config.example.json to customise universe/dates
configs/risk_config.json        # copy from risk_config.example.json to override risk
```

## 4. Run the backtests

```bash
python scripts/run_s01.py        # S01 trend following  (long-only, weekly)
python scripts/run_s03.py        # S03 pairs            (hedge-ratio matched, weekly sizing, daily exits, monthly reselect)
python scripts/run_s02.py        # S02 factor blend     (long-only, monthly)

# Force the offline deterministic dataset (no network):
python scripts/run_s01.py --source synthetic
# S03 borrow cost override (annual bps on the short leg):
python scripts/run_s03.py --borrow-bps 75
```

Each script prints headline metrics and writes a report to
`reports/backtests/<strategy>/` (`report.md`, `metrics.json`, equity/returns/
weights CSVs) plus figures in `reports/figures/<strategy>/`.

**Data source:** scripts try the local CSV cache → yfinance → synthetic. If
yfinance is unreachable the **entire** universe is regenerated synthetically
(real and synthetic data are never mixed) and the report is labelled
accordingly.

## 4.5 Local research platform (V7)

The V7 Streamlit platform exposes the V6 sector / company / aggregation
research, the V7.1 portfolio, V7.7 protection labels, V7.4 PortTech labels,
and the V7.8 MarketPulse shell as a single local web app.

```powershell
& 'C:\QuantEnvs\quant_trading_bot_phase2\Scripts\python.exe' -m streamlit run apps/portfolio_platform.py
& 'C:\QuantEnvs\quant_trading_bot_phase2\Scripts\python.exe' -m streamlit run apps/sector_thesis_dashboard.py
```

Both apps bind to `localhost` by default. For phone / tablet access on
**trusted** Wi-Fi (and the relevant security caveats), see
[`reports/research/V7_0_1_LAUNCH_WORKFLOW.md`](reports/research/V7_0_1_LAUNCH_WORKFLOW.md).
Convenience launchers live at `scripts/launch_platform.ps1` and
`scripts/launch_sector_dashboard.ps1`. Press `Ctrl+C` in the terminal to
shut down.

The platform is read-only; it does not place orders, does not connect to
a broker, does not fetch live market data, and has no authentication.
`LIVE_TRADING_ENABLED` remains `False`.

## 5. Run the tests

```powershell
& 'C:\QuantEnvs\quant_trading_bot_phase2\Scripts\python.exe' -m pytest
```
The suite covers the spec's required checks: data validation catches impossible
OHLC; indicators/strategies are causal; the engine never executes before the
signal date; costs reduce performance; position caps hold; S03 entry/exit/stop/
max-holding behave; options payoffs match known shapes; the parity scanner uses
bid/ask and does not false-flag a consistent chain once a cost buffer applies.

## 6. Repository layout

```
src/quantbot/
  config.py            data/{loaders,validators,corporate_actions,options_loader,futures_loader}
  indicators/{trend,volatility,factors,pairs,options_features}
  costs/{transaction_costs,slippage}
  risk/{risk_manager,drawdown,var_es,greeks,stress}
  portfolio/{construction,exposure,optimizers}
  backtest/{order,position,broker,engine,performance,walk_forward}
  strategies/{base,s01..s10}
  options/{pricing,greeks,payoff,structures,parity}
  reporting/{tearsheet,plots,export}
  utils/{dates,math,logging}
scripts/{run_s01,run_s02,run_s03}.py     tests/  configs/  data/  reports/
```

## 7. How look-ahead is prevented

1. Strategies precompute a **causal** weight panel — every row uses only data
   up to that date (unit-tested by recomputing on a truncated history).
2. The engine emits orders with `signal_date = t`, `execution_date = t+1`;
   `Order.__post_init__` raises on any violation.
3. Fills occur at the **next bar's** open/close via the simulated broker.
4. S03 pair reselection is walk-forward (month-start, history sliced to date).

## 8. Risk & cost models

- **Costs:** `(commission + half-spread + slippage)` bps × traded notional per
  side; round-trip-aware cost filter (`edge > 3 × round-trip`). Options model:
  per-contract fee + bid/ask fraction + multi-leg penalty.
- **RiskManager pipeline:** portfolio-DD kill switch → vol-spike kill →
  strategy pause → prior-day-loss de-risk → vol targeting → per-symbol cap →
  sector cap → gross/net cap. Caps only ever *reduce* risk.

## 9. Known limitations / caveats (read before trusting any number)

- **No profitability claim.** Synthetic-data results are illustrative only.
- **S02 is price-only** and uses the *current* ETF list → survivorship &
  point-in-time bias; no fundamentals in v1. Treat factor results as biased.
- **No real options/futures history** → S04–S08 inactive; options results use a
  Black-Scholes **synthetic** chain and are explicitly approximate.
- Black-Scholes Greeks are European approximations (no American early exercise
  / discrete dividends).
- Weight-based engine holds weights constant between rebalances (no intra-period
  drift rebalancing) — a standard, slightly-conservative research simplification.
- ETF adjusted-close is used for total-return adjustment; single-name
  point-in-time corporate-action handling is out of scope for v1.
- Borrow availability/locate for the S03 short leg is modelled only as a flat
  annual cost; hard-to-borrow risk is not simulated.
- Parity scanner is **report-only**; apparent violations are usually stale
  data / dividends / borrow, not free money.

## 10. Roadmap (not in v1)

Real options-chain ingestion → activate S05/S09 properly · futures chain →
S04 · combined multi-strategy portfolio · paper-trading harness with manual
review gate. **Live trading remains out of scope until external validation.**


### Phase 3B execution conventions

S03 retains `spread = A - beta * B` and executes quantities proportional to
`(+1, -beta)` for a long spread (reversed for a short spread). Exact dollar
neutrality was mathematically inconsistent with that spread and is no longer
required. Configured net, gross, sector and position caps remain constraints;
structured targets use one common scale and atomic execution.

See [Phase 3B execution mechanics](docs/phase3b_execution_mechanics.md) for
capacity assumptions, cadence, diagnostics, numerical reconciliation and tests.
