# Phase 3B - Execution realism and strategy mechanics

This phase starts at `b2af307c717cc92c9afad3d64a3dd1a489157871` on
`phase3-backtest-quality`. It preserves the Phase 1 cash/quantity ledger,
options accounting and generic risk invariants, the Phase 2 locked environment
and external data/provenance architecture, and Phase 3A market mechanics.
No historical data, dependency versions, strategy thresholds or configuration
values were changed. This is a daily research simulator, not live execution.

## Confirmed defects and changes

1. `build_pair_orders` ignored its beta argument and returned equal-dollar
   legs although `compute_spread` uses level prices `A - beta*B`. Sizing now
   replicates that spread. Invalid active beta fails explicitly.
2. Generic per-leg caps and exact net neutrality could destroy a pair hedge.
   Structured risk uses one proportional scale for the whole netted book.
   The exact-neutrality option remains intact for other callers and its Phase
   1C tests; S03 uses a separate `hedged` volatility hint.
3. Independent next-session conversion of decision-date weights could distort
   beta after an overnight gap. Pair identity, signal, beta and gross allocation
   now reach the execution layer, which rebuilds both legs at execution prices
   and rechecks hard caps proportionally.
4. Independent fills could create one leg when the other was rejected. S03
   trial fills now reach the ledger only after the entire batch is executable.
5. S02 excluded ineligible names after factor ranking. Raw price/ADV eligibility
   and finite history for every nonzero-weight factor now precede all ranking.
   Its liquidity factor and eligibility ADV use raw close times raw volume.
6. S01 compared adjusted peaks/prices to raw-OHLC ATR. Both binary and conviction
   paths now convert OHLC to the same adjusted research basis before ATR.
7. `min_commission` formerly floored the combined fee/spread/slippage total;
   it could swallow spread/slippage charges. The minimum now applies only to
   commission; all four cost components remain separately identifiable.
8. Risk/exit decisions were gated on the scheduled rebalance, delaying daily
   losses, stops and pair exits. Daily exits/reductions now execute next session;
   scheduled entries and ordinary resizing retain the strategy cadence.
9. No execution capacity policy existed. A configurable causal dollar-volume
   budget now limits ordinary orders or rejects an unexecutable pair batch.

The unchanged-target/resize/reversal/exit control already passed before changes:
Phase 1 correctly charged only executed quantity deltas. That behavior remains.

## Approved S03 specification migration

The old documentation and tests required exact dollar neutrality. The user
explicitly approved replacing that requirement because it contradicts the
existing price-level spread except in special cases.

For positive finite beta, prices PA/PB, equity E, gross allocation g and
signal d in {-1,+1}:

```
spread = A - beta*B
k = E*g / (PA + beta*PB)
qA = d*k
qB = -d*beta*k
notional_A = d*k*PA
notional_B = -d*beta*k*PB
gross = k*(PA + beta*PB)
net = d*k*(PA - beta*PB)
```

Long spread is `(+1,-beta)`; short spread is `(-1,+beta)` under one scalar.
Pre-cost P&L between trades is `d*k*(delta_A - beta*delta_B)` for the frozen
executed beta. A rolling beta change is a new sizing decision, not free P&L or
an unrecorded holdings change. Beta estimation, z-scores, thresholds and the
pair signal state machine are unchanged. Positive beta is required for this
long/short ETF strategy: zero, negative, NaN and infinity fail on an active
allocation. Nonpositive beta would not describe its intended two-sided hedge.

`risk_per_pair` retains the old **gross budget** of `2*risk_per_pair`; its name
does not imply a guaranteed maximum loss. Optional `target_gross` retains its
existing meaning: gross of the netted instrument book. Overlapping pair
allocations are retained as components, summed into actual instrument targets,
and all receive the same portfolio scale. This is conservative: one constrained
pair can reduce the entire book rather than maximizing independent allocations.

Position, strategy per-name, sector, gross and absolute net caps bound the
common scalar. A zero net limit on a non-neutral pair yields a zero allocation;
no leg is enlarged or independently cut to manufacture neutrality. The same
caps are rechecked at execution prices. Allocation weights use pre-cost equity,
as in Phase 1; costs and subsequent price changes can drift marked weights.
Ordinary drift is not a hidden daily rebalance mandate.

