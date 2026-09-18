# Phase 4B: approved S05 defined-risk short volatility

S05 is a reproducible daily options research strategy, not evidence of alpha or
live readiness. The approved parameters were sealed before historical performance
execution in `research/phase4b/s05-v1/specification.json`. Its file SHA-256 at
creation was `996afd429eb4461408c8a5c2cce81fdd7e9f214e02cefbfabcfbad14b563b4f0`.
The baseline Git commit was `7ea0865d60192cd076659e13c3c6800bf62fd933`.

## Specification recovery and approval

`STRATEGY_PLAYBOOK.txt:509-623`, the original S05 stub, canonical configuration,
and `indicators/options_features.py` establish IV-versus-EWMA-RV, ATM30, 70th IV
percentile, five annualized volatility points, 30-45 DTE, defined risk, 21-DTE
exit and short-strike breach. Canonical profit/stop parameters were .50 and 2.0.
The original playbook listed alternative structures/estimators, delta ranges,
undefined event/panic filters and incomplete long-vol exits. Later V5.9 scripts
were feature/sample-size diagnostics, not an executed or frozen S05 strategy.
Those observed results were not used to select parameters.

Implementation stopped for explicit user approval. The user approved the minimum
short-volatility iron-condor specification and clarified that profit/stop tests
use **gross executable liquidation debit**, not fee-adjusted P&L. The long-vol
branch and undefined event/panic filters are explicitly omitted. No thresholds,
widths, lookbacks or holding parameters were changed in response to results.

## Frozen conventions

- SPY and QQQ are separate $100,000 funded research runs. IWM options unavailable.
  No combined ledger or portfolio return is reported.
- Provider IV only. Phase 4A nearest spot-strike call/put ATM mean, both sides
  required, at 30 calendar DTE. Total-variance interpolation only inside observed
  positive tenors <=45 DTE; no extrapolation or local-IV fallback. Selected
  brackets/interpolation status are recorded. Provider analytics are uncertified.
- EWMA uncentered squared simple adjusted-close returns, lambda .94, annual252.
  Seed the first squared return; require20 consecutive valid returns. Invalid or
  missing underlying session resets the state/warm-up. Existing Phase 3C sealed
  adjusted-close CSVs only, truncated at each feature horizon; no new retrieval.
  This current variance estimate is a constant-variance 30-day forecast proxy,
  not a calibrated term forecast. Raw chain spot is used for strikes/breaches.
- IV percentile:252 exchange-session slots including today, minimum126 valid IV
  observations including today; fraction of valid earlier IV strictly below the
  current IV. Nulls consume time slots, never denominator counts or zero values.
- Signal: percentile>=.70 AND IV30-RV>=.05 (decimal annualized volatility).
  Record IV, RV, percentile, spread, available history and eligibility daily.
- Entry only first US exchange session of ISO week. Missing first session/data
  does not permit catch-up. One open structure and one contract per leg.
- Earliest decision-day expiration in30-45 DTE. Shorts nearest signed +/-.20,
  absolute delta band[.15,.25], OTM, ties lower strike. Distance comparison rounds
  only floating representation noise to12 decimals. Wings use the smallest
  common outward listed strike width, <=$10. Identity is chosen before quote
  gates; no search for wider, more favorable or more executable alternatives.
- Positive gross credit less than wing obligation. Retain central options limits
  including $500 credit cap, $1,000 loss cap, one position and <=$10 width.
  Defined loss plus normal round-trip explicit fees <=1% of min(initial,current
  equity), also <=$1,000. Aggregate cap5% initial, stricter than canonical8%.
  Reserve full wing obligation plus entry/exit fees from pre-credit cash.
  These checks are repeated at actual fill quotes before any ledger mutation.
- Signal at t; fixed contracts attempted atomically at the next available valid
  exchange-session observation, not the same observation or an inferred open.
  Entry already at/below exit DTE is rejected. Missing whole session gaps are not
  filled synthetically. Daily labels do not prove intraday synchronization.
- Buy ASK/sell BID, positive bid, finite non-crossed quotes and per-leg
  (ask-bid)/mid<=20%. No options last-price executions. $0.65 per contract/side
  commission plus $1 per multi-leg execution explicit slippage. Spread crossing
  is already in premium cash flows, with no second spread charge.
- C=gross executed entry credit, D=gross executable whole-condor close debit.
  Profit D<=.50C; stop D>=2C. Fees NEVER move either threshold. Daily exits also
  test DTE<=21 or spot reaching/breaching either short strike. Record all triggers;
  primary reason order is DTE, strike, stop, profit. No extra time/reversal/hold
  rule. Credit exits require executable quotes; invalid liquidation quotes do not
  fabricate D. DTE/strike triggers may still queue an attempted close.
- Atomic close is attempted on a later observation; rejected close retries under
  the existing engine. Trigger prices are not guaranteed execution prices.
- Missing required marks fail explicitly. Terminal liquidation retains normal
  executable bid/ask gates or fails. Expiration retains exact-date intrinsic cash
  research settlement, no expiry commission; early assignment/physical shares
  are unsupported. Defined expiry loss is not a bound on all liquidation/assignment
  costs. Missing provider Greeks/OI stay unknown, never substituted with zero.

## Implementation and compatibility

