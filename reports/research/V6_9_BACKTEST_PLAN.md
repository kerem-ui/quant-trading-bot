# V6.9 — Backtest Plan (planning-only; no code, no edge claim)

_Hand-written. Companion to the auto-generated
`reports/research/V6_9_LEDGER_AUDIT.md`._

**Status: PLANNING ONLY.** No backtest has been run. No strategy has been
implemented. `LIVE_TRADING_ENABLED` remains `False`. This document
specifies what V6.9.1 would do *if* the substrate audit clears the go/no-go
bar and *if* the design below survives review.

---

## 1. Goal

Decide — and document the conditions under which we could ever decide —
whether the V6.8 **company-derived sector read** carries forward-looking
information beyond what the canonical V6.1 **sector signal** already
encodes.

If the answer is "yes", that is interesting research output — not a green
light to trade. If the answer is "no", we keep the V6.8 view as an audit /
explainability surface and stop investing engineering effort in elaborating
it.

## 2. Null hypothesis

> **H₀.** Conditional on the canonical V6.1 sector signal at time *t*, the
> V6.8 company-derived read at the same *t* carries **zero** incremental
> information about a sector basket's forward return at horizons *h* ∈
> {5, 20, 60} trading days.

H₁ is two-sided. We do **not** specify a direction in advance (the V6.8
read could be slower, more conservative, *or* more forward-looking than the
canonical signal — we don't know).

The null is deliberately *conditional* on the canonical signal because:

* The two views are derived from overlapping inputs (the same per-sector
  catalyst CSVs). A naïve unconditional comparison would conflate the
  canonical signal's edge with any incremental V6.8 edge.
* Conditional information is the only operationally interesting question:
  if the V6.8 read merely tracks the canonical signal with a lag, the
  canonical signal is strictly better and V6.8 is decorative.

## 3. Why construction-bias is the headline risk

The V6.5.2 / V6.7 / V6.8 derivation rules were tuned **by hand** on the
same fundamentals (FY2024–FY2026 SEC company-facts) that any backtest will
likely be run on. Specifically:

* The "BULL + BROKEN → MIXED" rule (V6.5.2) was chosen *after* observing
  the NVDA/AMD/AVGO/MU inventory pattern in May 2026.
* The "many MIXED → CAUTION" rule (V6.8) was chosen *after* observing
  that today's SEMICONDUCTOR read would otherwise look forced bullish.
* The COMPANY_CATALYSTS mapping (V6.7) is hand-curated; ticker additions
  and theme labels reflect our 2026 view of the AI / power buildout.

Any in-sample test will appear to "work" by construction. The plan below
treats this as the dominant threat and elevates **out-of-sample
discipline** to a hard gate (Section 7).

## 4. Substrate audit (summary)

The auto-generated audit at `reports/research/V6_9_LEDGER_AUDIT.md`
counts what we have today. Headline (2026-05-29):

| Surface | Value | Backtest threshold |
|---|---|---|
| Distinct ledger run_ids | **1** | ≥ 30 |
| Distinct calendar dates | **1** | ≥ 90 |
| Per-sector ledger run count | **1** for every sector | ≥ 30 |
| Distinct aggregation run_ids | **1** | ≥ 30 |
| Historical canonical-sector-signal log | **absent** | required |

The audit concludes **NO-GO** with five blockers. The dominant blockers
are time-related: V6.7 only started accumulating data this month. None of
the rule-based aggregation logic can be tested until many runs have
landed.

**This is expected**, not a defect. Planning today fixes the design so
that when substrate eventually accumulates we don't reinvent it.

## 5. Substrate gap that V6.9 surfaced: canonical signal history

The V6.1 sector score is recomputed *live* from the latest catalyst CSVs
on every dashboard render. There is **no per-(run_id, sector) snapshot of
the canonical sector signal on disk**. The V6.6 change log records
*field-level* catalyst changes but never the resulting canonical signal
label.

This is a real gap for V6.9.1: the null hypothesis is *conditional on the
canonical signal at time t*, and "time t" only means anything if we know
what the canonical signal *was* at that time.

**Recommendation: a tiny V6.6.2 milestone** — add a
`data/research/sector_tracker/sector_signal_log.csv` that
`scripts/refresh_sector_trackers.py` appends to alongside the change log.
One row per (run_id, sector) with the canonical signal label and
normalized score at that refresh. Schema would mirror the V6.7 ledger's
append-only / idempotent style.

V6.6.2 should land *before* V6.9.1. The audit's canonical-signal-history
blocker is the only one V6.9.1 cannot just "wait out" by accumulating
data.

## 6. Proposed evaluation design

### 6.1 Target variable

Sector forward returns:

```
r_{sector, t, h} = (P_{sector, t+h} / P_{sector, t}) - 1
```

where `P_{sector, t}` is the close of a pre-declared sector basket on the
trading day on/after the run's calendar `date`. Horizons:

* `h = 5` trading days (≈ 1 calendar week)
* `h = 20` trading days (≈ 1 month)
* `h = 60` trading days (≈ 1 quarter)

Multiple horizons let us see whether any incremental signal in the V6.8
read concentrates at a particular timescale.

### 6.2 Sector basket / proxy mapping

Pre-declared, *frozen at plan-write time* (V6.9), so a future redesign
forces a new milestone (not a silent change):

| Sector | Primary proxy | Notes |
|---|---|---|
| `SEMICONDUCTOR` | **SOXX** (iShares Semiconductor ETF) | Holds NVDA / AMD / AVGO / MU / AMAT / LRCX / KLAC / TSM / ASML — direct overlap with the V6.7 universe. |
| `AI` | **XLK** (Technology Select Sector SPDR) | Best ETF proxy with MSFT / GOOGL / AMZN / META / ORCL exposure. NOT pure-play AI; this is a known noise floor. |
| `ENERGY` | Split: **XLE** for traditional, **GRID** or a custom basket for AI-power-infra | The V6.4 driver already separates `AI_POWER_INFRA` (GEV / ETN / VRT / PWR / CEG) from traditional energy (XOM / CVX / COP). The backtest should respect this split. |

**Hard rule:** all proxy mappings are pre-declared in the V6.9.1 design
review BEFORE any return data is loaded. No proxy substitution after
seeing performance.

### 6.3 Sample construction

For each `(run_id, sector)` observation in the V6.8 aggregation:

1. Pull the run's `date` and look up the **next trading-day close** as
   `P_t`. If a run lands intraday, we use the next-day open or close
   conservatively (one fixed convention, declared in advance).
2. Look up `P_{t+h}` for each horizon.
3. Build a row: `(run_id, sector, canonical_signal, canonical_score,
   company_derived_read, h, r_{sector,t,h})`.
4. Join the V6.6.2 canonical-signal-log row on `(run_id, sector)` to
   anchor the conditional.

### 6.4 Statistical test

The test of choice is **conditional comparison** of forward returns:

1. Group rows by *(canonical_signal, company_derived_read, h)*.
2. For each canonical_signal bucket with sufficient n (see §8), compute
   the mean forward return *per company_derived_read* sub-bucket.
3. Test whether the BULL minus BROKEN spread within a single canonical
   signal bucket is statistically distinguishable from zero.

The primary test is a **block-bootstrap** to respect the temporal
correlation that overlapping forward windows induce. Block size = the
horizon `h` (so a 60-day horizon's blocks are non-overlapping at the
return-window level). Report bootstrap p-values and 90 % CIs; do **not**
report a point estimate without the CI.

Secondary (descriptive only): conditional accuracy / hit-rate of the
"⚠ company roll-up more cautious" marker as a forward-loss predictor.

### 6.5 What NOT to do

* No parameter tuning on OOS data.
* No threshold optimization (no "let's try MIN_RUNS_PER_SECTOR=20 and see").
* No re-derivation of the V6.8 rules after seeing performance.
* No ETF substitution if performance is weak on the primary proxy.
* No expansion of the candidate horizon set after seeing 5d / 20d / 60d
  results.
* No claim of "edge" without the bootstrap CI excluding zero, and no
  trading decision based on the result regardless.

## 7. Out-of-sample discipline

The V6.7 ledger's first row dates from **2026-05-29**. Define:

* **IS (in-sample) window**: the first 50 % of accumulated ledger
  history, frozen at the date V6.9.1's design review is signed off.
* **OOS (out-of-sample) window**: the remaining 50 %, untouched until the
  IS analysis is fully written up and committed to git.

The IS write-up must be a committed git artifact (e.g.
`reports/research/V6_9_1_IS_REPORT.md`) **before** any OOS data is
read. The git timestamp of that commit is the holdout boundary.

If the OOS result diverges meaningfully from IS, the V6.8 read is
*dropped from consideration as a forward-looking signal*. We do not
re-tune; we accept the negative result.

## 8. Power check (back-of-the-envelope)

Suppose we accumulate one run per trading day. After 6 months (~125
trading days):

* Per-sector observations: ~125 each = **375 total** at the daily
  granularity.
* But the 60-day forward horizon means only **2 non-overlapping windows
  per sector** if blocked rigorously. That is far too few for a
  conditional test at h=60.
* The 20d horizon gives ~6 non-overlapping blocks per sector. Still
  underpowered.
* The 5d horizon gives ~25 non-overlapping blocks per sector. This is the
  only horizon where we'd plausibly have power.

**Implication:** even with 6 months of substrate, only the 5d horizon is
statistically interpretable. Longer horizons would need 18+ months of
ledger accumulation to power a conditional test at moderate effect sizes.

**Detectable effect size** (5d, n≈25 blocks/sector, α=0.05, power=0.8): a
Cohen's d of approximately **0.8** — a large effect. Anything smaller is
indistinguishable from noise at this sample size.

The plan therefore commits, in advance:

* Only the 5d horizon is **primary**.
* 20d and 60d horizons are reported as **descriptive context**, not
  inference.
* If the 5d test does not reject H₀, the V6.8 read is documented as
  "no detected forward-looking edge at the substrate-feasible horizon"
  and shelved.

## 9. Go / No-Go criteria for V6.9.1

V6.9.1 may start ONLY when **all** of the following are simultaneously
true:

1. **Substrate count gates** from the auto-generated audit are cleared:
   * ≥ 30 distinct ledger run_ids per sector
   * ≥ 30 distinct aggregation run_ids
   * ≥ 90 distinct calendar dates of ledger history
2. **V6.6.2 canonical-sector-signal log exists** and has been emitting
   for at least the full window the V6.9.1 backtest will use.
3. **Pre-declared proxy mapping** (§6.2) is committed in git and
   unmodified since this plan was signed off.
4. **OOS boundary date** is declared in advance — the holdout begins at
   the date of V6.9.1's design-review sign-off commit.
5. **No parameter optimization** is part of the V6.9.1 scope. The V6.8
   rules are frozen; the backtest tests *those* rules, not a tunable
   variant of them.
6. **Pre-committed null hypothesis** — exactly the one stated in §2.

If **any** of these conditions fail, V6.9.1 must be deferred. Re-tuning
the gate criteria themselves after seeing data is a project-level
violation of the "no parameter optimization" rule recorded in
`feedback_research_methodology`.

## 10. Decision after the backtest (for V6.9.1's authors)

When V6.9.1 has produced its IS + OOS results:

* **Reject H₀ on both IS and OOS, with consistent sign:** document the
  finding as a candidate research lead. **Not** a green light to trade.
  Live trading remains gated on the v1 mandate (research-only). The next
  step would be V6.10 design — a much more elaborate robustness
  programme, not a strategy implementation.
* **Reject on IS, fail on OOS:** classic overfit. Document the null
  result; drop the V6.8 read as a forward signal; keep it as a
  dashboard / audit surface.
* **Fail on IS:** stop. No OOS leak; OOS data remains unread for any
  future attempt.

## 11. Risks (and accepted positions)

1. **Hindsight bias in rules.** Accepted; mitigated by the OOS holdout
   and the no-tuning rule. Cannot be fully eliminated.
2. **Proxy ETF leakage of canonical-signal information.** SOXX overlaps
   heavily with the V6.7 universe; the canonical signal already conditions
   on the same fundamentals. The conditional design (§6.4) is exactly what
   addresses this; the null may still be hard to reject.
3. **Survivorship bias in COMPANY_CATALYSTS.** OpenAI / Anthropic are
   private placeholders (TRACKED). Today's hyperscalers are public
   winners. If a peer was de-listed mid-window, the ledger silently drops
   them. Accept and document; no backfill.
4. **Calendar-driven correlation.** A few major macro events
   (FOMC, CPI prints, NVDA earnings) move all three sector proxies
   together. The bootstrap block size partly addresses this. We do not
   claim independence beyond what the test machinery can deliver.

## 12. Required artifacts for V6.9.1 sign-off

Before V6.9.1 begins coding:

* This plan unchanged or with explicitly-versioned edits documented in a
  changelog at the top of this file.
* The latest `V6_9_LEDGER_AUDIT.md` showing **all five blockers
  cleared**.
* The V6.6.2 `sector_signal_log.csv` accumulating data for at least the
  intended backtest window.
* A short design-review note explicitly citing this plan's §9 and
  confirming each gate.

## 13. References

* `reports/research/V6_9_LEDGER_AUDIT.md` — substrate counts and current
  go/no-go.
* `src/quantbot/research/sector_tracker/ledger_audit.py` — pure helpers,
  testable; thresholds defined as module constants.
* `src/quantbot/research/sector_tracker/company_ledger.py` — V6.7 ledger.
* `src/quantbot/research/sector_tracker/company_aggregation.py` — V6.8
  aggregation rules (the rules to be tested).
* `apps/sector_thesis_dashboard.py` — V6.8.1 collapsed roll-up; the
  operator-visible divergence marker.
* User memory: `feedback_research_methodology` —
  *"falsification-first, power-check-before-build, OOS-before-edge, no
  parameter optimisation"*. This plan is an instance of that policy.

---

**This plan defines the conditions under which V6.9.1 is permitted. Until
those conditions are met, the V6.8 company-derived read is an audit
surface only — not a signal, not a strategy, not a trade.**