Pair plans use adjusted signal units. In explicit raw-share accounting, each
leg converts via its adjusted/raw factor before raw shares are booked. Raw
splits also update carried component quantities; beta is still stated in the
signal's adjusted units. Missing required held marks still fail explicitly.

### Atomic execution policy

The **entire S03 batch** is atomic, including overlapping pairs and exits.
Both valid execution prices and (if enabled) sufficient capacity are required
before any trial fill changes cash or quantities. If a leg fails or would only
partially fill, every trial fill is rejected with zero executed quantity,
notional and costs. Existing holdings remain. There is no legging model.

Capacity-limited pair entries are rejected rather than partially executed.
A failed exit may leave a real existing position open; it is explicitly recorded
and marked, never replaced by fabricated liquidation proceeds. Normal future
strategy decisions can retry. No perpetual retry queue or fill-probability model
is implied. The per-name no-trade band does not clip legs of structured targets.

## S01 and S02 conventions

S01 keeps its long-only trend hypothesis, inverse-volatility sizing, entry cost
filter, thresholds, binary/optional conviction modes and configured rebalance
frequency. Both ATR paths use `adjusted_ohlc`, multiplying each OHLC bar by
`adjusted_close/raw_close`. Input data is not modified. Return volatility and
signals already use adjusted prices. Equivalent raw split-like scaling with the
same adjusted price history now gives identical ATR and signals.

S02 keeps its price-only factor definitions, factor weights, top-quantile
selection, equal-weight allocation and per-name cap. Its membership mask is
computed at the decision close from raw price, trailing 21-session raw dollar
volume (10 observations minimum), and finite required factors. An ineligible
instrument cannot enter any factor's rank denominator. Zero-weight factors do
not impose history requirements. This fixes cross-sectional eligibility leakage;
it does not supply missing point-in-time fundamentals or constituent histories.

## Decision and execution cadence

| Strategy/control | Evaluation | Execution |
|---|---|---|
| S01 entry/ordinary sizing | Configured rebalance, weekly by default; causal daily features | Next session open or close |
| S01 soft exit | Each completed session, executed-entry minimum holding period | Next session; never same-bar |
| S01 hard ATR stop | Each completed session, peak since executed entry | Next session; not delayed by minimum hold |
| S02 ranking/features | Daily causal panel | Entries, exits and resizing at configured monthly rebalance |
| S03 pair reselection | Monthly walk-forward, unchanged | Positions react through sizing/exit policies |
| S03 entry/beta re-sizing | Weekly, unchanged | Atomic next-session batch |
| S03 reversion/stop/correlation/max-signal-hold exit | Daily signal state, unchanged thresholds | Remove exited components next session; surviving components retain quantities |
| Central daily loss/drawdown | Completed current net return/equity each session while held | Next-session reduction/flattening |
| Allocation caps and volatility sizing | New scheduled allocations; structured caps also at execution | Actual delta fills |

S01's executed-position guard measures minimum holding in sessions since the
successful fill; hard stops and central risk reductions override soft holding
requirements. S03's existing maximum-holding counter remains a **signal-state
session counter**, not a guarantee of a fixed number of executed holding days.
An entry can be delayed by the weekly schedule or rejected; a rejected exit can
extend actual holding. The trace distinguishes these cases. Daily exit processing
does not turn S02 into a daily factor-rebalanced strategy or permit off-cycle
entries. No tick/intraday stops are inferred from OHLC.

Between rebalance dates, ordinary market drift alone does not force trades or
bypass the no-trade band. Daily loss/drawdown reductions and explicit exits can
bypass that band. Off-cycle ordinary orders preserve held quantity reductions
and use the stricter execution-time allocation/unit bound after a gap.

## Daily capacity and cost convention

`BacktestEngine(max_participation=0.01)` sets a per-symbol execution budget of
1% of **raw close times raw reported volume on the decision session**. That
observation is available before either next-open or next-close execution. It
is a previous-session capacity proxy, not observed depth at the fill instant.
Future execution-session volume never approves an earlier fill.

