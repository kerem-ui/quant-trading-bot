# Phase 3C: frozen research revalidation protocol

This phase does not change any strategy, accounting, risk, execution, configuration value or dependency. It certifies reproducibility and reconciliation of corrected research runs, not profitability, independent alpha, capacity at scale or live readiness.

## Legacy / non-certified records

Everything in `reports/backtests/` and `reports/core/`, and performance statements derived from those files in the old README, is **LEGACY / NON-CERTIFIED**. Files remain byte-for-byte intact; the frozen specification records their checksums and every run verifies them before and after execution. Use the separate Phase 3C report for current evidence. Existing exploratory scripts are not certification entry points. In particular, `scripts/research_edge.py` computes S03 equal-dollar return spreads; those are inconsistent with the newly approved quantity hedge. Its historical conclusions cannot certify the corrected S03.

## What was already observed

The initial repository commit includes 2010-01-04 through 2026-05-19 full-period reports. `scripts/report_s02_v3.py` and `scripts/research_edge.py` explicitly examine 2010-2014, 2015-2019 and 2020-2026, factor-only variants, equal/random factor weights, trend binary versus conviction variants, and multiple ETF pair candidates. README role assignments were informed by these results. Git history does not provide a defensible untouched holdout or a record proving an observed period was untuned. Classify this entire range as previously observed development/research data. Neither a script variable called OOS nor a fresh execution date makes it untouched OOS. Parameter-selection chronology beyond these records cannot be determined from the current repository.

## Freeze before results

`python -B -m quantbot.research.phase3c freeze --id ID --inventory PATH_TO_PHASE2C_PRIVATE_INVENTORY` creates a new sealed `research/phase3c/ID/freeze.json` and byte-identical source copies in ignored `runs/phase3c/ID/source_inputs/`. It does not change originals or fetch data. The private locator stays local; committed metadata contains relative legacy names and content hashes only. Every CSV must match its Phase 2C checksum and pass finite OHLCV and exact exchange-session continuity checks. Later ETF inceptions remain later inceptions.

The specification contains canonical strategy/data/risk configuration, effective defaults, universes, rules, execution/cost assumptions, runtime source hashes, code revision, lock/config hashes, source file identities and ranges, legacy output hashes, chronological windows, sensitivities and classification rules. Runtime code/config/legacy artifacts are checked before and after each run. Input files are checked before and after the complete run. No synthetic fallback, network download, data filling or parameter search is allowed.

The original cached equity inputs lack provider response manifests. The configured provider was yfinance, but original retrieval provenance cannot be independently authenticated. Their hashes prove byte identity, not market-data truth. Phase 2 provenance sealing is reused for specifications and output manifests. These inputs are explicitly legacy-normalized caches, never provider raw data.

## Frozen strategy mechanics

S01 remains binary long-only: weighted 20/60/120 return z-score, entry 1, exit 0.25, realized volatility20, adjusted ATR14 times3, minimum soft hold20, weekly entry/resize with 2% no-trade band. Daily actual-held hard stops and central risk remain enabled. The optional conviction experiment is not enabled. S01's entry cost hurdle stays at its base cost model for all execution-cost scenarios, so sensitivity does not retune signals.

S02 remains monthly long-only, top20% of eligible price-only factor scores, capped at4% per name. The five factor weights remain45/20/20/10/5%. Price and trailing raw-dollar liquidity eligibility apply before ranking. No fundamental data or synthetic factor sleeves are added.

S03 remains `A-beta*B`, with long-spread quantities `k*(1,-beta)` and the opposite short direction. Monthly selection, trailing beta252/z60, entries2/exits0.5/stops3.5, max signal hold20, and target gross0.60 remain unchanged. Selection correlation0.65 differs deliberately from the existing exit correlation0.50. Exact dollar neutrality is not required. All pair risk scaling is proportional; the existing atomic fill policy remains intact.

Common run capital is $1,000,000 per separate strategy. Prices and execution use the adjusted research convention, next session open. Per-side trading charges are commission1bp, half-spread2bp, extra slippage2bp; impact/minimum commission0. Interest is disabled and negative cash without financing is prohibited. S03 borrow is50bp annual on carried net-short quantity at closing marks, /252; S01/S02 borrow0. Capacity remains disabled as in verified defaults; this is a small-book assumption, not a certificate of unlimited liquidity. No parameters change across windows.

## Metrics and attribution

Each measurement first checks full-run net-return compounding, cash plus marked quantities, every event snapshot and signed daily P&L components. A subperiod starts from the immediately preceding equity, not its first ending equity. Include starting capital in drawdown. CAGR uses252 sessions/year and is omitted below a year. Volatility and Sharpe use sample standard deviation, zero risk-free hurdle. Sortino uses RMS negative returns across **all** sessions; old reports used the standard deviation of negative observations, so Sortino levels are not directly comparable.

Executed trades count nonzero filled order deltas, not target declarations or zero-quantity acknowledgments. Episode P&L comes from fill cash flows, costs, borrow, dividends and terminal marks. S03 pair components must sum to actual symbol quantities and reconcile daily market P&L, trading fees and borrow. With overlapping pairs, actual symbol fees are allocated by absolute virtual component quantity change; actual net-short borrow is allocated to contributing short components. Pair attribution is not an independently funded strategy result. Virtual pair turnover is labeled as such and is not reported as actual account turnover.

