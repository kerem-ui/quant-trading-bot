# Phase 1A — ETF accounting convention

Scope: the existing ETF research backtester, its fills, and the reporting
calculations that depend on those fills. Strategies still return target weights.
Options, providers, strategy rules, and live execution are unchanged.

## Price basis and instrument units

The ledger uses **adjusted research units**, not raw broker shares:

```text
adjustment_factor[t] = adjusted_close[t] / raw_close[t]
adjusted_open[t]     = raw_open[t] * adjustment_factor[t]
valuation_close[t]   = adjusted_close[t]
```

`Order.fill_price`, quantities, marks, notional and cash movements all use this
same adjusted basis. Fractional units are allowed. An adjustment factor converts
the price scale; it is not a strategy input or a separate source of profit.
This is retrospective adjusted-data research accounting, not a claim that
vendor adjustment factors were available point in time at the open.

For example, raw open 200, raw close 220 and adjusted close 55 imply an adjusted
open of 50. A $500 allocation buys 10 research units, worth $550 at that close.

Adjustments already embedded in the provider's series are not booked again as
cash dividends, split events or changes in raw shares. Their precise treatment
depends on the supplied adjusted series. The ledger does **not** model dividend
receivables, payment dates, withholding, split-deliverable changes or tax lots.
It cannot reconcile raw broker positions or cash across corporate actions.
Revised adjustment history can change the units in a rerun; retain the input
data snapshot for reproducibility.

## Portfolio and fills

`Portfolio` stores cash, signed quantities and valid marks. Its equity and
weights are derived:

```text
equity = cash + sum(quantity[s] * mark[s])
weight[s] = quantity[s] * mark[s] / equity
```

Quantities change only through successful fills. At a rebalance's execution
time, mark all existing positions to the adjusted execution prices. Let E be
this common **pre-cost** portfolio equity. For each target w and fill price P:

```text
target_quantity   = w * E / P
executed_quantity = target_quantity - current_quantity
executed_notional = abs(executed_quantity * P)
cash_change      = -executed_quantity * P - transaction_cost
```

All orders in the batch use the same E, so alphabetical execution order does
not change target allocations. Fees are deducted from cash, not from the
quantity. A rejected order changes neither cash nor quantities and costs zero.
The order records signal/execution dates, target and prior decision weights,
actual executed quantity, adjusted price, absolute notional, transaction cost,
quantity before the fill, and the allocation equity E. Buy/sell classification
uses the actual signed fill, not the earlier target-weight difference.

The no-trade band is evaluated using execution-time actual exposure. A skipped
target leaves quantities unchanged. Exact full-exit targets sell/cover the
entire position even if its market value is tiny. Unchanged nonzero targets can
require real rebalancing trades after prices or equity change.

## Event ordering

For **next-open** execution:

1. Carry the previous close's actual quantities and cash into the day.
2. On a pending execution day, mark existing units at adjusted opening prices.
   Existing holdings earn the overnight move.
3. Convert targets and apply successful fills, with each fee charged once.
4. Mark the post-fill quantities at adjusted closing prices. Only these
   quantities earn the remaining open-to-close move.
5. Charge the existing carried-short borrowing convention, described below.
6. Derive net return from ending equity. Supply this completed day's net return
   to the existing risk pipeline when it processes the next strategy decision.

For **next-close** execution, existing holdings earn the move to that close
before fills. New positions earn no pre-entry return. On days without an
execution batch, marking the unchanged holdings directly to close captures the
same complete daily economic move without requiring an unused opening mark.

No fill is permitted on its signal date. Risk/strategy evaluation retains the
existing rebalance cadence; Phase 1A does not add continuous risk evaluation.
The historical risk argument name `prev_day_return` remains for API compatibility;
the engine now passes the latest completed day's **net** return.

## Costs and financing limitations

The existing equity cost model is unchanged. Commission, half-spread and
slippage basis points (and its minimum charge, if configured) are applied to
actual executed notional. They appear once as a cash deduction. The fill price
is not additionally shifted by the same spread/slippage charge.

