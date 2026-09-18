# Phase 3A: daily equity/ETF market mechanics

Starting checkpoint: `029b5bba64a292377201411d5d4cbbe3b5ed9c62` (`phase2-verified`).
Work branch: `phase3-backtest-quality`. No strategy parameters, options accounting,
risk constraints, storage schema, migrated datasets or locked packages are changed.

## Confirmed findings and scope

The existing quantity ledger already books real fills, net returns and quantity-based
short borrowing correctly under the Phase 1 convention. It did not need replacement.
The missing mechanics were:

- Any supplied date could be a trading bar, including exchange holidays; missing
  exchange sessions could silently move execution to a later available bar.
- Cash could become negative with no declared debit financing assumption.
- Same-batch purchases could precede funding sales, creating a transient cash deficit.
- Corporate actions existed only as an adjusted-price convention, without an explicit
  raw-share event interface or sufficient historical action inputs.
- There was no cash-interest accounting or separate financing attribution.
- Reporting required new dividend/cash attribution; the existing headline
  `total_transaction_cost` also included borrowing and would include financing.

The changes extend the existing ledger, broker and result objects. Targets remain
weights, quantities remain fractional, and risk receives the completed net return.
There is no provider download, subscription, live execution, options strategy,
intraday infrastructure or new dependency.

## Calendar and date roles

`USMarketCalendar` is a versioned regular-session calendar for US-listed equity/ETF
research, explicitly limited to 2010--2026. Unsupported years fail instead of
assuming a complete future calendar. It uses the existing locked pandas dependency.

Session labels are naive local dates. Session open/close timestamps use
`America/New_York`, including DST. Normal hours are 09:30--16:00, with 13:00
closes on the day after Thanksgiving and eligible July 3/December 24 sessions.
Observed holidays include Good Friday and Juneteenth from 2022. New Year's Day
on Saturday does not close the preceding Friday. Exceptional full closures include
October 29--30, 2012; December 5, 2018; and January 9, 2025.

The engine rejects non-session bars, duplicate/unsorted instrument indexes,
ambiguous timezone/intraday labels, and missing global exchange sessions between
the first and last bar. It does not fill missing prices or discard suspicious rows.
An individual security may have gaps; Phase 1's required-mark checks still reject
missing marks when held and reject unpriced entries.

- Signals use information available by the signal session's close.
- Execution occurs at the calendar's next session open or close, as configured.
- Valuation occurs at that session's close, including early closes.
- `result.sessions` records the permitted signal/execution/valuation cutoffs;
  actual signal/order dates remain in the order records.
- Daily funding accrual does not prorate early-close sessions by trading hours.

Examples: March 28, 2024 signals execute April 1; May 24 signals execute May 28;
December 30, 2021 advances to December 31, then January 3, 2022. The 2022 calendar
has 251 sessions.

The synthetic generator now creates actual exchange sessions. The Phase 1 ETF
fixture was corrected from 65 weekday labels (including January 15, February 19
and Good Friday) to 65 exchange sessions. Its prices, event offsets, quantities,
costs and economic assertions were not changed. Legacy synthetic caches containing
holiday bars are now rejected; they are never silently rewritten. Seeded synthetic
paths generated for a calendar interval can change because the session count changed.

Calendar references:

