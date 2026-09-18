# Phase 4A: options analytics foundation and validation

## Scope and audit

Phase 4A adds no strategy, provider, execution model or environment dependency.
All historical files remain immutable. Detailed results live under ignored
`runs/phase4a/`; the repository contains analytical code, deterministic tests,
and this report definition. The Phase 1 options cash/quantity/cost calculations
are unchanged: only missing Greek diagnostic propagation changes in position.py.

| Existing component | Audit classification and disposition |
|---|---|
| options/pricing.py | European BSM formula implemented; normal cases were already correct. Zero-volatility payoff, validation and IV bracketing corrected and independently tested. |
| options/greeks.py | Analytical European Greeks implemented; regular formulas verified by finite differences. Degenerate/invalid inputs previously became zero risk; corrected. |
| options/structures.py | Payoff templates and signed quantity/multiplier Greek scaling; defaults IV=.20, r=.03 and T=30/365 are hypothetical research inputs, not historical facts. CalendarSpread is a European model-value difference, not a lifecycle/early-assignment engine. Existing defaults preserved; new dated analytics bypass these defaults. |
| options/position.py and risk/greeks.py | Provider-position and model-structure aggregation are separate. Missing/nonfinite components now propagate unknown, rather than implying zero exposure. Provider units remain unverified. Cash/marks/realized P&L/max-loss rules unchanged. |
| options/parity.py | Mathematical European parity is implemented/tested. european_only previously did not filter American contracts; now enforced, and unknown style is rejected. Explicit opt-out flags European approximation. Box/convexity scanners are legacy quote diagnostics, not certified executable arbitrage signals or an American pricing model. |
| data/options_loader.py | Synthetic BSM generator, now explicitly labelled hypothetical European metadata; a ticker such as SPY in this synthetic fixture does not make it real SPY contract-reference data. load_options_chain remains a NotImplemented placeholder; the real normalized corpus is read separately. |
| options/features.py | Observed/vendor nearest-delta and maturity-bucket proxies plus causal rolling statistics; no calibrated surface. Maturity fallback removed, actual delta/strike/distance/status added, invalid IV excluded with counts, mixed snapshots rejected. |
| options/chain.py | Legacy pivot no longer averages duplicated or mixed-underlying observations. nearest_delta returns its actual row; not an exact-target interpolation. |
| indicators/options_features.py | Older research proxies: nearest strike/DTE ATM and broad OTM-put average. Its skew_slope is NOT a 25-delta skew, and its IV percentile uses a different strict-less-than convention from options/features. It remains a legacy helper, not the Phase 4A validated chain API. No active strategy uses these IV/skew helpers. |
| indicators/volatility.py | Causal realized-vol/ATR helpers already covered by Phase 3. Realized vol is not option IV and is not substituted for missing vendor IV. Unchanged. |
| data/options_providers, storage, legacy migration | Provider IV/Greeks retained as observations; Phase 2 schema/missingness/provenance unchanged. The report verifies manifest and Parquet hashes before and after reading. |
| strategies/s05 through s08 | Inactive strategy stubs, not implemented volatility strategies; not activated or certified. |
| New analytics.py / surface.py / validation.py | Dated model inputs, explicit contract terms, observed-chain representation, labelled interpolation, and deterministic source-bound diagnostics. These are the canonical Phase 4A analytics entry points. |

## Defects reproduced before correction

The first regression run produced 17 expected failures and one passing negative-
price control. Subsequent regressions reproduced four failures for missing position
Greeks, the ignored European filter, mixed underlying summaries, and invalid-IV
medians; one for missing aggregate Greeks; and two for silent surface averaging.
All these failing assertions are preserved. New API tests initially failed at
collection because the modules did not yet exist. Additional metadata/identity/
signed-delta tests reproduced three validation gaps before they were corrected.
No existing economically correct assertions were weakened or replaced.

## Pricing and IV conventions

For S > 0, K > 0, T >= 0, sigma >= 0, all finite:

- European Black-Scholes-Merton, constant sigma and continuously compounded r/q.
- T = calendar days / 365, price per underlying share, annualized decimal sigma.
- Calls/puts use discounted spot A = S exp(-qT), discounted strike B = K exp(-rT).
- European bounds: call [max(A-B,0), A], put [max(B-A,0), B]. For T>0 the upper
  bound is asymptotic, not an invertible finite-volatility price.
- At expiration, price is ordinary intrinsic. At zero volatility and positive T,
  price is discounted deterministic forward payoff, not discounted spot intrinsic.
- An ITM European put can validly be below spot intrinsic when rates are positive;
  applying American spot-intrinsic bounds would incorrectly reject it.
- Invalid model inputs raise ValueError; impossible prices return a failed IVResult
  with explicit reason and NaN volatility. The compatibility implied_vol function
  returns NaN on failed inversion; it never returns a fabricated boundary estimate.