The existing annual-basis-point, 252-observed-bar borrow convention is retained:

```text
borrow[s,t] = abs(carried_short_quantity[s]) * adjusted_close[s,t]
              * annual_borrow_bps / 10000 / 252
```

It uses quantities carried from the previous close, including an exit day, and
is charged after that day's closing mark. Newly opened shorts incur no entry-day
borrow fee. Five carried short units at 100 and 252 annual basis points cost
$0.05 per bar. Trading costs cannot shrink those units or their borrowing base.
A current closing mark is required for this charge even if the short was covered
at the open.

This is a deliberately limited research accrual convention. It does not model
actual/360 or calendar-day accrual, weekend/holiday accrual, intraday borrow,
locate availability, recalls, time-varying instrument borrow rates, short-sale
proceeds restrictions, cash interest, debit financing, margin or buying power.
Negative cash remains possible under the existing leveraged target interface;
no new interest or funding model is implied. Non-positive/non-finite equity
causes an explicit error, not a simulated margin liquidation or insolvency path.

## Valuation failures

Every required mark for a nonzero position must be finite and strictly positive.
Missing, nullable missing, zero, negative and infinite marks raise a valuation
error naming the symbol and date. A held instrument missing a required execution
mark prevents reliable execution-time portfolio sizing and fails explicitly.
An invalid execution price for an unheld instrument rejects its order.

Zero positions need no mark. Unheld marks can be missing in result tables; zero
P&L for a genuinely absent position is not an imputed return on a held position.
No forward-fill, last-price valuation or zero-return policy is silently imposed
on held instruments. Market closures, stale-but-present quotes and corporate
action correctness require separate data policies; Phase 1A does not add them.

## Returns, attribution, turnover and audit records

```text
net_return[t] = ending_equity[t] / ending_equity[t-1] - 1
```

Initial capital is the denominator on the first bar. Thus initial capital times
the compounded net returns reproduces ending equity, within floating-point
tolerance. Trading and borrowing costs are included once. Existing metrics,
drawdowns, stress and benchmark reporting consume these corrected net returns.

Results retain daily cash, quantities, valid held marks, per-symbol gross dollar
P&L, per-symbol trading/borrow costs, and copied ledger snapshots after each mark,
fill, rejection and borrow charge. These allow an independent replay of the cash
movements and quantities. There is no implicit terminal liquidation: open
positions remain marked at the last close, with no invented exit fee.

S02 per-symbol contributions are gross marked dollar P&L less the symbol's
trading and borrow costs, divided by prior ending equity. They sum to the daily
net portfolio return, including entry-day intraday P&L. Reported sums of daily
contributions remain arithmetic attribution, not compounded wealth allocation.

Turnover is actual absolute executed notional divided by batch allocation equity.
Weight drift is not turnover. Entries, exits and resizing use executed quantities;
sign reversals retain the existing reporting category of resizing.

The S01 holding-period diagnostic in `scripts/research_edge.py` also uses the
recorded dollar P&L and actual costs, normalized by initial capital. Its intervals
include the real exit bar and do not overlap a later trade's costs. The script's
separate S03 pair research calculation is not a run of this ETF ledger and is
not certified by these accounting tests.

Risk caps constrain target allocations. Actual weights subsequently drift with
prices and cash costs; maintaining a continuous exposure cap would require
additional real trades and risk policy, which are outside Phase 1A. The S01 cap
test now verifies the unchanged allocation cap, exact executed allocation and
daily holdings-to-weight reconciliation rather than assuming free rebalancing.
The existing no-trade-band test likewise checks every executed trade directly.

## Validation and environment

`tests/test_etf_accounting_regressions.py` retains all original 14 cases without
weakening their economic assertions and adds event replay, adjusted-basis,
quantity sizing, cost, attribution, missing-mark and boundary-case tests.
The S01 diagnostic unit test loads its actual reporting function definitions
without importing the surrounding S03-dependent CLI, then supplies a real
hand-checkable backtest result. This tests that calculation only; it does not
claim the full `research_edge.py` CLI can import or execute in this environment.