The existing S05 placeholder now implements `OptionsStrategy` in
`strategies/s05_implied_vs_realized_vol.py`. It does not masquerade as an equity
weight strategy. The dedicated runner opts into the sealed specification; the
canonical generic activation flag remains false. Existing canonical thresholds
are fingerprint-checked, not silently overridden. `options/s05_spec.py` provides
immutable parameters; `options/s05_features.py` computes causal research inputs.

The only shared execution change is an optional `admit_execution` hook after
central risk approval and actual quote calculation but before cash/position
booking. Its default accepts the existing central decision; duck-typed legacy
strategies without the hook are unchanged. S05 uses it for stricter funding and
fee-inclusive risk checks. Accounting, pricing, Phase2 schema, market data,
existing strategy parameters and dependency versions are unchanged.

`research/phase4b.py` verifies sealed specs, canonical config, lock, corpus,
partition manifests/Parquet and underlying CSV checksums. Input/source hashes are
checked again after execution. Generated outputs are write-once under ignored
`runs/phase4b/`; legacy report directories are rejected. Each symbol has signals,
decisions, exit observations, orders, trades, rejections, event ledger, equity,
exposure and provider-Greek output. The top-level report and sealed manifest
identify code base commit/dirty state, exact source text hashes, data identities,
parameters and every output hash. Source hashes identify uncommitted implementation
bytes at execution; publication commit can be later. Git LF/CRLF-equivalent
configuration text is accepted, but market inputs retain byte-exact checksums.

Returns compound to every equity observation; each event satisfies cash+signed
marks=equity. Closed premiums less explicit fees equal trade P&L and final cash.
Reconciliation uses rtol1e-12/atol1e-8, not NumPy's default relative tolerance.
Turnover is sum of absolute executed option-premium notionals/initial capital,
not underlying turnover. Exposure labels distinguish gross/net marked option
value, defined expiry loss, fee-budgeted risk and reserved cash. Provider Greeks
remain explicitly in uncertified vendor units. No margin/borrow/interest model
or options capacity guarantee is invented.

## Deterministic economic examples

All use one contract per leg, multiplier100, and $100,000 initial cash. A $5-wide
condor receives $100 gross credit. Entry fee/slippage=$3.60; cash=$100,096.40.
Initial executable liquidation liability=$120: equity=$99,976.40, loss=$23.60.
Defined expiry loss=$400; fee-budgeted risk=$407.20; cash reserve=$507.20.

| Observation / later execution | Closing debit | Total explicit fees | Net P&L | Ending equity |
|---|---:|---:|---:|---:|
| Profit observed50; later fill50 |50|7.20|42.80|100042.80|
| Profit observed50; later fill40 |40|7.20|52.80|100052.80|
| Stop observed200; later fill200 |200|7.20|-107.20|99892.80|
| Stop observed200; next observation gaps to250 |250|7.20|-157.20|99842.80|
| Normal terminal close at120 |120|7.20|-27.20|99972.80|
| Exact-date OTM intrinsic expiry |0|3.60|96.40|100096.40|
| Missing fill leg / failed risk admission |no fill|0|0|100000.00|

The expiry fixture deliberately spans a large observation gap and verifies the
existing cash-settlement convention, not the usual21-DTE strategy exit. A missing
held-leg quote stops the run with prior valid state intact, never a zero mark.
The execution-day risk test uses $41,000 equity: $100 decision credit implies
$407.20 risk (fits$410); actual $90 credit implies$417.20 (reject, no holdings).

## Data requirements for Phase 4C (not started)

Primary need: more years of daily options with coherent underlying prices,
reliable observation dates/timestamps, warm-up history and genuine unexamined
periods. Several regimes and enough completed trades matter more than a positive
single example. Longer QQQ history is required before the frozen percentile can
operate. No rule was relaxed to manufacture its trades.

Coverage beyond45 DTE is not required for this specification; consistent bracketing
around30 DTE and the actual selected contracts through exit is required. Historical
rates/dividend expectations support independent model validation; dividend dates/
amounts and reference terms matter for assignment analysis. They are not silently
invented for the provider-IV signal. OI is not required by this frozen strategy.
Intraday quotes would be needed for intraday execution/stops/hedging, not this daily
model. Quote sizes would improve capacity evidence; even a one-lot assumption is
not proof of available liquidity. Extra underlyings improve breadth, but are not
required merely to implement SPY. No subscription purchase is made or prescribed
without connecting it to these requirements.

## Reproduction

Use the unchanged locked Phase2 environment. Restore existing source files from
the separate data archive and verify against the frozen specification; a Git clone
alone intentionally does not include market data. Set environment variables to
local data locations, without putting machine-specific paths or secrets in Git.

```powershell
python -B scripts/run_phase4b.py --data-root $env:QUANTBOT_DATA_ROOT `
  --underlying-sources $env:QUANTBOT_S05_UNDERLYING_SOURCES `
  --output runs/phase4b/new-unique-run
python -B -m pytest tests/test_phase4b_s05.py tests/test_phase4b_research.py
python -B -m pytest
uv lock --check --offline
uv pip check --python $env:VIRTUAL_ENV/Scripts/python.exe
```

The approved sealed specification is fixed; the runner exposes no parameter
optimization/override flags. See `phase4b_s05_results.md` for measured results and
verification. One observed trade cannot support an edge verdict; QQQ is explicitly
data-insufficient. No Phase4C work, new providers or live execution was introduced.