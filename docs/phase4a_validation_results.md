# Phase 4A measured validation results

The Phase 4A acceptance criterion is satisfied for the documented European BSM
model and labelled American approximations, with explicit unsupported historical
inputs. This is not certification of vendor analytics, American early exercise,
a live risk engine or strategy profitability. See phase4a_options_analytics.md for
the full audit, input conventions and remaining legacy-proxy limitations.

## Reproducible run identity

- Base checkpoint: 51e24238d05e9614e1388b4696674f1d7051b275.
- Run: phase4a-82a7f7a36e10c5bd.
- Exact implementation and test SHA-256 values are recorded in the run manifest;
  its recorded Git state is the pre-publication base plus the tested working diff.
- Corpus: d448dcd36b54056c9085ebbb57ed28314fa7b5694eaf38c74855cc9726b018e4.
- 14 processed Parquet partitions; 1,248,482 rows. All referenced corpus/dataset/
  Parquet checksums verified before and after reading. Other corpus versions unmixed.
- SPY: 1,183,094 rows, 2022-01-03 to 2023-01-31, 0-46 DTE; only 712 rows exceed 45 DTE.
- QQQ: 65,388 rows, January 2022, 0-30 DTE.
- Final reports: runs/phase4a/validated/{report.md,report.json,manifest.json,observations.json}.
- Repeat run: runs/phase4a/validated-repeat; all four files byte-identical.
- report.json SHA-256: 7ff0242ece81638ed159d5abbdcda1cc64ad575e4b8482405e9f5c2dbabf2a4a.
- observations.json SHA-256: f74adce4458bb6c88b1453693bdfe2bc4f990b974dabecb15cda9aa568138dd9.
- Full observation diagnostics (2,667,472 bytes) stay ignored, not in Git.

## Mathematical evidence

Fourteen call/put cases agree with independently integrated discounted lognormal
payoffs: largest absolute difference 1.4210854715202004e-14 dollars per share.
The same cases pass IV inversion/repricing, European bounds and parity tests.
Six ordinary cases supply 30 analytical-vs-finite-difference Greek comparisons.
Maximum absolute Greek errors:

| Delta | Gamma | Theta/day | Vega/1 vol point | Rho/1 rate point |
|---:|---:|---:|---:|---:|
| 9.804407286e-11 | 2.052266671e-8 | 1.432963644e-11 | 7.850781136e-11 | 1.096256419e-10 |

For S=K=100, T=.5, r=.03, q=.01, sigma=.20, a long call has delta
0.5534572420, gamma 0.02778949475, theta/day -0.01775920443,
vega/point 0.2778949475 and rho/point 0.2462779849 per share.
Two short contracts with multiplier 100 multiply each by -200.
A zero-volatility S=K=100, T=1, r=.05 call is 4.877057549929 rather than the
legacy 0. Invalid 101-dollar premium no longer returns a false IV of 5.
Expiration/zero-volatility kinks and lower-bound unidentifiable IV remain unknown.

## Historical comparison under explicit assumptions

Scenario: continuously compounded r=.03, q=0, date-only ACT/365, quote-midpoint
valuation. No rates/dividend expectations are claimed to be historical observations.
The sample has 1,498 rows: SPY 1,390, QQQ 108; calls 757, puts 741; ATM 466,
ITM 678, OTM 354. DTE buckets: 0:426; 1-7:368; 8-21:336; 22-45:329; >45:39.
Stratification deliberately includes missing-IV observations; it is not a
frequency-weighted estimate of corpus error rates.

| Inversion outcome | Count |
|---|---:|
| Successfully repriced within 1e-8/share | 834 |
| Expiration date; no defensible intraday maturity | 426 |
| Outside supplied European-model price bounds | 236 |
| Outside configured 0-5 volatility bracket | 2 |

Largest successful repricing residual: 9.9897010664e-9 per share.
454 sample rows lack provider IV. 780 have both invertible quotes and provider IV.
All 1,498 lack event/underlying timestamps and trustworthy OI. **Zero observations
support strict contemporaneous vendor validation** because rates/dividends/vendor
version and synchronized timestamps were not retained.

| Provider/local IV difference | Value |
|---|---:|
| Mean absolute | .02951031055 (2.9510 volatility points) |
| Median absolute | .006315170119 (0.6315 volatility points) |
| P95 absolute | .1371389162 (13.7139 volatility points) |
| Maximum absolute | 1.243613482 |
| Mean relative to provider IV | 9.3216% |
| Median relative | 2.1785% |
| P95 relative | 59.2065% |

792 comparisons use local Greeks evaluated at vendor IV to isolate rate/yield/
maturity effects from reconstructed-IV differences. Raw values remain untouched.
The table applies the separately labelled current-documentation hypothesis of
vendor vega/rho divided by 100; other Greek fields are compared as supplied.

| Greek | Pairs | Mean absolute difference | P95 absolute difference | Mean relative difference |
|---|---:|---:|---:|---:|
| Delta | 792 | .003692442056 | .01412170532 | 2.1378% |
| Gamma | 792 | .000105303791 | .000346403435 | 3.8436% |
| Theta/day | 792 | .009323552440 | .02746279174 | 21.0030% |
| Vega/point, conversion hypothesis | 792 | .001927174976 | .008404195119 | 2.2186% |
| Rho/point, conversion hypothesis | 792 | .001213571379 | .006457095954 | 3.1159% |

