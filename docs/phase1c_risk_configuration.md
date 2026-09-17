# Phase 1C — Risk, configuration and Git correctness

Date: 2026-09-17. This phase changes existing risk/configuration behavior only.
No new strategy, provider, live execution, monitoring, infrastructure or Phase 2
implementation was added. Existing unrelated working-tree/index changes were retained.

## Final risk constraints

The reproduced failure was the final net-exposure transformation in
`RiskManager.apply_exposure_caps`. After individual and sector caps, it removed a
uniform tilt from every symbol. A valid capped vector `[.15, .15, -.15]`, with a
zero-net cap, became `[.10, .10, -.20]`: the short exceeded its 15% position/sector cap.
With `[.15, 0]` and a .05 net cap, it created a new 5% short in the inactive symbol.

`reduce_net_exposure` now reduces only the overweight side. It cannot increase a
position's absolute size, reverse its sign or create a holding in an inactive name.
The first example becomes `[.075, .075, -.15]`; gross is .30, net is zero, and every
position/sector remains within .15. The second becomes `[.05, 0]`.

The complete pipeline now:

1. Validates finite, nonnegative limits, unique instruments and finite targets
   (the existing NaN-target-to-zero convention remains; this is not market-price handling).
2. Applies the existing portfolio/strategy drawdown and volatility-spike controls.
3. Applies daily-loss reduction; subsequent volatility targeting cannot lever that
   reduced exposure back up. A .20 weight reduced by .5 remains at most .10, rather
   than becoming .40 after a fourfold volatility scale-up.
4. Applies volatility targeting, then global and strategy-specific per-name caps.
5. Applies sector/asset-class caps. Unmapped names share one conservative group,
   with an explicit RiskState note; they no longer bypass the cap.
6. Reduces gross and net exposure without increasing individual positions.
7. Restores explicitly requested market neutrality by shrinking the overweight side.
8. Calls `validate_final` to recheck single-name, strategy-name, gross, absolute net,
   sector-group, long-only and market-neutral constraints together. Violations raise.

The ETF engine passes its strategy's existing `max_weight` and `long_only` attributes
to this risk call. These are the **only two Phase 1C additions to that engine**;
cash, quantities, marks, fills, costs and daily-return accounting are untouched.
S01/S02 caps therefore cannot be enlarged by later central volatility scaling.
The existing S03 pair-selection count limits are unchanged; subsequent risk reductions
do not create instruments or add pairs. `target_gross` is a sizing target, not a new
guaranteed minimum allocation or a newly introduced portfolio risk feature.

All implemented exposure constraints are upper bounds, so a flat portfolio is
feasible. Long-only plus zero-net/market-neutral requirements return zero when
necessary. Negative/nonfinite limits are invalid and raise, rather than being
"repaired" silently. A late broken transform is caught by the independent validator.

These guarantees concern **approved target weights at the end of risk processing**.
Actual cash-and-quantity holdings subsequently drift with prices, costs, rejected fills,
and the existing rebalance-band policy. This phase does not impose continuous forced
rebalancing or change Phase 1A accounting to make marked weights appear constant.
Sector constraints use the supplied classification; complete/correct economic sector
classification remains a data requirement. The unknown group is explicit, not a claim
that the true classification is known.

`portfolio.construction.apply_constraints` now also enforces its documented net cap
with the same reducing-only operation; previously it ignored that parameter.

## Risk signs and units

| Quantity | Convention |
|---|---|
| Position weight | Signed marked notional / equity; .15 means 15%; shorts negative |
| Gross exposure | Sum of absolute weights, nonnegative; 1.5 means 150% |
| Net exposure | Sum of signed weights; `max_net_exposure` bounds its absolute value |
| Position and group caps | Nonnegative weight fractions, not percentages written as 15 |
| Cash / realized or unrealized P&L | Currency units; profits positive, losses negative |
| Daily returns / drawdown | Decimal fractions; losses/drawdowns negative |
| Option structure `max_loss()` and candidate/position `max_loss` | Finite nonpositive worst-case dollar P&L; -250 means a $250 defined loss |
| PortfolioGreeks `max_loss`, aggregate defined-loss budgets | Finite nonnegative dollar magnitudes; 250 means a $250 loss budget |
| OptionsRiskLimits debit/credit/loss limits | Nonnegative dollars; width is strike dollars; portfolio fraction uses initial capital |
| VaR / ES | Nonnegative return loss fractions; gain-only tails floor at zero |