Run with the existing environment (no pytest cache or bytecode writes):

```powershell
& .\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -o addopts='' -q --tb=short tests/test_etf_accounting_regressions.py
```

The existing `statsmodels` 0.14.6 installation is incomplete: its RECORD lists
1,396 non-bytecode package files, of which 1,124 were absent at inspection.
`statsmodels/__init__.py` imports the absent `statsmodels/compat/patsy.py`.
This blocks collection of `test_v2_improvements.py`, `test_v21_cleanup.py` and
`test_s03_pairs.py`. The cause of the missing installation files cannot be
determined from the current repository. No packages were installed, removed,
upgraded or downgraded, and no stub was substituted to conceal this failure.

### Observed test results (2026-09-17)

- Before the ledger implementation: 27 failed, 2 passed in 1.33 seconds. This
  included all original 12 failing cases, their two passing controls, and the
  new ledger/event tests.
- After the initial implementation: 29 passed in 1.27 seconds.
- The first existing-test run had 40 passed and 1 failed in 77.07 seconds:
  the S01 test still assumed held weights could never drift past the target cap.
  It was corrected to enforce the same cap on actual allocations and independently
  reconcile all daily weights, without clipping economically real holdings.
- Rechecking the blocked modules alone produced 3 collection errors in
  0.78 seconds, all for the missing `statsmodels.compat` package.
- Boundary tests then reproduced two defects (tiny-value exits and nullable
  missing marks): 2 failed, 34 passed in 1.59 seconds. Both were corrected.
- The affected combined selection completed with 78 passed and 3 collection
  errors in 81.94 seconds: 37 accounting cases plus 41 existing tests passed;
  the three statsmodels-dependent modules above could not collect.
- The additional S01 diagnostic regression first failed as expected: it
  reported 0.10195357515 instead of 0.20758121 of initial capital. After its
  calculation was corrected, the final accounting file had 38 passed in
  1.45 seconds. The existing original 14 assertions remain intact.
  The isolated red run was 1 failed, 37 deselected in 0.74 seconds.

In total, 79 distinct tests passed. This is not a claim that the full project
suite, the three blocked modules, or the complete research CLI passed.

### Rerun hand examples

All examples begin with $1,000. Quantities are adjusted research units; numbers
below are rounded for readability.

| Example | Ending cash | Ending quantity | Ending equity | Cost |
|---|---:|---:|---:|---:|
| Rejected $500 buy, later price rises | 1,000 | 0 | 1,000 | 0 |
| $500 next-open buy at 100, close 110 | 500 | 5 | 1,050 | 0 |
| $500 buy at 110, close 110 | 500 | 4.545454545 | 1,000 | 0 |
| Next-close buy at 110 after open 100 | 500 | 4.545454545 | 1,000 | 0 |
| Five units held through 100 → 110 → 100 | 500 | 5 | 1,000 | 0 |
| Flat 100 price; $500 long entry with 10 bps cost | 499.50 | 5 | 999.50 | 0.50 |
| Flat short, 10 bps entry cost and three carried bars at 252 annual borrow bps | 1,499.35 | -5 | 999.35 | 0.50 trading + 0.15 borrow |
| Five units carried from 100; open 120, resize to 25%, close 132 | 825 | 2.291666667 | 1,127.50 | 0 |

The round-trip price example has net returns +5% and -4.7619047619%, compounding
to no profit. The fee example's entry-day net return is -0.05%. Risk receives
that same -0.05% when making the close decision, and receives -5% in the separate
half-invested 10% market-loss example. A missing held mark raises
`Invalid valuation price for ETF on 2024-03-28: nan`.

Maximum absolute equity-versus-compounded-return difference across these reruns
was approximately $1.14e-13. Event replay independently checks each executed
quantity, signed cash movement, cost, market mark and equity identity.
