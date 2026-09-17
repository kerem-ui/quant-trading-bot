# Phase 1B — Options accounting and fill correctness

Date: 2026-09-17. Scope: the existing daily historical options backtester.

No ETF accounting implementation, strategy, provider, live execution, broker submission,
dependency, or environment was changed. No Phase 1C work was started. Existing unrelated
working-tree changes and the immutable Phase 0 backup were preserved.

## Historical accounting convention

- Strategies still propose the existing defined-risk, same-expiration verticals.
- A decision on date t can execute only on a later available chain date.
- The engine supports standard 100-multiplier contracts. Nonstandard multipliers and
  mismatched leg identities are rejected; adjusted deliverables are not approximated.
- Contract identity includes underlying, expiration, call/put, and exact strike. The
  lookup does not use approximate strike matching. Duplicate matches fail explicitly.
- Every leg must have finite, nonnegative, non-crossed bid/ask quotes. Executions also
  require a positive bid and the configured spread-percentage limit. Buys pay ask;
  sells receive bid. Last price and midpoint are never fallback executable prices.
- A structure is atomic: all fills are checked before cash or holdings change.
  No partial structures, partial fills, or legging are modeled.
- Open marks use bid for long legs and ask for short legs. A finite, uncrossed zero
  bid can legitimately mark a long at zero, but cannot execute under the existing
  positive-bid fill gate. A quote outside the execution spread gate can still be a
  conservative mark; that does not imply it is executable.
- Missing, non-finite, crossed, stale-date, or multiplier-mismatched required marks
  raise an error naming the contract and valuation date. All legs of the affected
  position retain their prior valid marks and P&L. The run returns no completed
  result using a fabricated zero or a stale mark presented as current.
- Normal close rejection retains the complete position and requeues the close.
  A missing/invalid required held mark still stops that run. A wide but otherwise
  valid quote may be marked while a close waits.
- Final-bar liquidation is an explicit research convention, using that bar's quotes
  and the normal fill gate. It can occur after an entry on the final bar. If any leg
  cannot execute, the affected structure stays open, the failure is recorded, and
  the run raises rather than reporting a fictitious completed backtest. Other
  independently completed structures are not rolled back.
- On the exact expiration date, held contracts settle together to signed intrinsic
  cash using a finite, nonnegative, consistent spot for their own underlying.
  Settlement is processed before queued daily orders; pending closes cannot also
  close an expired structure. Entry on or after expiration is rejected. A skipped
  expiration date raises before an expired position can trade on a later date.
- Settlement does not require option bid/ask if a valid same-underlying settlement
  observation exists in the chain that day. Missing underlying spot is never
  replaced with strike, another underlying's spot, or a later day's spot.

This is **intrinsic cash research accounting**, including when input rows say
`exercise_style=american`. It is not actual physical delivery or an American
assignment model. The chain's underlying observation is a modeling input, not a
verified official exchange settlement fixing. There is no early exercise, dividend
assignment optimization, stock delivery, pin risk, AM/PM fixing selection, settlement
lag, exercise fee, or broker reconciliation. Mixed-expiration structures and
nonstandard deliverables require a later lifecycle/data design, not silent fallback.

## Cash, costs, and P&L identities

For signed contracts q, premium p, and multiplier M:

```text
entry premium cash = -sum(q * entry fill price * M)
entry cash change = entry premium cash - entry commission - entry extra slippage
open marked value = sum(q * current conservative mark * M)
unrealized P&L = open marked value + entry premium cash - entry costs
closing premium cash = sum(q * closing fill price * M)
realized P&L = entry premium cash + closing/settlement cash - entry costs - exit costs
equity = cash + marked open positions
equity = initial capital + cumulative realized P&L + open unrealized P&L
net daily return = ending equity / previous ending equity - 1
```

The first day starts flat and has zero return. The regression tests compound the
complete net daily series back to every equity observation, with absolute tolerance
1e-9 and relative tolerance 1e-12. Event reconciliation checks use explicit signed
quantities, contract multipliers, and marks, independently reconstructed cash flows,
and cumulative P&L.

Bid/ask crossing already changes premium cash and mark-to-market P&L. It is **not**
charged again through `bid_ask_fraction`. `OptionsCostModel.execution_costs` separates
per-contract commission from the existing flat `multi_leg_penalty`, which represents
explicit extra dollar slippage per multi-leg execution. It introduces no new
slippage assumption. `total_cost`, `open_cost`, and `close_cost` report these explicit
cash charges; embedded bid/ask losses remain in premium/mark P&L.

`OptionsCostModel.structure_cost` remains an estimate relative to midpoint for the
existing parity research utilities. Its spread estimate is not used by the
historical execution path. The equity cost model is unchanged. Invalid execution
fee/penalty settings fail before any portfolio mutation.