`defined_loss_magnitude` is the explicit conversion from signed option loss P&L to a
positive loss amount. The Greek aggregator previously summed -250 and -250 to -500,
which passed a positive $400 risk budget. It now aggregates to +500 and rejects the
$400 budget; a $500 budget accepts it. Unknown, NaN and unbounded maximum loss cannot
become zero risk. Negative magnitude inputs do not pass `options_loss_within_limit`.

The existing Phase 1B signed position/candidate convention is retained, including
premium-only payoff bounds. Option candidate validation rejects invalid signs/units
instead of applying `abs()` to disguise them. Options limits validate finite values,
integer position counts and fractional portfolio budgets. `allow_naked=True` is
rejected, consistent with the existing hard no-naked-short rule. No financing,
assignment or unified margin/risk engine was added.

## One authoritative strategy JSON

Authoritative path: **`configs/strategy_configs.json`**.

The root `strategy_configs.json` is now only a `$ref` compatibility redirect. Both
paths resolve through `load_strategy_config` to the same validated contents,
independently of the current working directory. Reintroducing a root payload causes
an explicit error, even when a caller requests the canonical path. Unknown redirect
destinations are not followed. Direct external `json.load` readers of the old root
payload must migrate to `load_strategy_config`; they cannot receive stale defaults.

Before replacement, every field in both JSON files was compared. There were exactly
14 differences and **no fields found only in the root file**. The canonical file was
already used by current entry points; the V2.1/V2.3 tests explicitly preserve its S01
defaults and role metadata. No tuning or new default strategy behavior was chosen.

| Field (inside strategies) | Old root | Canonical value retained | Resolution reason |
|---|---|---|---|
| S01.cost_filter_multiplier | 3.0 | 4.0 | Current runtime source and V2.1/V2.3 assertions |
| S01.min_holding_days | absent | 20 | Current conservative default, explicitly tested |
| S01.rebalance_band | absent | .02 | Current runner control, explicitly tested |
| S01.role | absent | satellite_experimental | V2.3 classification, explicitly tested |
| S01.s01_confirm_days | absent | 3 | Preserve existing opt-in conviction configuration |
| S01.s01_conviction_lookbacks | absent | [60, 120] | Preserve existing opt-in configuration |
| S01.s01_execution_mode | absent | binary | Preserve default behavior, explicitly tested |
| S02.role | absent | core | Existing V2.3 classification |
| S03.cointegration_pvalue_threshold | .05 | .10 | Retain current canonical runtime selection setting |
| S03.max_half_life | absent | 45.0 | Preserve current selection setting |
| S03.min_half_life | absent | 2.0 | Preserve current selection setting |
| S03.min_rolling_correlation | .70 | .65 | Retain current canonical runtime selection setting |
| S03.role | absent | research_only_no_alpha | Preserve current reporting classification |
| S03.target_gross | absent | .60 | Preserve current exposure-sizing setting |

S01/S02/S03 above abbreviate their complete JSON strategy IDs. All other original
fields agreed. One additional inconsistent declaration was corrected:
`S01_trend_following.long_short` was **true in both files**, but the implementation
already enforced long-only. It is now false; requesting true through the loader is
an error. This changes a misleading declaration, not the strategy's trading behavior.

### Caller inventory and deliberate migration

| Caller | Source before and after |
|---|---|
| `scripts/run_s01.py`, `run_s02.py`, `run_s03.py` | Shared `load_strategy_config` / `strategy_params`; already canonical |
| `scripts/run_core.py`, `run_compare.py` | Shared loader, plus explicit in-memory research variants |
| `scripts/research_edge.py` | Shared loader; intentional parameter variants remain explicit |
| `scripts/report_s02_v3.py` | Shared loader |
| `scripts/report_s02.py` | `factor_attribution._base_config`, which uses the shared loader |
| `src/quantbot/reporting/factor_attribution.py` | Shared loader |
| `load_risk_config()` | Canonical risk block plus global drawdown controls |
| Explicit `load_strategy_config(root_path)` | Formerly stale root payload; now canonical redirect |
| S01/S02/S03 constructors | Consume passed parameter dictionaries; code defaults/explicit partial overrides remain API fallbacks, not a second JSON payload |
| Daily options engine/strategy classes | Existing `OptionsRiskLimits` and their own explicit constructor parameters; dormant S05-S10 specifications are not claimed as live controls |

