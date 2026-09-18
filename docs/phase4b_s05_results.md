# Phase 4B: bounded S05 results

Status: mechanically validated research/debug implementation. The corpus was
already observed during earlier research. No out-of-sample or alpha claim is made.
The user-approved specification is frozen; no parameter changed after results.

## Runs and provenance

- Freeze: `research/phase4b/s05-v1/specification.json`.
- First bounded run: `runs/phase4b/s05-v1-bounded/`, retained intact.
- Final verification run: `runs/phase4b/s05-v1-verified/`.
- Deterministic repeat: `runs/phase4b/s05-v1-repeat/`.
- Small sealed evidence: `research/phase4b/s05-v1/bounded_results.json` and
  `verification.json`; full market-derived signals/ledgers remain ignored.
- Inputs:14 processed Phase2C partitions /1,248,482 rows, plus two existing
  checksum-pinned adjusted-close CSVs for RV. No overlapping EOD/Greek versions
  were combined. No download, source rewrite or dependency change.
- Dataset, partition and underlying checksums were checked before/after. Runs
  record base Git commit plus exact implementation/test fingerprints. The initial
  run and final run have identical economic results; extra tests and a stricter
  reporting tolerance were added during review, without tuning strategy rules.

## Bounded research results

| Measure | SPY | QQQ |
|---|---:|---:|
| Options observation range |2022-01-03 to2023-01-31|2022-01-03 to2022-01-31|
| Options rows |1,183,094|65,388|
| Session slots |271|20|
| Valid IV30 observations |252|8|
| Missing/unavailable IV30 |19|12|
| Valid IV-percentile observations |127|0|
| Sessions without sufficient/available percentile |144|20|
| Valid RV observations |271|20|
| Dates satisfying frozen IV/RV signal |3|0|
| Eligible weekly candidate structures |1|0|
| Executed entries / completed trades |1 /1|0 /0|
| Rejected submitted orders |0|0|
| Starting equity |100,000.00|100,000.00|
| Ending equity |99,983.80|100,000.00|
| Gross trading P&L |−9.00|0.00|
| Commissions |5.20|0.00|
| Additional explicit slippage |2.00|0.00|
| Total explicit costs |7.20|0.00|
| Net P&L |−16.20|0.00|
| Net return |−0.0162%|0.0000%|
| Maximum drawdown |−0.0256%|0.0000%|
| Gross executed premium turnover / initial capital |2.095%|0.000%|
| Maximum defined expiry loss |137.00|0.00|
| Maximum fee-budgeted risk |144.20|0.00|
| Maximum cash reserve |207.20|0.00|
| Maximum gross marked option value / equity |1.26231%|0.00000%|
| Average gross marked option value / equity |0.026935%|0.000000%|
| Minimum net marked option value / equity |−0.085022%|0.000000%|
| Holding duration, calendar days |9 (one trade)|Unavailable|

Missing-data counts describe features, not order rejections: unavailable analytics
prevent order submission. Two of the three SPY signal dates were not eligible
weekly entry dates. QQQ is **DATA_INSUFFICIENT_IV_HISTORY**:20 sessions and8 valid
IV30 observations cannot meet126 valid observations. Its zero return is idle
cash, not evidence that the strategy has been evaluated successfully on QQQ.
RV can warm up from the existing earlier underlying CSVs; option IV history cannot
be invented from them. No warm-up rule was weakened.

Capacity-limited order count is0 because quote-size capacity is not modeled; this
is not a finding of unlimited liquidity. Spread crossing is embedded in actual
premiums, not an extra estimated charge. The funded one-lot convention does not
certify executable quote size. No CAGR/Sharpe/alpha conclusion is drawn from one
trade. Research profitability remains undetermined.

## Actual trade and reconciliation

Decision2022-09-26: IV30=.29355, RV=.2304515189163712, IV−RV=.06309848108362878
(6.309848 volatility points); percentile=.9695121951219512. Selected short put
provider delta−.1997 and short call+.2007. Expiration2022-10-26 (30 DTE at
selection;29 DTE at actual entry). Mechanical equal wing width=$2.

| Executed2022-09-27 leg | Quantity | Price/share | Premium cash flow |
|---|---:|---:|---:|
| SPY336 put |+1|3.85|−385.00|
| SPY338 put |−1|4.14|+414.00|
| SPY389 call |−1|2.49|+249.00|
| SPY391 call |+1|2.15|−215.00|
| Gross credit |||+63.00|

Entry cash=100000+63−3.60=100059.40. Defined expiry loss=200−63=137;
fee-budgeted risk=137+7.20=144.20; reserve=200+7.20=207.20.

Exit decision2022-10-05: DTE21; executable debit$82. DTE triggers the exit;
$82 is neither the$31.50 profit level nor the$126 stop level. Actual next-
observation close2022-10-06 costs$72 gross, plus$3.60 explicit costs.
Final cash/equity=100059.40−72−3.60=99983.80.
Gross P&L=63−72=−9; net=−9−3.60−3.60=−16.20.
The execution date is20 DTE; no21-DTE fill is fabricated.