- Default solver bounds are [0, 5] (0% to 500% annualized volatility), configurable
  explicitly. Above-bracket prices are not called mathematically impossible: they
  are outside the configured solver domain.
- solve_iv uses bracketed bisection, at most 200 iterations, absolute repricing
  tolerance 1e-8 per share. Legacy scalar API keeps its 1e-6 tolerance/100 iterations.
- Prices within tolerance of the deterministic lower bound are unidentifiable at
  that precision; no claim of uniquely recovered zero IV. Expiration IV is unknown.
- Every successful historical inversion is repriced and its residual recorded.
- Near-expiry ITM/OTM flat price regions can identify price but not sigma accurately;
  the guarantee is price reconciliation, not arbitrary IV-identification precision.

Hand check: S=K=100, T=1, r=.05, q=0, sigma=0 call previously returned 0;
correct value is 100 - 100 exp(-.05) = 4.877057549929 per share. S=80/K=100,
T=1/r=.10/sigma=.20 put has valid price below 20; IV now recovers .20.
A market price 101 for S=K=100/r=q=0 formerly returned IV=5; it now fails.
A price generated at sigma=6 also formerly returned 5; it now reports an
out-of-bracket result unless the caller deliberately expands its bound.

## Greeks and scaling

| Field | Local per-share convention | Position conversion |
|---|---|---|
| delta | dV/dS, call nonnegative, put nonpositive | signed contracts * multiplier |
| gamma | d2V/dS2, per dollar squared | signed contracts * multiplier |
| theta | -dV/dT / 365, per calendar day | signed contracts * multiplier |
| vega | dV/dsigma / 100, per 1 volatility percentage point | signed contracts * multiplier |
| rho | dV/dr / 100, per 1 rate percentage point | signed contracts * multiplier |

Rates, yield and volatility inputs are fractions, e.g. .03/.01/.20. Theta is
usually negative for a long option but is not forced negative; carry/dividends
can change its sign. A positive quantity means long. Missing multiplier produces
unknown position scaling, never a fabricated multiplier of one or 100.

At sigma=0 away from the discounted-forward kink, Greeks are derivatives of the
deterministic payoff. At the kink they are explicitly undefined (NaN). At T=0,
delta away from strike is payoff slope, gamma/vega/rho are zero, theta undefined;
at strike all five are undefined. No fictitious zero-risk ATM expiration result.

Deterministic validation integrates the discounted lognormal payoff independently
of the d1/d2 pricing formula (14 cases: calls/puts, ITM/ATM/OTM, short/long T,
negative/zero/positive r, dividends, near-zero sigma, near-expiration). Tests also
check parity and bounds. Six regular cases compare all five Greeks with central
finite differences (30 comparisons); zero-volatility derivatives have separate
checks. All tolerances and actual residuals are recorded in the report.

## Inputs and contract terms

AnalyticsInputs is immutable and requires valuation date, supplied r/q (or explicit
missing values) and provenance labels. Optional timezone-aware timestamp must
agree with its date. The daily model remains date-only ACT/365 even when a timestamp
is supplied; no fabricated expiration time or intraday hedging is introduced.
Dated curves/dividend data can later provide each observation's explicit inputs.
Missing r or q disables local valuation/IV/Greeks, leaving provider fields intact.

ContractMetadata distinguishes underlying, expiration, strike, right, exercise,
settlement, multiplier and terms source. Supplied terms cannot silently disagree
with populated source metadata. Unknown terms remain unknown. SPY/QQQ standard
ETF options are American and physically delivered; European BSM is explicitly an
approximation for them. A legacy-null settlement field is not overwritten with
that standard convention. Contract adjustments/discrete dividends/early exercise,
physical delivery and assignment are unsupported; no full American engine added.
Phase 1 historical intrinsic cash-settlement bookkeeping remains unchanged and
must not be confused with actual ETF physical assignment.