No current Python caller directly opened the root payload outside the shared loader.
Thus migration is centralized, with entry-point identity tests, rather than changing
already-correct script imports. Explicit external strategy JSON paths remain supported
as deliberate validated overrides; they are not automatic fallback sources.

### Validation and inactive settings

- Duplicate JSON keys at any nesting depth, NaN/Infinity JSON numbers (including
  overflowed numeric literals), unknown sections/fields, unknown factor names and
  invalid hard-risk limits are rejected.
- Conflicting global/risk drawdown settings are rejected rather than silently
  choosing precedence. Identical values do not create differing behavior.
- Unsupported S01/S02 long-short mode, S02 non-price mode, unknown S01 execution
  modes, enabling disabled S04-S10 placeholders, and non-monthly S03 pair-selection
  requests fail explicitly. Negative per-strategy caps fail at loading.
- `configuration_diagnostics()` identifies retained inactive/declarative fields.
  Enabled/role fields are metadata, not a new scheduler. Short-side S02 settings are
  inactive. S01 confirmation fields apply only in conviction mode.
- Global options budget declarations are retained but are not wired to the daily
  options engine's dollar `OptionsRiskLimits`; no unified risk engine is implied.
- Global commission/slippage declarations currently require explicit use of the
  existing `equity_cost_model_from_config` helper; existing entry points use cost-model
  defaults. Those declarations are now explicitly classified, not newly wired through
  the accounting layer in this phase. Global `cost_filter_multiplier` does not override
  S01's own value. `vol_spike_lookback` does not calculate a volatility ratio inside
  RiskManager; a caller must supply that diagnostic.
- Validation is intentionally scoped; it is not a complete type/range system for
  every dormant future-strategy specification or every direct constructor override.

## Git-ignore evidence

The only ignore-rule change is **`data/` -> `/data/`**. The old rule matched any
directory named data, including source packages. The anchored rule protects the root
market-data directory without excluding `src/quantbot/data`.

Before:

```text
git check-ignore -v --no-index src/quantbot/data/__init__.py
.gitignore:22:data/  src/quantbot/data/__init__.py

git ls-files src/quantbot/data
[no files]

git status --short --untracked-files=all -- src/quantbot/data
[source hidden by ignore rule]
```

After:

```text
git check-ignore -v --no-index src/quantbot/data/__init__.py
[no match; exit 1]

.gitignore:22:/data/          data/sample.parquet
.gitignore:22:/data/          data/cache/test.csv
.gitignore:2:__pycache__/     src/quantbot/data/__pycache__/loaders.pyc
.gitignore:29:outputs/        outputs/run.json
.gitignore:35:reports/options/ reports/options/run.csv
.gitignore:13:.env           .env
```

`git status` now shows these 12 unchanged Python sources as `??` (trackable/untracked):

```text
src/quantbot/data/__init__.py
src/quantbot/data/corporate_actions.py
src/quantbot/data/futures_loader.py
src/quantbot/data/loaders.py
src/quantbot/data/options_cache.py
src/quantbot/data/options_chain_loader.py
src/quantbot/data/options_loader.py
src/quantbot/data/options_providers/__init__.py
src/quantbot/data/options_providers/synthetic.py
src/quantbot/data/options_providers/thetadata.py
src/quantbot/data/options_validators.py
src/quantbot/data/validators.py
```

Together these source files are 76,139 bytes. Their contents were not changed.
Bytecode, virtual environments, root market data, globally excluded Parquet/database
formats, logs, outputs and existing generated-report exclusions remain ignored.
No dataset/private file was added to Git. No files were staged, committed or pushed;
the pre-existing staged work was retained. A future reviewed commit must include these
12 source files along with the corrections—unignoring alone does not put them in an
existing commit or make an old clone reproducible.

Repository-ignore tests isolate `.gitignore` from user-global excludes. One inspection
attempt using `core.excludesFile=NUL` with `git status` failed on this Git build; normal
`git status` supplied the evidence above. Normal Git emitted sandbox permission notices
for the optional user-global ignore file; these are not pytest warnings or changes to
Git configuration. No persistent Git configuration was altered.

## Test-first evidence