- [NYSE trading hours and holiday calendar](https://www.nyse.com/trade/hours-calendars)
- [NYSE 2021 calendar](https://www.ice.com/publicdocs/2021_NYSE_Trading_Calendar.pdf)
- [NYSE 2022 calendar](https://www.nyse.com/publicdocs/ICE_NYSE_2022_Yearly_Trading_Calendar.pdf)
- [NYSE January 9, 2025 closure memorandum](https://beta.nyse.com/publicdocs/nyse/markets/american-options/rule-interpretations/2025/National_Day_of_Mourning_20250102.pdf)
- [SEC discussion of the October 2012 exchange closures](https://www.sec.gov/file/proposed-rule-release-no-34-69077)

## Exclusive accounting modes and available data

The historical equity loader/cache retains only date, open, high, low, close,
adjusted_close and volume. Inspection of the Phase 2 inventory confirms those
fields. The loader discards other vendor fields and can fall back to close when
adjusted_close is absent. Its adjustment ratio cannot establish exact event type,
split ratio, ex-date, dividend amount or payment date. Vendor OHLC can itself be
split-adjusted. These data cannot reliably reconstruct a raw-share action history.
No historical corporate actions were fabricated or backfilled.

`price_mode='adjusted'` remains the default. Execution uses adjusted close, or
open multiplied by adjusted_close/close. Valuation uses adjusted_close. Quantities
are research units. Passing an explicit action book in this mode raises an error;
there is no second dividend credit or split conversion.

`price_mode='raw'` requires all of:

1. Supplied `CorporateActionBook` with an explicit source and `complete=True`.
2. Complete symbol/date coverage, including an explicit empty event set when known
   to have no actions. Unknown events cannot silently mean no events.
3. Each frame's `attrs['price_basis']='raw_unadjusted'` attestation.
4. Valid, unique actions with positive finite split ratios/dividend amounts on
   exchange sessions. Unknown symbols, unsupported conventions and multiple actions
   for one symbol/date are rejected as ambiguous.

Raw execution/valuation use open/close directly. Strategy and risk features retain
their existing adjusted-close inputs; those returns are never booked as raw P&L.
The engine records the complete supplied action book in the result configuration.
The attestation is an input contract, not proof that the external source is correct.

Splits are effective before session trading: quantity is multiplied by the ratio,
and the prior mark is divided by it. This preserves position value and prevents a
split from creating market P&L. A split cannot create a position in a flat account.

Ordinary and representable special dividends use
`prior_close_ex_date_cash`: prior holdings receive/pay quantity times the supplied
amount on the ex-date, before trading. A same-day entrant receives nothing; an
existing holder selling that day retains entitlement. Shorts owe the dividend.
The price drop is market P&L and the dividend is a separate cash component.

This is an explicit ex-date cash-recognition research convention. It does not model
the interval from ex-date to payment date, receivables/payables, withholding taxes,
due bills, returns of capital, spinoffs, mergers, cash-in-lieu or fractional-share
rounding. Unsupported special-dividend conventions fail. Simultaneous split and
dividend inputs require a future explicit ordering/per-share-basis extension.
The raw mode is not a live broker corporate-action ledger.

## Cash, financing and short-borrow conventions

Cash interest defaults to zero. `cash_interest_rate` and `financing_rate` are
supplied annual decimal rates: 0.0365 is 3.65%, not 365%. They are finite,
nonnegative scalar assumptions, never inferred historical market rates.

Accrual uses the preceding closing balances over elapsed calendar days / 365
(ACT/365F), including weekends, holidays and leap days in the numerator. There is
no pre-first-bar accrual or post-terminal-bar accrual. Charges/credits are posted
before today's actions and orders, once per completed close-to-close interval.

```text
eligible_credit = max(previous_cash - previous_marked_short_collateral, 0)
cash_interest  = eligible_credit * supplied_credit_rate * elapsed_days / 365
cash_debit     = max(-previous_cash, 0)
financing_cost = cash_debit * supplied_debit_rate * elapsed_days / 365
```

Short collateral is the absolute marked value of previous closing short quantities.
It is a conservative eligibility convention, not a broker's settled-cash, proceeds
restriction or margin calculation. No short-proceeds rebate is modeled. Credit
interest is reinvested in cash at each posting; debits include previously posted costs.

`financing_rate=None` prohibits negative cash, including fee-created debt. An
unfunded batch fails before any of its fills is booked. Cash-releasing fills are
booked before cash-consuming fills using the same pre-cost allocation equity.
No target is silently resized to hide a financing requirement. An explicitly supplied
zero debit rate is a declared research assumption; it is never the default.
The usual four-ETF S01 test portfolio remains unfinanced. This does not prove all
possible targets are unlevered: the target/risk interfaces permit greater exposure,
and those runs must supply financing or fail.

`borrow_cost_bps_annual` remains an annual basis-point rate. Borrow charges apply
only to actual carried negative quantities. Two explicit day-count conventions:

- `sessions_252` (default): preserve Phase 1's post-split carried short quantities
  times today's closing mark times annual_bps / 10000 / 252. No entry-day charge;
  the cover day charges the carried interval. Holidays/weekends are not extra bars.
- `actual_365`: preceding closing short notional times annual_bps / 10000 times
  elapsed calendar days / 365. Weekend/holiday intervals accrue; a cover today pays
  the already-carried interval and stops all subsequent borrow accrual.

No locate availability, recalls, historical hard-to-borrow rates, margin/buying power,
settlement delays, liquidations or intraday financing are implied. New open/close
positions begin accruing on the next close-to-close interval. Different exposure
durations within a daily bar are not modeled. A dated rate series remains a future
explicit data input; no rate-data provider was added.

## Event order, reconciliation and reporting

1. Snapshot previous equity/positions; accrue prior-interval cash interest,
   financing and (if selected) ACT/365 borrow.
2. Apply validated pre-session raw-share splits/dividends.
3. Mark existing holdings at the execution price; convert pending targets into
   quantities using common execution-time equity; validate funding; book fills and
   their transaction costs once.
4. Mark resulting quantities at the session close; apply legacy session borrow
   only when that convention is selected.
5. Verify component P&L, derive net return, and give the risk engine that same net
   return before generating next-session orders.

```text
equity = cash + sum(signed_quantity * valid_mark)
equity_change = market_PnL + dividends + cash_interest
                - financing_cost - short_borrow_cost - transaction_cost
daily_net_return = ending_equity / previous_ending_equity - 1
```

All cost components are positive amounts in cost records and negative components
in `pnl_components`. `total_net_pnl` is their signed sum. `gross_pnl` retains only
per-symbol market P&L. The result adds dividends, cash interest, financing costs,
session cutoffs and event snapshots. `total_cost` includes trading + short borrow +
financing. `total_transaction_cost` now correctly means trading costs alone.

S02 contributions include each symbol's dividends and an explicit
`__CASH_FINANCING__` contribution when applicable; it is not attributed to an ETF.
The tearsheet exposes component dollar P&L and separately identifies financing.

## Hand-calculated examples

All examples start with $1,000. Unless stated otherwise, rates and fees are zero.
The executable examples are in `tests/test_phase3a_market_mechanics.py`; they also
check every event's cash-plus-holdings identity and daily return compounding.

| Example | Quantities at end | Cash | Component P&L | Ending equity |
|---|---|---:|---|---:|
| March 28 signal, April 1 entry at 100 after Good Friday/weekend | +5 | 500 | all zero | 1,000 |
| Five raw shares at 100; 2-for-1 split, mark 50 | +10 | 500 | market 0; split 0 | 1,000 |
| Five raw shares at 100; 1-for-2 reverse split, mark 200 | +2.5 | 500 | market 0; split 0 | 1,000 |
| Five raw shares, $2 ordinary/representable special dividend; mark 98 | +5 | 510 | market -10; dividend +10 | 1,000 |
| Five short raw shares, same dividend and price drop | -5 | 1,490 | market +10; dividend -10 | 1,000 |
| Adjusted mark remains 100 across raw 100 to 50 split | +5 research units | 500 | all zero; no explicit split | 1,000 |
| One idle-cash day at 3.65% | 0 | 1,000.10 | interest +0.10 | 1,000.10 |
| Buy 15 at 100; $500 debit held one day at 7.3% | +15 | -500.10 | financing -0.10 | 999.90 |
| Short 5 at 100 on March 27, cover April 2; 365 annual bps ACT/365 | 0 | 999.70 | borrow -0.30 | 999.70 |
| Flat split event | 0 | 1,000 | all zero; no phantom shares | 1,000 |

Financing: `500 * .073 / 365 = .10`. The short example carries six calendar days:
`500 * .0365 * 6 / 365 = .30`. April 3 and 4 have zero borrowing charges.
The preserved Phase 1 short example still pays $0.50 entry cost plus three $0.05
session borrow charges, ending at $999.35.

The complete idle-cash example from January 2 through April 2, 2024 ends at
$1,009.140587506376. Independently calculate it as
`1000 * product(1 + .0365 * elapsed_days / 365)` over successive exchange dates.
Its entire $9.140587506375 P&L is cash interest; there are no holdings or trades.

The combined example uses that same initial period, 3.65% cash interest, an April 1
50% long/25% short allocation at 100, 10 bps transaction cost and 365 annual bps
ACT/365 short borrow. The long closes April 2 at 110; the short stays at 100.

- Equity immediately before entry: $1,009.039683538022, independently obtained
  from the idle-cash product through April 1.
- Long quantity: 5.04519841769011; short quantity: -2.522599208845055.
- Entry cash: `E - .50E + .25E - .00075E = 756.022982890863`.
- Next interval eligible cash: entry cash less $252.259920884506 short collateral.
- Market P&L: +$50.451984176901; total cash interest: +$9.090059844222.
- Transaction costs: -$0.756779762654; borrowing: -$0.025225992088.
- Net P&L: +$58.760038266381; ending cash: $756.048133204975.
- Ending signed holdings: $302.711905061406; ending equity: $1,058.760038266382.

An unconfigured 150% long or 100% long plus a fee fails explicitly before the
batch is booked. Missing action coverage, missing raw-price attestation, ambiguous
event order and unsupported due-bill inputs fail explicitly, producing no certified
result and no invented economics.

## Validation and remaining limits

Tests were introduced before implementation. The initial 25 cases failed on absent
calendar/mechanics APIs; once the calendar existed, the old engine demonstrably
accepted a closed-session bar. Additional tests reproduced transient funding debt,
misclassified financing costs and missing action-input metadata before their fixes.
The numerical Phase 1 assertions remain intact; only invalid synthetic date labels
were corrected. No options/risk assertions or Phase 2 storage tests were weakened.

Verified results (September 18, 2026; locked CPython 3.12.10 environment):

- Phase 3A: all 44 cases pass within the targeted and full runs.
- Final targeted run: 338 passed in 107.45 seconds, including the Phase 1
  accounting/risk regressions, Phase 2B/2C storage/migration tests and directly
  affected engine, cost, data-validation and reporting tests.
- Full suite: 1,491 passed, 14 skipped in 156.65 seconds.
- Failures: 0; collection errors: 0; warnings: 0.
- The 14 existing optional SEC-cache skips comprise 5 AI, 4 energy and 5
  semiconductor tests. No skips or xfails were added.
- `uv lock --check` passes; `uv pip check` reports all 72 installed packages
  compatible. Neither dependency declarations nor lock contents changed.
- Read-only execution of the checkpoint engine reproduced a 150% long holding
  with cash -500, 15 units, equity 1000 and zero financing. The new default rejects
  that undeclared debt; the explicit 7.3% example ends at 999.90 after one day.

The acceptance criterion is satisfied for the hand-checkable portfolios under
the conventions above. The source changes do not supply missing historical action
or rate information and do not certify broker-level settlement or margin behavior.

Run with the locked project environment:

```powershell
python -B -m pytest -p no:cacheprovider -o addopts='' -q
uv lock --check
uv pip check --python <path-to-project-environment-python>
```

Limits: the reviewed calendar ends in 2026; stale-but-present quotes, security-specific
halts, delistings, survivorship bias, real rate histories and broker settlement/margin
remain outside this phase. Raw accounting requires separately sourced reliable inputs;
the migrated legacy corpus was not modified. Adjusted prices remain a research
convention. Results are economically reconciled under the stated daily conventions,
not a claim of live broker reconciliation or complete market realism.