`OptionsBacktestResult.event_ledger` captures open, close, expiration, and valuation
events. Each holding carries its full contract identity, signed quantity, multiplier,
mark price, and mark date. Intermediate snapshots use the latest valid marks for
unaffected positions; end-of-day marks must be current. No synthetic mark is inserted
to make a failed run look complete. `orders` records each executed leg's signed
transaction quantity, price, notional, and cash flow. Expiration records are labeled
cash settlement, not market fills. Closed trades include entry/exit cash and separate
entry/exit commission and slippage. Closed positions have zero open value and zero
unrealized P&L; their historical leg records remain available for audit.

## Confirmed defects corrected

| Defect | Correction and location |
|---|---|
| Missing held legs were skipped, dropping their signed marked value | `BacktestPosition.mark`: stage all marks; raise with contract/date before committing any position state |
| Another underlying or a near-but-different strike could be selected | `contract_selector.lookup_row`: underlying-aware, exact strike, ambiguous-match failure; spread builders filter the intended underlying |
| Candidate leg identity was omitted or overridden at execution | `Candidate` retains per-leg identity; engine rejects conflicting identities and unsupported multipliers; atomic fill rejects mixed underlying/expiry/date rows |
| NaN, infinity, crossed markets, or missing quote fields could fill | Shared quote validation in `fill_model`; execution rejection before portfolio mutation; selectors use the same fill validity gate |
| Terminal close relaxed the gate or fabricated a midpoint fill | `_force_close_remaining` uses the normal gate and raises on failure, preserving the complete affected structure |
| Missing terminal legs produced an apparently finished run with unresolved economics | Explicit failure; no partial close, fabricated closed trade, or completed result |
| Spread crossing was counted in fill price and charged again | `OptionsCostModel.execution_costs` charges only commission and existing explicit extra slippage |
| Expiry used the first underlying, strike fallback, or skipped expiry dates | Validated same-underlying exact-date intrinsic cash settlement; no fallback; stale expiry stops the run |
| Closed positions retained marked value and polluted portfolio views | Clear open value/unrealized P&L on close/expiry; exclude closed positions from views and defined-loss totals |
| Direct close accepted rejected fills or repeated a completed close | Validate closing fills before mutation and reject already-closed positions |
| Final daily Greeks could retain exposure after terminal liquidation | Replace final Greeks with the post-liquidation snapshot |
| Two-contract vertical fill-time payoff bounds used one-contract width | Scale width cash by the actual contract count |
| Non-finite/negative execution costs could contaminate cash | Validate execution cost parameters before booking |
| Executed quantities/prices/cost components were insufficiently recorded | Complete leg execution records, trade cash/cost components, and reconciled event snapshots |
| V5.4 `wide_bid_ask` scenario varied a duplicate fee rather than actual quotes | Remove that misleading scenario and update report wording; retain low/default/high fee and extra-slippage scenarios |

## Hand-checkable reconciliations

All examples start with **$10,000 cash**, use multiplier **100**, and one contract per
listed leg unless stated otherwise. Commission is **$1 per contract per execution**.
Extra slippage is **$0 for a single leg** and **$0.50 per multi-leg execution**.
All figures below are dollars except per-share option quotes and percentages.
Quotes are bid/ask. Tests use SPY contracts; normal-close expirations are 2026-02-06,
with entry on 2026-01-06 and close on 2026-01-07.

The short-put example is an isolated accounting fixture with the full $10,000 strike
obligation covered by initial cash. It does not add a short-put strategy, naked-short
permission, collateral reservation, or a margin engine.

| Example | Opening execution and premium cash | Entry commission + extra slippage | Cash after entry | Signed entry mark | Entry equity / unrealized P&L |
|---|---|---:|---:|---:|---:|
| Long call K100 | Buy 1 at ask 2.20: -220 | 1 + 0 | 9,779.00 | +200 at bid 2.00 | 9,979.00 / -21.00 |
| Cash-secured short put K100 | Sell 1 at bid 2.00: +200 | 1 + 0 | 10,199.00 | -220 at ask 2.20 | 9,979.00 / -21.00 |
| Debit call vertical K100/K105 | Buy K100 at 2.20, sell K105 at 1.00: -120 | 2 + 0.50 | 9,877.50 | +200 -110 = +90 | 9,967.50 / -32.50 |
| Credit put vertical K95/K100 | Buy K95 at 1.10, sell K100 at 2.00: +90 | 2 + 0.50 | 10,087.50 | +100 -220 = -120 | 9,967.50 / -32.50 |