Budget in dollars is converted to the run's execution-price units. Ordinary
orders may partially execute; their unfilled remainder is not silently carried
as a pending order. A future strategy decision can submit the remaining delta.
S03 requires a fully executable atomic batch and rejects any capacity shortage.
Missing, zero, negative or non-finite required liquidity rejects the order.

Default `max_participation=None` preserves the historical **unconstrained small-
portfolio research assumption**, recorded in result configuration. It must not
be used to claim scalability to arbitrary capital. The option is an engine
argument; no existing strategy parameter or default was silently changed.

The observed adjusted open/close (or explicit raw-mode open/close) remains the
fill reference. Daily data contains no observed bid/ask depth. Costs are separate
cash charges on executed absolute notional:

- commission = max(configured minimum commission, notional * commission bps);
- spread = notional * assumed half-spread bps;
- slippage = notional * additional fixed slippage bps;
- optional existing impact = notional * impact coefficient * sqrt(participation).

All bps terms divide by 10,000. No minimum applies to zero executed notional.
The impact model retains its existing participation clamp at 100%; it is an
uncalibrated scenario parameter, disabled by default. Enabling impact requires
valid known dollar volume even if no capacity cap is configured. The broker
does not also adjust reference prices for these cash charges. Buy and sell
costs are adverse once each; Phase 1B options cost behavior is untouched.

## Diagnostics and reconciliation

`result.decisions` records decision date, signal, intended and risk-approved
weights, pair specifications and scheduled-rebalance/daily-exit-or-risk reason.
Join its date to `Order.signal_date`. Orders record execution date/reference
price, requested quantity delta, executed delta, absolute notional, pre-fill
quantity, common allocation equity, capacity outcome, known liquidity budget,
cost components and rejection note. Resulting quantity is pre-fill quantity
plus executed delta. `result.ledger` supplies reconciled cash, quantities, marks
and equity after each event, including accepted/rejected pair plans. The four
execution cost components are also summed by `cost_attribution()`.

Outcomes are `fully_executable`, `capacity_limited`, `rejected_price`,
`rejected_liquidity` or `rejected_atomic`. A no-trade-band skip produces no fill
or cost; intended/approved targets and held ledger state remain available.
Turnover is executed absolute notional divided by common pre-cost batch equity.
Target declarations and price drift themselves do not count as turnover.

## Hand-checkable examples

All examples start with equity/cash 10,000 unless otherwise stated. Costs are
zero except in the explicitly costed rows. No borrow rate or cash interest is
introduced in these fixtures; Phase 3A tests separately preserve those charges.

| Example | Executed quantities / dollar notionals | One-way turnover | Cost | Cash / marked positions / equity |
|---|---|---:|---:|---|
| Long spread, beta=2, A=100 B=40, gross=180 | +1 A / -2 B; +100 / -80 | .018 | 0 | 9,980 / +20 / 10,000 |
| Short spread, same inputs | -1 A / +2 B; -100 / +80 | .018 | 0 | 10,020 / -20 / 10,000 |
| A rises 2, B rises 1 after long entry | Held +1 / -2; market P&L +2 -2 = 0 | 0 additional | 0 | 9,980 / +20 / 10,000 |
| Net cap .001 (10 dollars), same long pair | +.5 / -1; +50 / -40; gross 90, net 10 | .009 | 0 | 9,990 / +10 / 10,000 |
| Entry after A gaps to 120, B=40, gross budget 180 | +.9 / -1.8; +108 / -72 | .018 | 0 | 9,964 / +36 / 10,000 |
| Missing B execution price | Both legs rejected | 0 | 0 | 10,000 / 0 / 10,000 |
| Pair capacity shortage on B | Entire entry rejected | 0 | 0 | 10,000 / 0 / 10,000 |
| Failed pair exit due to missing B liquidity | Prior +1/-2 preserved | 0 additional | 0 | 9,980 / +20 / 10,000 |
| Single-name target .5, price100, prior volume1000, capacity1% | Requested50, executed10; notional1,000 | .1 | .60 at 1+2+3 bps | 8,999.40 / 1,000 / 9,999.40 |
| Same capacity in adjusted units, reference50, rawclose100 | Requested100, executed20; notional1,000 | .1 | .60 | 8,999.40 / 1,000 / 9,999.40 |
| Commission minimum1, spread2bps, slippage3bps on notional1,000 | +10 at reference100 | .1 | 1+.20+.30=1.50 | 8,998.50 / 1,000 / 9,998.50 |