References: [OIC exercise](https://www.optionseducation.org/referencelibrary/faq/options-exercise)
and [OIC physical settlement](https://prd-web.optionseducation.org/advancedconcepts/equity-vs-index-options).

## Provider versus local comparison

The report reads only the processed series from the existing Phase 2C corpus;
other overlapping snapshots are not mixed or counted as independent observations.
All 14 processed partitions (1,248,482 records) are verified. Sampling takes at most
three rows per symbol/month/right/DTE bucket/moneyness/IV-missingness stratum,
ordered by MD5(contract_id|date), then identity. Calls and puts, different strikes,
ITM/ATM/OTM, DTE 0/1-7/8-21/22-45/>45 and missing IV are retained. This stratified
sample is not frequency-weighted or statistically representative of all quotes.

Run with an explicitly supplied scenario r=.03, q=0, not claimed historical rates.
Quote midpoint is used solely for valuation inversion, never as an executable fill.
Provider IV and each Greek remain in provider_* fields; local_iv/local_greeks and
local_greeks_at_provider_iv have separate names. No vendor field or source file is
"corrected" to agree. Two comparisons distinguish reconstructed-IV effects from
Greeks computed at supplied vendor IV under the same local rate/yield assumption.

[ThetaData's current Greek documentation](https://docs.thetadata.us/Articles/Data-And-Requests/Option-Greeks.html)
describes European BSM, a default SOFR input, optional dividends, version-dependent
maturity treatment, and vega/rho conversion by division by 100. This does not
establish the legacy request/version. Raw comparisons and a separately labelled
unit-conversion hypothesis are both shown; stored values are never rescaled.

Strict historical validation count is zero: no contemporaneous rate/dividend
inputs or reliable quote/underlying event timestamps survive. Therefore differences
are not evidence that vendor Greeks are wrong. Numerical implementation errors are
isolated by independent fixtures; historical differences can reflect rates, yield,
price alignment, maturity convention, rounding, unit convention or model choice.
Cases outside European bounds are violations of the supplied scenario model, not
proof of impossible actual American market prices.

## Chain, skew and term structure

AnalyticalChain preserves raw provider observations and null OI/IV/Greeks. It rejects
mixed dates/underlyings, duplicate contract/date keys and reused identities, and
flags impossible/nonfinite IV, invalid delta signs, bad quotes, missing IV/Greeks,
insufficient strike/tenor coverage and strike-price monotonicity discrepancies.
Monotonicity checks use midpoint diagnostics only; asynchronous data is not proof
of arbitrage. Suspect observations remain available in the observed frame.

Phase 4A ATM means nearest observed strike to spot per right (ties choose lower
strike), then mean available call/put IV, with strike/spot distance and side count.
This differs explicitly from legacy features._atm_iv's nearest signed +/-0.50
proxy; legacy summaries now expose the selected delta/strike. Do not combine those
ATM conventions in one series without recording the change.

Wings use signed +.25 calls/-.25 puts, nearest valid provider delta, tolerance .10;
ties choose lower strike. Results retain selected delta, strike, distance and status.
Missing target wings stay unavailable, never an asserted exact 25-delta observation.
Put skew = put-wing minus ATM; call skew = call-wing minus ATM; put-call skew = put
minus call; risk reversal = call minus put (the opposite sign). All are annualized
volatility fractions, not option prices or trading recommendations.

Fixed tenor uses positive observed maturities with both ATM sides available:
interpolate total variance sigma^2*T linearly, then divide by target T and sqrt.
No extrapolation. Missing tenor coverage returns null/status. A decreasing-total-
variance bracket is flagged and not smoothed. This ATM proxy is not a calibrated
arbitrage-free IV surface or a fixed-forward-moneyness guarantee. The old near/mid/
far buckets remain explicit 7-14/21-30/30-45 DTE observations with actual selected
DTE, not fictitious constant maturities. The 30-day overlap is a documented legacy
bucket definition, not three independent tenor observations.

The corpus is predominantly short maturity; actual DTE range and counts above 45
are in the report. The two demonstrated first-date chains cannot support 45/60/90-
day analytics. Do not infer reliable long-term surfaces from occasional longer rows.

## Reproduce the validation

From the authorized clone and the unchanged locked environment:

```powershell
$Python = 'C:\QuantEnvs\quant_trading_bot_phase2\Scripts\python.exe'
$CorpusManifest = Read-Host 'Existing Phase 2C corpus manifest path'
& $Python scripts/validate_phase4a.py --data-root $env:QUANTBOT_DATA_ROOT `
  --corpus-manifest $CorpusManifest --output runs/phase4a/my-validation `
  --rate 0.03 --dividend-yield 0.0
& $Python -m pytest tests/test_phase4a_analytics.py tests/test_phase4a_analytics_regressions.py tests/test_phase4a_validation.py
& $Python -m pytest
uv lock --check --offline
uv pip check --python $Python
```

Output directories must be new and under ignored runs/. Each run contains full
machine/human reports, separated observation diagnostics, and sealed output manifest.
The report records corpus/partition/source checksums, Git base commit and dirty
state, exact analytical source/test file hashes (including new untracked code), lock
hash, scenario assumptions, sample hash, statistics and limitations. Final publication
commit can differ from the recorded base while the exact source hashes identify the
executed implementation. Repeating unchanged code/data/input assumptions produces
byte-identical artifacts in a separate new directory. No legacy report is overwritten.

No dependencies, strategy parameters, migrated data, ETF execution or Phase 3
research outputs are changed. See phase4a_validation_results.md for measured results,
verification counts and acceptance limits.