| Example | Closing execution and premium cash | Pre-close marked value / unrealized P&L | Exit commission + extra slippage | Ending cash = equity | Correct realized P&L | Old realized P&L from failing regression |
|---|---|---:|---:|---:|---:|---:|
| Long call | Sell at bid 3.00: +300 | +300 / +79 | 1 + 0 | 10,078.00 | +78.00 | +58.00 |
| Short put | Buy back at ask 1.10: -110 | -110 / +89 | 1 + 0 | 10,088.00 | +88.00 | +73.00 |
| Debit vertical | Sell long at 4.00; buy short at 1.60: +240 | +240 / +117.50 | 2 + 0.50 | 10,115.00 | +115.00 | +85.00 |
| Credit vertical | Sell long at .40; buy short at .90: -50 | -50 / +37.50 | 2 + 0.50 | 10,035.00 | +35.00 | +10.00 |

For example, the debit vertical closes with:

```text
cash = 10,000 - 220 + 100 - 2 - 0.50 + 400 - 160 - 2 - 0.50 = 10,115
realized P&L = -120 + 240 - 2.50 - 2.50 = +115
remaining contracts = 0; open mark = 0; unrealized P&L = 0
```

| Boundary/lifecycle example | Correct numerical outcome | Before correction |
|---|---|---|
| Unchanged debit vertical, normal next-bar close | -120 entry, 2.50 entry cost, +90 close, 2.50 exit cost; ending 9,965, P&L -35 | Ending 9,935, P&L -65 from double-counted spreads |
| Same quotes, valid final dataset boundary | Exactly the same 9,965 ending cash and -35 P&L; both legs closed | Included duplicate spread costs |
| Debit vertical expires at spot 102 on 2026-01-07 | Long intrinsic +200, short intrinsic 0; no exit fee; 9,877.50 + 200 = 10,077.50; P&L +77.50 | Ending 10,062.50, P&L +62.50 |
| Long call expires at spot 103 | +300 settlement; 9,779 + 300 = 10,079; P&L +79 | Could use another underlying's spot; QQQ spot 900 produced +79,779 P&L |
| Long call expires OTM at spot 99 | Zero intrinsic; ending 9,779; P&L -221 | A valid zero payoff remains valid; missing spot is no longer fabricated |
| Short put expires at spot 98 | -200 settlement; ending 9,999; P&L -1 | Underlying/date validation was absent |
| Short put expires OTM at spot 103 | Zero settlement; ending 10,199; P&L +199 | Underlying/date validation was absent |
| Missing-leg entry | No fill, no holdings, no fee; cash/equity remain 10,000 | Existing passing control; preserved |
| Crossed short-leg entry (bid 1.20, ask 1.10) | Reject whole structure; cash/equity remain 10,000 | Accepted and changed cash to 9,887.50 |
| NaN quote entry | Reject whole structure; cash/equity remain 10,000 | Could turn cash into NaN |
| Held debit vertical loses the short-leg quote | Raise naming SPY call K105 and date; retain cash 9,877.50 and prior complete mark +90; last valid equity 9,967.50 | Dropped the -110 liability, changing the mark to +200 and apparent equity to 10,077.50 |
| Terminal long-call quote 1.00/1.50 | Spread 40% exceeds 25%; no close; cash 9,779, valid marked value +100, equity 9,879; explicit failure, no completed result | Relaxed gate allowed an exit |
| Terminal long-call quote .01/2.00 | No close; cash 9,779, conservative mark +1, equity 9,780; explicit failure | Replaced rejected execution with midpoint 1.005 |
| Terminal missing vertical leg | No partial close, no fee; retain both legs, cash 9,877.50, prior complete mark +90; abort | Could leave residual positions in a returned result with incomplete valuation |
| Invalid held quote (crossed or NaN) | Same atomic preservation and explicit error as missing mark | Accepted invalid marks or contaminated marked value |
| Two-contract debit vertical | Entry premium -240; expiry payoff range 0..1,000; premium-only max profit 760 and max loss -240 | Max profit incorrectly 260 from one-contract width |

Retained marks after an error are diagnostic **last valid state**, not claims of a
current executable liquidation value. Errors prevent publishing a completed curve.

### Net-return compounding

Printed directly from the corrected implementation using the tested three-day fixture:

| Date | Normal/valid-terminal cash | Normal/valid-terminal equity | Net return |
|---|---:|---:|---:|
| 2026-01-05 | 10,000.00 | 10,000.00 | 0 |
| 2026-01-06 | 9,877.50 | 9,967.50 | -0.00325 |
| 2026-01-07 | 9,965.00 | 9,965.00 | -0.00025081514923497306 |

```text
10,000 * (1 - .00325) * (1 - .00025081514923497306) = 9,965
```

For expiration, the first two observations are unchanged. Last equity/cash is
10,077.50 and final net return is 0.01103586656634059; compounding gives 10,077.50.
The final Greek exposure is zero after all three completion paths.

## Test-first evidence and verification

No pre-existing test assertion was changed. New tests are in
`tests/test_options_accounting_regressions.py`.