Before the explicit unit hypothesis, mean raw vega/rho differences are respectively
18.76119568 and 9.450346284. The unit conversion explains most of this discrepancy;
it does not prove the legacy vendor model/version. Full raw and converted summaries,
including 834 local-Greek comparisons at reconstructed IV and denominator counts,
are in the generated report. Relative differences exclude zero provider denominators.
No observation has been labelled a vendor mathematical error or modified to agree.

## Skew and tenor examples, 2022-01-03

| Underlying, 30 DTE | ATM IV | Call wing IV / actual delta | Put wing IV / actual delta | Put-minus-call skew |
|---|---:|---:|---:|---:|
| SPY | .12220 | .1028 / +.2398 | .1594 / -.2543 | .0566 |
| QQQ | .17235 | .1511 / +.2499 | .2097 / -.2441 | .0586 |

Call-minus-put risk reversals are -.0566 and -.0586, respectively. These are observed
provider-IV features, not locally overwritten data or exact 25-delta quotes.
Wing distances: SPY call .0102, put .0043; QQQ call .0001, put .0059.

| Underlying | 7 DTE observed | 14 DTE total-variance interpolation | 21 DTE observed | 30 DTE observed | 45/60/90 DTE |
|---|---:|---:|---:|---:|---|
| SPY | .09605 | .1060316462 | .11040 | .12220 | unavailable |
| QQQ | .14105 | .1521818402 | .15645 | .17235 | unavailable |

Both 14-day interpolations use observed 11/15-day brackets. No extrapolation.
Full first-date chains contain 3,404 SPY and 3,260 QQQ rows with respectively 473
and 425 missing IV values. Midpoint strike-monotonicity diagnostics flag 6 and 80
discrepancies. Rows remain present; asynchronous quotes do not establish arbitrage.

## Preserved behavior and remaining limitations

Phase 1 cash/quantity/fill/commission accounting, risk caps and defined-loss signs;
Phase 2 schemas/manifests/Parquet; Phase 3 market mechanics, strategy parameters and
research outputs; and the Python dependency declarations/lock are unchanged.
The OneDrive checkout was not used or modified. No market dataset or detailed
research ledger is included in this publication.

Remaining limitations: European BSM only, continuous dividend yield, date-only
maturity, no historical rates/dividend expectations, unknown vendor version,
unverified original Greek units, unavailable OI, bounded short-tenor coverage,
possible nonsynchronous quotes, no calibrated surface, no early exercise/physical
assignment, and explicitly documented non-certified legacy feature proxies.
None is disguised as zero exposure, a validated vendor output or a supported
60/90-day surface. No strategy profitability inference or Phase 4B implementation.

## Files changed

Existing source files:

- src/quantbot/options/pricing.py: deterministic limit, finite-input/European-bound validation and bracketed IV outcome.
- src/quantbot/options/greeks.py: degenerate derivatives and invalid-right guard.
- src/quantbot/options/features.py: maturity/delta selection and bad-IV/mixed-snapshot guards.
- src/quantbot/options/chain.py: no silent duplicate/mixed-identity pivot averaging.
- src/quantbot/options/parity.py: enforce the existing European-only request.
- src/quantbot/options/position.py: missing provider-Greek diagnostics remain unknown; cash/marks unchanged.
- src/quantbot/risk/greeks.py: unknown model-structure Greeks remain unknown; max-loss convention unchanged.
- src/quantbot/data/options_loader.py: hypothetical European metadata on synthetic BSM fixtures.

Added files:

- src/quantbot/options/analytics.py: dated input and contract metadata plus separated local/provider values.
- src/quantbot/options/surface.py: observed chain, quality flags and explicit skew/tenor outputs.
- src/quantbot/options/validation.py: deterministic numerical/historical report with sealed provenance.
- scripts/validate_phase4a.py: bounded report command.
- tests/test_phase4a_analytics_regressions.py: 25 regression/control tests, including 24 initially failing legacy cases.
- tests/test_phase4a_analytics.py: 43 mathematical, metadata, missingness and selection cases.
- tests/test_phase4a_validation.py: 4 comparison, sampling and provenance tests.
- docs/phase4a_options_analytics.md: complete audit and conventions.
- docs/phase4a_validation_results.md: measured results and verification record.

## Final verification

CPython 3.12.10, unchanged external Phase 2 environment.

| Group (overlapping where relevant) | Passed | Failed | Skipped | Collection errors |
|---|---:|---:|---:|---:|
| Phase 4A | 72 | 0 | 0 | 0 |
| Existing options/pricing/features | 179 | 0 | 0 | 0 |
| Phase 1 accounting/risk | 178 | 0 | 0 | 0 |
| Phase 2 storage/provenance | 62 | 0 | 0 | 0 |
| Phase 3 | 111 | 0 | 0 | 0 |
| Complete final project suite | 1,630 | 0 | 14 | 0 |

Final full run: 430.96 seconds; no warnings. The 14 skips are unchanged optional SEC-cache integration checks (5 AI, 4 energy, 5 semiconductor).
An earlier full run, before the last additional regression cases, also passed: 1,619 passed / 14 skipped / no failures or warnings in 425.39 seconds.
The standalone completed Phase 4A set passed: 72 tests in 0.80 seconds.
uv lock --check --offline passed; uv pip check verified all 72 installed distributions compatible. No dependency/package/version/environment changes.
Git diff checks passed; all prior test files remain unchanged. Generated observations/reports, market data and .venv remain ignored.
Acceptance: satisfied within the explicit documented model conventions and missing-input limitations. No claim of certified historical vendor analytics or American exercise accuracy.