Every recorded event reconciles signed holdings/cash/equity. Net returns compound
to the equity curve, and closed-trade premiums reconcile to ending equity under
rtol1e-12/atol1e-8. Daily provider Greeks are saved separately in their supplied,
uncertified units; missing components remain unknown.

## Chronological diagnostics

These are continuous-ledger quarter slices of observed data, with no resets or
window-specific fitting. One trade spans Q3/Q4, so quarterly P&L includes marks,
not only completed-trade P&L.

| SPY period | Net P&L | Explicit costs | Entries | Completed trades |
|---|---:|---:|---:|---:|
|2022Q1|0.00|0.00|0|0|
|2022Q2|0.00|0.00|0|0|
|2022Q3|−4.60|3.60|1|0|
|2022Q4|−11.60|3.60|0|1|
|2023Q1 (January only)|0.00|0.00|0|0|

QQQ January2022 has no trades. Sample sizes cannot support regime robustness,
statistical significance, profitability or model-selection conclusions.

## Test-first evidence and limitations

New S05 and research APIs initially failed collection before implementation.
The actual-fill risk regression then reproduced an unauthorized fill: decision
risk$407.20 fit the$410 budget, while next-observation risk$417.20 did not. The
new admission hook rejects it before cash/holdings change. Initial integration
exposed nine existing duck-typed strategy compatibility failures; the optional
hook fallback restored them without changing their assertions. A deterministic
delta-tie test reproduced floating-order instability; rounding representation
noise before the lower-strike tie rule corrected it. A ten-cent reconciliation
regression exposed NumPy's permissive default relative tolerance in the new
reporter; explicit strict tolerances corrected it. No prior economic assertion
was weakened. Frozen parameters and all historical sources remained unchanged.

Known limitations are the approved ones: American early assignment/physical
settlement absent, intrinsic cash research expiry, missing reliable timestamps/
OI/rate-dividend expectations, uncertified provider analytics, unknown quote sizes,
one-lot daily execution approximation and already-observed short history. Event/
panic filters and long-volatility branch are explicitly deferred. No parameter
was changed to increase sample size or improve the negative result.

See `phase4b_s05.md` for complete frozen rules, deterministic numerical examples,
setup instructions and strategy-specific Phase4C data needs. No Phase4C work
has begun. Final verification counts and acceptance are recorded below.
## Final verification and acceptance

| Test coverage | Passed | Failed | Skipped |
|---|---:|---:|---:|
| New Phase4B |52|0|0|
| Phase4A analytics |72|0|0|
| Existing options/features/parity |179|0|0|
| Phase1 accounting/risk regressions |178|0|0|
| Phase2 storage/migration |62|0|0|
| Phase3 A/B/C |111|0|0|
| Full project |1682|0|14|

Phase groups are extracted from the final full-suite JUnit record and overlap;
they are not additive. Full runtime438.90 seconds,0 collection errors,0 warnings.
The14 skips are existing unrelated SEC-cache-dependent tests (AI5/energy4/semi5).
An earlier full pass had1675 passing tests before seven additional exit/guard
regressions. The final52 Phase4B tests also passed separately in5.23 seconds.
CPython3.12.10, uv0.11.8: offline lock check passed;72 installed packages compatible.
No dependency declaration, lock or installed package version changed.

Independent final and repeat runs have23 byte-identical files covering both
symbols' signals/decisions/trades/ledgers/metrics and the frozen spec. Report and
manifest differ where their run IDs differ. All final source fingerprints match
the tested code. Corpus/source hashes and the approved spec remain unchanged.

The Phase4B implementation/reconciliation acceptance criterion is satisfied
under its explicit daily research convention. Empirical strategy validity is
NOT established: SPY has one observed trade; QQQ has insufficient IV history.
No Phase4C implementation or data purchase was started.

## Files changed

- `.gitattributes`: LF preservation for sealed Phase4B metadata.
- `README.md`: current S05 status and documentation pointers.
- `docs/phase4b_s05.md`: approval, frozen conventions, examples and reproduction.
- `docs/phase4b_s05_results.md`: bounded results and verification.
- `research/phase4b/s05-v1/specification.json`: pre-performance approved freeze.
- `research/phase4b/s05-v1/bounded_results.json`: small sealed result/provenance summary.
- `research/phase4b/s05-v1/verification.json`: exact tests, source hashes and limits.
- `scripts/run_phase4b.py`: offline runner without parameter override flags.
- `src/quantbot/options/s05_spec.py`: immutable approved parameters.
- `src/quantbot/options/s05_features.py`: causal RV, IV30 and percentile inputs.
- `src/quantbot/strategies/s05_implied_vs_realized_vol.py`: implemented options strategy.
- `src/quantbot/options/strategy_base.py`: default-preserving execution admission hook.
- `src/quantbot/options/backtest_engine.py`: optional hook before booking a fill.
- `src/quantbot/research/phase4b.py`: provenance, sealed outputs and reconciliation.
- `tests/test_phase4b_s05.py`:44 deterministic strategy/economic tests.
- `tests/test_phase4b_research.py`:8 freeze/reporting/reproducibility guards.

Full market data, source CSVs, generated signals and research ledgers are excluded
from Git. The original OneDrive project was not modified.