New file: `tests/test_phase1c_risk_config.py`, **75 cases**. Six randomized cases cover
180 combinations of exposure, sector, strategy-name, neutrality and long-only caps.
Other cases verify reproductions, invalid/impossible configurations, final-validator
failure, loss signs, option limits, config redirects/callers, and Git exclusions.

| Run | Passed | Failed | Notes |
|---|---:|---:|---|
| Initial regressions before implementation | 11 | 33 | Confirmed economic/config/ignore failures |
| First fixes plus all Phase 1A/1B cases | 147 | 0 | Original 44 new cases + 103 accounting cases |
| Expanded tests before remaining limit validation | 63 | 7 | Options limits, unknown risk key, negative magnitude |
| Directly affected risk/config/strategy/accounting run | 274 | 0 | 128.67 seconds |
| Final configuration edge cases before correction | 70 | 5 | Nonfinite JSON, negative caps, ineffective frequency, diagnostic gaps |
| Final Phase 1C + Phase 1A + Phase 1B run | 178 | 0 | 75 + 38 + 65 cases; 5.95 seconds |
| Full project suite | 1,973 | 0 | 199.81 seconds; all 1,898 pre-existing cases plus 75 new cases |

All listed test runs had zero skips, pytest warnings and collection errors. Expected
red test runs are separated from verification. No existing assertions or Phase 1A/1B
regression files were modified. Final full-suite outcomes, separately:
**1,973 passes, 0 failures, 0 skips, 0 pytest warnings, 0 collection errors.**

SHA-256 checks against the start of Phase 1C confirmed both accounting regression
files, ETF broker/position/order implementations and options engine/fill/position
implementations are byte-for-byte unchanged. Removing only the two newly added
risk-call arguments from the ETF engine reproduces its original SHA-256 hash.
`git diff --check` passes. The index still contains only the same three pre-existing
staged additions; no Phase 1C staging, commit or push occurred.

Commands used the existing interpreter, disabled bytecode/cache writes, and made no
package/environment changes:

```powershell
& '.venv\Scripts\python.exe' -B -m pytest tests/test_phase1c_risk_config.py tests/test_etf_accounting_regressions.py tests/test_options_accounting_regressions.py -p no:cacheprovider -o addopts='' -ra --tb=short
& '.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider -o addopts='' -ra --tb=short
```

## Files changed in Phase 1C

1. `.gitignore`: anchor root market-data exclusion.
2. `strategy_configs.json`: replace stale payload with explicit redirect.
3. `configs/strategy_configs.json`: correct S01's long-only declaration.
4. `src/quantbot/config.py`: authoritative loading, validation and diagnostics.
5. `src/quantbot/risk/risk_manager.py`: reducing-only transforms, final validation and input checks.
6. `src/quantbot/risk/greeks.py`: signed-loss conversion and positive magnitude validation.
7. `src/quantbot/risk/var_es.py`: nonnegative loss-fraction convention.
8. `src/quantbot/options/risk.py`: validate existing candidate units and hard limits.
9. `src/quantbot/portfolio/construction.py`: enforce documented net constraint.
10. `src/quantbot/backtest/engine.py`: pass two existing strategy hard-limit attributes to risk processing.
11. `tests/test_phase1c_risk_config.py`: new regressions/invariants.
12. `docs/phase1c_risk_configuration.md`: this evidence/migration report.
13. `docs/phase1c_environment_reproducibility.md`: environment evidence and deferred Phase 2 requirements.

## Acceptance scope

A: Approved targets satisfy all implemented final risk constraints; infeasible
nonzero requests can flatten, invalid settings fail explicitly. Continuous marked
holdings/margin enforcement is outside this pipeline and was not added.

B: One authoritative strategy JSON path, explicit root redirect, fully documented
field resolution and shared-loader entry-point tests. Declared inactive settings are
identified rather than represented as enforced controls.

C: The ignore/trackability defect is fixed and tested. The previously hidden code is
visible for review; recording it in Git history still requires the user's subsequent
commit. No claim is made that unstaged/uncommitted changes already exist in a clone.

D: Both accounting regression files are unchanged and fully passing. Cash/quantity,
option premium, execution, marking, cost and settlement behavior was not redesigned.

Environment lock/recreation work remains Phase 2 documentation only. See the companion
report for the known unresolved package-metadata issues. Phase 2 was not started.