| Stage | Passed | Failed | Meaning |
|---|---:|---:|---|
| Initial tests against unchanged implementation | 1 | 37 | Economic failures above; missing-leg-entry control already worked |
| First corrections and directly affected existing tests | 95 | 0 | Original 38 new cases plus 57 existing cases |
| Added identity/event-accounting tests before their implementation | 47 | 7 | Missing records and accepted identity/multiplier substitutions reproduced |
| Corrected identity and event ledger plus existing tests | 111 | 0 | All 54 new cases plus 57 existing cases |
| Final edge cases before correction | 54 | 11 | Mixed rows, changed multiplier, quantity scaling, invalid costs, misleading cost scenario |
| Final directly affected verification | 122 | 0 | 65 new cases plus 57 existing cases; 1.18 seconds |
| All options/parity/cost modules | 187 | 0 | 65 new cases plus 122 existing cases; 2.67 seconds |
| Full project suite | 1,898 | 0 | 184.61 seconds; includes all 38 verified ETF accounting cases |

All listed runs had zero skips, pytest warnings, and collection errors. Expected
failing regression runs are deliberately separated from the final passing runs.
Final full-suite outcomes, separately: **1,898 passes; 0 failures; 0 skips;
0 pytest warnings; 0 collection errors.** All 65 new cases pass without weakening
their assertions. All 1,833 pre-existing cases still pass.

Commands (PowerShell, existing project interpreter; no installs):

```powershell
& '.venv\Scripts\python.exe' -B -m pytest tests/test_options_accounting_regressions.py -p no:cacheprovider -o addopts='' -ra --tb=short
$optionTests = @(rg --files tests | Where-Object { $_ -match 'options|put_call_parity|transaction_costs' })
& '.venv\Scripts\python.exe' -B -m pytest @optionTests -p no:cacheprovider -o addopts='' -ra --tb=short
& '.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider -o addopts='' -ra --tb=short
```

Runtime: Python 3.12.10, pytest 9.0.3, existing `.venv`. No package or environment
actions. A separate numerical-print command initially lacked pytest's `src` import
path; it was rerun successfully with `sys.path.insert(0, 'src')`, without installation
or configuration changes. This was not a pytest collection failure.

## Files changed for Phase 1B only

| File | Responsibility changed |
|---|---|
| `src/quantbot/options/contract_selector.py` | Full lookup identity, exact strike, shared executable quote gate |
| `src/quantbot/options/fill_model.py` | Valid quotes, atomic row/identity validation, separated execution costs |
| `src/quantbot/options/position.py` | Atomic marks, validated cash settlement, close-state accounting |
| `src/quantbot/options/spreads.py` | Underlying filtering and retained per-leg contract identity |
| `src/quantbot/options/backtest_engine.py` | Correct execution/terminal/expiry economics and auditable event records |
| `src/quantbot/costs/transaction_costs.py` | Options execution cost components only; ETF model unchanged |
| `scripts/run_options_v54.py` | Remove obsolete duplicate-fee stress scenario and correct dependent descriptions |
| `tests/test_options_accounting_regressions.py` | New 65-case regression/invariant suite |
| `docs/phase1b_options_accounting.md` | This convention, evidence, and reconciliation report |

Historical reports were not regenerated or overwritten. Reports produced by the old
engine contain the old economics and must not be treated as corrected results.

## Remaining limitations and acceptance scope

- Research cash settlement does not reproduce physically settled American options.
- Standard contracts only; no OCC adjusted-deliverable ledger, corporate-action
  transformations, mixed-expiration lifecycle, or intraday/0DTE entry support.
- No quote-size/queue model, partial execution, legging, market impact calibration,
  broker execution, collateral/margin engine, financing, or cash interest was added.
- Quotes are assumed to be the supplied daily observation. Bid/ask timestamp
  synchronization, real quote freshness within a date, official settlement provenance,
  and data coverage cannot be established by these accounting tests.
- Optional missing Greeks still follow existing behavior; this phase does not claim
  complete Greek-risk coverage. Fee/slippage-inclusive equity is correct; the existing
  vertical max-profit/max-loss metadata describes premium-only expiration payoff
  bounds, not a complete fee-inclusive margin/risk engine.
- The event ledger records latest valid marks with dates; it is an auditable daily
  research ledger, not an intraday consolidated market valuation service.
- Runs with missing required data or unexecutable terminal positions deliberately
  fail. Their partial state is diagnostic, not an accepted completed backtest.

The acceptance criterion is satisfied for the tested small examples under this
explicit historical convention: executed/rejected legs, quantities, premium cash,
commissions, explicit slippage, marks, realized/unrealized P&L, settlement, net returns,
and ending equity reconcile within numerical tolerance. This does not certify
real-world American assignment, liquidity, or live-trading readiness.