The original equal-dollar allocation at gross180 held +.9 A and -2.25 B;
`delta_A=2, delta_B=1` incorrectly lost .45 instead of zero. The original
independent next-open conversion at target weights .01/-.008 and prices120/40
produced +.833333/-2 instead of +.9/-1.8. The old minimum-commission formula
charged 1.00 on the costed example, swallowing .50 of separate spread/slippage.

For unchanged/resize/reversal/exit at fixed price100:

| Target weight | Executed delta | Held quantity | Cash | Marked position | Equity | Turnover |
|---:|---:|---:|---:|---:|---:|---:|
| .10 | +10 | 10 | 9,000 | 1,000 | 10,000 | .10 |
| .10 unchanged | 0 | 10 | 9,000 | 1,000 | 10,000 | 0 |
| .05 | -5 | 5 | 9,500 | 500 | 10,000 | .05 |
| -.05 | -10 | -5 | 10,500 | -500 | 10,000 | .10 |
| 0 | +5 | 0 | 10,000 | 0 | 10,000 | .05 |

Total turnover is .30; there are four actual orders. Costs would apply to
1,000+500+1,000+500 of executed notional, not to gross declarations.

S02 rank fixture: eligible A/B/C rank 1/3, 2/3, 1. An extreme ineligible X
previously changed them to 1/4, 2/4, 3/4. They now remain 1/3, 2/3, 1 with or
without X. Incomplete required-factor history likewise cannot distort ranks.
S01 fixture: raw high101/low99/close100 and adjusted close50 becomes adjusted
high50.5/low49.5/close50, true range1. Equivalent raw split scaling leaves ATR
and signals unchanged; previously the ATR path received high101/close100.

The daily risk fixture enters 10 shares at100 on Monday, then closes Tuesday
at90: market loss100, cash9,000, equity9,900. A configured .5% daily-loss trigger
halves the holding next session to5 shares, releasing450 cash: cash9,450,
marked position450, equity9,900. It no longer waits until the weekly rebalance.

## Verification

Test-first failures were observed before implementation for beta sizing/validation,
S02 price/liquidity eligibility, S01 price basis, minimum commission, missing
capacity API, overnight hedge distortion, non-atomic entry, daily exit/risk
cadence, incomplete factor history and executed minimum holding.
The initial batch was 11 failures and one passing delta-accounting control.
No Phase 1 economic assertions were weakened. Legacy tests requiring exact
S03 neutrality were replaced only after the documented approval, with exact
quantity-ratio, gross-budget, exposure-cap and diagnostic reconciliation checks.

Final verification on September 18, 2026, CPython 3.12.10:

| Verification | Result |
|---|---|
| New Phase 3B cases | 44 passed in the final full run |
| Phase 1A ETF regressions | 38 passed |
| Phase 1B options regressions | 65 passed |
| Phase 1C risk/configuration regressions | 75 passed |
| Phase 2B storage/provider cases | 42 passed |
| Phase 2C migration cases | 20 passed |
| Phase 3A mechanics cases | 44 passed |
| Combined affected-suite run before final edge refinements | 388 passed in 261.91 seconds |
| Focused execution/accounting rerun after liquidity/history refinements | 99 passed in 27.56 seconds |
| Final complete project suite | **1,535 passed, 14 skipped in 348.93 seconds** |
| Final failures / collection errors / pytest warnings | **0 / 0 / 0** |
| `uv lock --check --offline` | Passed, 72 packages resolved |
| `uv pip check` against the project environment | All 72 installed packages compatible |
| Dependency/configuration/data changes | None |

The 14 skips are existing optional SEC-cache integration checks: five AI,
four energy and five semiconductor cases. No skips or xfails were added.
An earlier complete run passed 1,534 cases with the same 14 skips; the final
rerun includes the additional rejected-order diagnostic regression. All final
source changes were present for the 1,535-pass run.