Nonlinear cross-sectional ranking has no unique additive factor P&L. S02 reports held-factor rank exposures and instrument P&L; old single-factor counterfactual backtests are not relabeled additive contributions. S02 eligibility impact compares old post-ranking masking versus corrected pre-ranking masking at the same causal decision dates, without executing a legacy strategy variant.

Chronological windows retain the continuous ledger and original warm-up/state. Existing `make_walk_forward_windows` supplies four expanding-history boundaries; its `train_frac` argument is unused in the old implementation, so no train-fraction claim is made. The old `walk_forward_run` and `cost_sensitivity` wrappers omit frozen engine settings; this phase uses the boundaries with the verified full causal run instead. No fold-specific fitting or resets occur. These are observed-period diagnostics, not OOS alpha tests.

Cost scenarios are 0x,1x,2x all execution-charge components, retaining the base signal cost filter and all other assumptions. S03 separately runs borrow0/50/100bp with base trading costs. Cost-driven equity/risk/quantity feedback is allowed; a fee-only sensitivity need not preserve identical realized quantities. Cash interest and financing remain zero/disabled. Open terminal holdings stay marked, without fictitious liquidation.

## Classification rules fixed before performance runs

All classifications require passing reconciliation and immutable-input checks. A failed correctness check is not a strategy rejection: it prevents certification.

- RESEARCH-VALIDATED requires at least5 years and30 completed holding episodes (pair episodes for S03); positive base and2x-cost total return; at least2 of the3 predefined chronological periods positive; maximum drawdown no worse than20%; and no single instrument/pair above50% of total positive contributor P&L.
- RESEARCH-REJECTED means base and2x returns are both nonpositive and at most1 chronological period is positive.
- Other technically correct results are RESEARCH-UNCERTAIN.

These transparent descriptive gates are not statistical significance tests. They do not establish alpha. Concentration, sample length, overlapping episodes, market regimes, selection bias, many historical variants and fixed-universe survivorship still limit every classification. No rejected hypothesis is retuned in this phase. Combined-strategy certification is deferred because separate backtests do not share one funded ledger.

## Reproduce offline

Use the locked Phase 2 Python environment and private repository. Restore the exact25 CSV blobs listed in the frozen specification from the separate data archive; a code-only clone does not contain licensed/local market data. Verify their SHA-256 hashes. Do not substitute newly downloaded revised history under the same identity.

```powershell
$python = 'C:\QuantEnvs\quant_trading_bot_phase2\Scripts\python.exe'
& $python -B -m quantbot.research.phase3c run --freeze research/phase3c/ID/freeze.json --id UNIQUE_RUN_ID --sources PATH_TO_HASH_PINNED_CSV_DIRECTORY
```

The chosen output directory must not already exist. Generated CSV/JSON ledgers, trades, manifests, diagnostics and complete sensitivity results remain under ignored `runs/phase3c/UNIQUE_RUN_ID/`. Commit only source/tests/documentation, frozen portable metadata and small summary evidence; never commit source CSVs, large ledgers, market data or private inventory paths. Every output file is checksum-listed in the sealed run manifest.


## This checkpoint

The final pre-performance freeze is `research/phase3c/phase3c-20260918-v3/freeze.json`, recorded against runtime commit `8a9fde562badad337eb49f653c6965d9f7b34032`. The eleven completed scenarios are saved under ignored `runs/phase3c/phase3c-20260918-certified-v3/`.

Two preparation defects were corrected without changing any strategy, risk limit, cost scenario, source datum or classification gate. The v1 preparation stopped on tuple serialization before performance execution. The v2 runs reconciled locally, but a fresh-checkout rehearsal exposed Git newline conversion in code/configuration files. Their evidence is preserved locally as superseded development output. The v3 specifications explicitly match every v2 strategy configuration, scenario, criterion and dataset identity.

Code, configuration and legacy report **text** fingerprints now canonicalize CRLF to LF so an equivalent Git checkout passes. Market input and generated output fingerprints remain strictly byte-exact. Legacy report bytes are additionally captured at run start and checked unchanged after each scenario. `.gitattributes` pins the portable research JSON files to LF. Fresh index checkouts using both `core.autocrlf=true` and `false` passed all source/config/legacy-content guards and retained byte-identical sealed metadata. No production file or dependency was reformatted.

Small committed summary evidence and run identities sit beside the freeze. Full run manifests, ledgers and source blobs remain local. To regenerate the human report after restoring and verifying the ignored run outputs:

```powershell
& $python scripts/report_phase3c.py --run runs/phase3c/phase3c-20260918-certified-v3 --verification research/phase3c/phase3c-20260918-v3/verification.json --output docs/phase3c_research_report.reproduced.md
```

The renderer refuses legacy directories and checks every output hash before formatting numbers. It creates a new file and never overwrites an existing report. The final verification metadata records exact suite counts and the test-first failures/fixes. All Phase 1, Phase 2 and Phase 3A/3B economic code and configuration values remain unchanged.