Final full-suite command:

```powershell
python -B -m pytest -p no:cacheprovider -o addopts='' -q -ra
```

Acceptance is satisfied for the deterministic daily S01/S02/S03 examples under
the documented conventions: signals, approved targets, executed quantities,
net/gross exposures, turnover, fees, cash, marks and equity reconcile. Pair
ratios survive risk and execution, eligibility cannot affect ranks from outside
the investable set, and capacity/cost assumptions are explicit. This acceptance
does not remove the realism limitations below or authorize Phase 3C.

## Remaining limits

- Daily reference prices and assumed spreads do not reproduce auctions, order
  queues, intraday stops, actual depth or fill probability. No calibrated impact
  or live-execution claims are made.
- Prior-session volume is a causal proxy, not a guarantee of execution-day
  liquidity. Unconstrained default runs cannot support arbitrary capital sizes.
- Atomic whole-book rejection/scaling is conservative and can reject feasible
  subsets. There is no legging, independent pair optimization or automatic
  indefinite retry service. A rejected risk exit can leave exposure outstanding.
- S03 freezes a causal decision beta for execution/holding. Its rolling signal
  and maximum-holding counter remain signal-state conventions; rejected orders
  and weekly entry schedules can make actual holding duration differ.
- Caps describe allocations before fees, not a promise that drifting closing
  weights are always below those numbers. Daily loss/drawdown and scheduled
  reallocation govern subsequent exposure; no unfilled clipping is permitted.
- Phase 3A calendar range, supplied corporate-action requirements, adjusted
  research-accounting convention, financing assumptions and borrow limitations
  remain. No new historical rate/action/locate data was invented.
- Strategy-level alpha, survivorship bias and dataset completeness are not
  certified by reconciled execution examples. No Phase 3C work is included.


## Files changed

Source (12):

- `src/quantbot/backtest/broker.py`: causal capacity, explicit fill outcomes and cost components.
- `src/quantbot/backtest/engine.py`: structured execution, daily exits/risk and decision trace.
- `src/quantbot/backtest/order.py`: requested/executed quantity and capacity/cost diagnostics.
- `src/quantbot/backtest/structured_execution.py`: atomic pair repricing/rejection and common scaling.
- `src/quantbot/costs/slippage.py`: clarify additional slippage versus spread assumptions.
- `src/quantbot/costs/transaction_costs.py`: separate equity charges and commission-only minimum.
- `src/quantbot/indicators/volatility.py`: explicit adjusted OHLC conversion.
- `src/quantbot/risk/risk_manager.py`: proportional structured caps and separate hedged hint.
- `src/quantbot/strategies/base.py`: document distinct risk hooks.
- `src/quantbot/strategies/s01_trend_following.py`: consistent ATR and actual-holding exit guard.
- `src/quantbot/strategies/s02_factor_blend.py`: eligibility/history before ranks and raw dollar liquidity.
- `src/quantbot/strategies/s03_pairs_mean_reversion.py`: price-aware beta-matched allocation and pair metadata.

Tests (4):

- `tests/test_phase3b_execution.py`: 44 deterministic regression/invariant cases.
- `tests/test_s03_pairs.py`: approved exact-hedge replacement for legacy neutrality assertions.
- `tests/test_v2_improvements.py`: approved risk-hint/hedge tests; existing no-trade-band assertions retained.
- `tests/test_v21_cleanup.py`: verify actual net-exposure diagnostics and exact component hedges.

Documentation (2): `README.md` and this guide.

No Phase 1 regression files, Phase 2 storage/migration tests, Phase 3A tests,
configuration values, dependency declarations, lockfiles or historical datasets
were edited. During final edge checks, missing volume columns, overflowing
liquidity, late-starting instrument histories and mutable raw-split diagnostic
records were each reproduced before correcting the new execution paths.


Rejected fills retain the actual pre-trade quantity and allocation equity as
well as the requested delta. This diagnostic regression was reproduced and
corrected without changing cash, quantities, pricing or cost economics.
