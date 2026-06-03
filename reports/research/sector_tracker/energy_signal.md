# ENERGY Sector Thesis Tracker — Signal

*Read-only DECISION-SUPPORT output. NOT a trading signal, NOT a broker order, NOT investment advice. `LIVE_TRADING_ENABLED = False`.*


- Sector: **ENERGY**
- **Signal: HOLD**
- Normalized score: **+0.179** (raw +5.0 / total weight 28)
- Catalysts: 19 (BULL 4, NEUTRAL 14, NEAR_THRESHOLD 1, BROKEN 0)
- Emergency exit triggered: **False** (triggered: none)

## Top bull drivers
- Quanta Services revenue YoY (grid construction)
- Vertiv revenue YoY (data center power + cooling, most AI-direct)
- Macro regime — 2s10s curve (T10Y2Y)
- Macro regime — equity volatility (VIX)

## Top risks (BROKEN / NEAR_THRESHOLD)
- Macro regime — long-end rates (DGS10)

## Catalysts (raw)
| catalyst_id | tier | status | catalyst_name | threshold | current | action_if_broken |
|---|---|---|---|---|---|---|
| ENER-GEV-REV-T1 | 1 | NEUTRAL | GE Vernova revenue YoY (turbines + grid for AI build-out) | +20% YoY (BULL); -10..+20 NEUTRAL; -25..-10 NEAR; <-25 BROKEN | +9.0% (FY2024->FY2025) | review thesis (no order) |
| ENER-ETN-REV-T1 | 1 | NEUTRAL | Eaton revenue YoY (electrical equipment for data centers) | +20% YoY (BULL); -10..+20 NEUTRAL; -25..-10 NEAR; <-25 BROKEN | +10.3% (FY2024->FY2025) | review thesis (no order) |
| ENER-VRT-REV-T1 | 1 | BULL | Vertiv revenue YoY (data center power + cooling, most AI-direct) | +20% YoY (BULL); -10..+20 NEUTRAL; -25..-10 NEAR; <-25 BROKEN | +27.7% (FY2024->FY2025) | review thesis (no order) |
| ENER-PWR-REV-T1 | 1 | BULL | Quanta Services revenue YoY (grid construction) | +20% YoY (BULL); -10..+20 NEUTRAL; -25..-10 NEAR; <-25 BROKEN | +20.3% (FY2024->FY2025) | review thesis (no order) |
| ENER-CEG-REV-T1 | 1 | NEUTRAL | Constellation Energy revenue YoY (nuclear baseload for AI) | +20% YoY (BULL); -10..+20 NEUTRAL; -25..-10 NEAR; <-25 BROKEN | +19.5% (FY2024->FY2025) | review thesis (no order) |
| ENER-NEE-REV-T2 | 2 | NEUTRAL | NextEra Energy revenue YoY (utility + renewables) | +20% YoY (BULL); -10..+20 NEUTRAL; -25..-10 NEAR; <-25 BROKEN | n/a | review thesis (no order) |
| ENER-SO-REV-T2 | 2 | NEUTRAL | Southern Co revenue YoY (utility — AI load growth) | +20% YoY (BULL); -10..+20 NEUTRAL; -25..-10 NEAR; <-25 BROKEN | +10.6% (FY2024->FY2025) | review thesis (no order) |
| ENER-XOM-REV-T1 | 1 | NEUTRAL | ExxonMobil revenue YoY (integrated oil & gas) | +20% YoY (BULL); -10..+20 NEUTRAL; -25..-10 NEAR; <-25 BROKEN | -5.0% (FY2024->FY2025) | review thesis (no order) |
| ENER-CVX-REV-T1 | 1 | NEUTRAL | Chevron revenue YoY (integrated oil & gas) | +20% YoY (BULL); -10..+20 NEUTRAL; -25..-10 NEAR; <-25 BROKEN | -4.6% (FY2024->FY2025) | review thesis (no order) |
| ENER-COP-REV-T2 | 2 | NEUTRAL | ConocoPhillips revenue YoY (US shale + upstream) | +20% YoY (BULL); -10..+20 NEUTRAL; -25..-10 NEAR; <-25 BROKEN | +4.9% (FY2024->FY2025) | review thesis (no order) |
| ENER-OILGAS-OCF-T2 | 2 | NEUTRAL | Oil & gas majors aggregate operating cash flow YoY (XOM+CVX+COP) | +20% YoY (BULL); -10..+20 NEUTRAL; -25..-10 NEAR; <-25 BROKEN | -0.9% (latest FYE 2025-12-31) | review cash-return / capex assumptions (no order) |
| ENER-MACRO-RATES-T2 | 2 | NEAR_THRESHOLD | Macro regime — long-end rates (DGS10) | <=4.00 BULL; <=4.50 NEUTRAL; <=5.00 NEAR; >5.00 BROKEN | 4.57% (2026-05-20) | monitor rates |
| ENER-MACRO-VOL-T2 | 2 | BULL | Macro regime — equity volatility (VIX) | <=18 BULL; <=22 NEUTRAL; <=30 NEAR; >30 BROKEN | 17.44 (2026-05-20) | monitor volatility regime |
| ENER-MACRO-CURVE-T2 | 2 | BULL | Macro regime — 2s10s curve (T10Y2Y) | >=+0.30 BULL; >=0 NEUTRAL; >=-0.30 NEAR; <-0.30 BROKEN | +0.53pp (2026-05-20) | monitor curve |
| ENER-DATACENTER-POWER-DEMAND-T1 | 1 | NEUTRAL | Data-center power demand growth (AI-driven) | >15% YoY load growth = BULL; 5..15 NEUTRAL; 0..5 NEAR; <0 BROKEN | n/a | review AI-power exposure (no order) |
| ENER-NUCLEAR-SMR-T2 | 2 | NEUTRAL | Nuclear / SMR progress and orders | commercial SMR orders + NRC progress = BULL; delays / cancellations = BROKEN | n/a | monitor nuclear-baseload exposure (no order) |
| ENER-REGULATORY-RATECASE-T2 | 2 | NEUTRAL | Utility regulatory / rate-case risk | constructive rate cases = NEUTRAL; rejected / punitive = BROKEN | n/a | review regulated-utility exposure |
| ENER-COMMODITY-OIL-T1 | 1 | NEUTRAL | WTI / Brent crude oil price regime | >$75 BULL; $60..75 NEUTRAL; $50..60 NEAR; <$50 BROKEN | n/a | review traditional-energy exposure (no order) |
| ENER-LNG-CONTRACTS-T2 | 2 | NEUTRAL | LNG export contracts + EU/Asia demand | rising long-term contracts + tight market = BULL; cancellations / oversupply = BROKEN | n/a | review LNG / midstream exposure (no order) |

## Emergency exits
| exit_id | status | scenario | trigger | action |
|---|---|---|---|---|
| ENER-EXIT-DATACENTER-CAPEX-CUT | MONITORING | Big-Tech / hyperscaler capex pullback materially reduces data-center power demand | Cross-tracker: AI-EXIT-HYPERSCALER-CAPEX-CUT triggers, OR AI-HYPERSCALER-CAPEX-T1 falls below NEUTRAL band | research-only: re-evaluate sector sleeve; consider defined-risk hedges via the existing options layer (separate approval required); NO order execution |
| ENER-EXIT-GRID-ORDERS-SLOW | MONITORING | Grid / electrification equipment order growth decelerates sharply | ETN / VRT / PWR aggregate revenue YoY revised lower across two consecutive prints, OR backlog growth halts | research-only: re-evaluate sector sleeve; consider defined-risk hedges via the existing options layer (separate approval required); NO order execution |
| ENER-EXIT-UTILITY-LOAD-MISS | MONITORING | Utility load-growth disappoints vs AI-power forecasts | NEE / SO / CEG materially lower load-growth guidance, OR ERCOT / PJM forward-curves cut | research-only: re-evaluate sector sleeve; consider defined-risk hedges via the existing options layer (separate approval required); NO order execution |
| ENER-EXIT-TURBINE-BACKLOG-DETERIORATE | MONITORING | Gas-turbine / equipment backlog deteriorates | GEV / SIE turbine backlog growth halts or reverses; book-to-bill < 1.0 across two prints | research-only: re-evaluate sector sleeve; consider defined-risk hedges via the existing options layer (separate approval required); NO order execution |
| ENER-EXIT-REGULATORY-SHOCK | MONITORING | Punitive state PUC rate-case decision OR FERC ruling compresses utility returns | Material adverse final order in a CEG / NEE / SO rate case, OR FERC capacity-market change | research-only: re-evaluate sector sleeve; consider defined-risk hedges via the existing options layer (separate approval required); NO order execution |
| ENER-EXIT-AI-POWER-NARRATIVE-REVERSAL | MONITORING | AI-power demand narrative reverses (multiple hyperscalers cite over-build / capacity slack) | Two or more of MSFT / GOOGL / AMZN / META explicitly cite excess power capacity / delayed data-center commissioning | research-only: re-evaluate sector sleeve; consider defined-risk hedges via the existing options layer (separate approval required); NO order execution |
| ENER-EXIT-OIL-DEMAND-SHOCK | MONITORING | Material oil/gas demand shock (recession or EV substitution acceleration) | EIA / IEA cuts global oil demand by >1.5 mbd across consecutive prints | research-only: re-evaluate sector sleeve; consider defined-risk hedges via the existing options layer (separate approval required); NO order execution |
| ENER-EXIT-COMMODITY-PRICE-COLLAPSE | MONITORING | WTI / Brent crude price collapses below break-even | WTI < $50/bbl sustained for >1 quarter, OR Brent < $55 | research-only: re-evaluate sector sleeve; consider defined-risk hedges via the existing options layer (separate approval required); NO order execution |
| ENER-EXIT-CAPEX-DISCIPLINE-BREAK | MONITORING | Oil major capex discipline visibly breaks (capex rises sharply faster than OCF) | XOM / CVX / COP capex guide raised materially while OCF guide is flat / cut | research-only: re-evaluate sector sleeve; consider defined-risk hedges via the existing options layer (separate approval required); NO order execution |
| ENER-EXIT-DIVIDEND-COVERAGE-STRESS | MONITORING | Dividend / buyback coverage stress at the integrated majors | XOM / CVX / COP OCF falls below dividend + buyback run-rate for >2 quarters | research-only: re-evaluate sector sleeve; consider defined-risk hedges via the existing options layer (separate approval required); NO order execution |

## Scoring scheme (pre-declared, not optimized)
- Tier 1 weight = 2; Tier 2 weight = 1.
- Status values: BULL=+1, NEUTRAL=0, NEAR_THRESHOLD=-1, BROKEN=-2.
- Normalized score = sum(weight × status) / sum(weight).
- Bands: >= 0.50 ACCUMULATE; >= 0.20 SELECTIVE_BUY; >= -0.10 HOLD; >= -0.30 AVOID_NEW_BUY; >= -0.60 REDUCE; else EXIT_WATCH.
- Any TRIGGERED emergency exit overrides → EXIT_WATCH.
- **No broker orders are produced.** The signal label is a research recommendation only; validation in V6.6 is separate.

**This is a research signal, not a trading signal, not investment advice, and not order execution.**

## Subsector split (AI_POWER_INFRA vs TRADITIONAL_ENERGY vs MACRO)


### AI_POWER_INFRA  —  10 catalysts (auto-derived 6/10)
- BULL 2 · NEUTRAL 8 · NEAR_THRESHOLD 0 · BROKEN 0

| catalyst_id | tier | status | current_value | source |
|---|---|---|---|---|
| ENER-GEV-REV-T1 | 1 | NEUTRAL | +9.0% (FY2024->FY2025) | SEC_EDGAR |
| ENER-ETN-REV-T1 | 1 | NEUTRAL | +10.3% (FY2024->FY2025) | SEC_EDGAR |
| ENER-VRT-REV-T1 | 1 | BULL | +27.7% (FY2024->FY2025) | SEC_EDGAR |
| ENER-PWR-REV-T1 | 1 | BULL | +20.3% (FY2024->FY2025) | SEC_EDGAR |
| ENER-CEG-REV-T1 | 1 | NEUTRAL | +19.5% (FY2024->FY2025) | SEC_EDGAR |
| ENER-NEE-REV-T2 | 2 | NEUTRAL | n/a | MANUAL |
| ENER-SO-REV-T2 | 2 | NEUTRAL | +10.6% (FY2024->FY2025) | SEC_EDGAR |
| ENER-DATACENTER-POWER-DEMAND-T1 | 1 | NEUTRAL | n/a | MANUAL |
| ENER-NUCLEAR-SMR-T2 | 2 | NEUTRAL | n/a | MANUAL |
| ENER-REGULATORY-RATECASE-T2 | 2 | NEUTRAL | n/a | MANUAL |

### TRADITIONAL_ENERGY  —  6 catalysts (auto-derived 4/6)
- BULL 0 · NEUTRAL 6 · NEAR_THRESHOLD 0 · BROKEN 0

| catalyst_id | tier | status | current_value | source |
|---|---|---|---|---|
| ENER-XOM-REV-T1 | 1 | NEUTRAL | -5.0% (FY2024->FY2025) | SEC_EDGAR |
| ENER-CVX-REV-T1 | 1 | NEUTRAL | -4.6% (FY2024->FY2025) | SEC_EDGAR |
| ENER-COP-REV-T2 | 2 | NEUTRAL | +4.9% (FY2024->FY2025) | SEC_EDGAR |
| ENER-OILGAS-OCF-T2 | 2 | NEUTRAL | -0.9% (latest FYE 2025-12-31) | SEC_EDGAR |
| ENER-COMMODITY-OIL-T1 | 1 | NEUTRAL | n/a | MANUAL |
| ENER-LNG-CONTRACTS-T2 | 2 | NEUTRAL | n/a | MANUAL |

### MACRO  —  3 catalysts (auto-derived 3/3)
- BULL 2 · NEUTRAL 0 · NEAR_THRESHOLD 1 · BROKEN 0

| catalyst_id | tier | status | current_value | source |
|---|---|---|---|---|
| ENER-MACRO-RATES-T2 | 2 | NEAR_THRESHOLD | 4.57% (2026-05-20) | FRED |
| ENER-MACRO-VOL-T2 | 2 | BULL | 17.44 (2026-05-20) | YFINANCE |
| ENER-MACRO-CURVE-T2 | 2 | BULL | +0.53pp (2026-05-20) | FRED |

## Auto-derived catalysts (V6.4)

| catalyst_id | tier | status | current_value | source |
|---|---|---|---|---|
| ENER-GEV-REV-T1 | 1 | NEUTRAL | +9.0% (FY2024->FY2025) | SEC_EDGAR |
| ENER-ETN-REV-T1 | 1 | NEUTRAL | +10.3% (FY2024->FY2025) | SEC_EDGAR |
| ENER-VRT-REV-T1 | 1 | BULL | +27.7% (FY2024->FY2025) | SEC_EDGAR |
| ENER-PWR-REV-T1 | 1 | BULL | +20.3% (FY2024->FY2025) | SEC_EDGAR |
| ENER-CEG-REV-T1 | 1 | NEUTRAL | +19.5% (FY2024->FY2025) | SEC_EDGAR |
| ENER-SO-REV-T2 | 2 | NEUTRAL | +10.6% (FY2024->FY2025) | SEC_EDGAR |
| ENER-XOM-REV-T1 | 1 | NEUTRAL | -5.0% (FY2024->FY2025) | SEC_EDGAR |
| ENER-CVX-REV-T1 | 1 | NEUTRAL | -4.6% (FY2024->FY2025) | SEC_EDGAR |
| ENER-COP-REV-T2 | 2 | NEUTRAL | +4.9% (FY2024->FY2025) | SEC_EDGAR |
| ENER-OILGAS-OCF-T2 | 2 | NEUTRAL | -0.9% (latest FYE 2025-12-31) | SEC_EDGAR |
| ENER-MACRO-RATES-T2 | 2 | NEAR_THRESHOLD | 4.57% (2026-05-20) | FRED |
| ENER-MACRO-VOL-T2 | 2 | BULL | 17.44 (2026-05-20) | YFINANCE |
| ENER-MACRO-CURVE-T2 | 2 | BULL | +0.53pp (2026-05-20) | FRED |
## Data gaps (unverified / MANUAL or stale catalysts)

| catalyst_id | catalyst_name | source_detail |
|---|---|---|
| ENER-NEE-REV-T2 | NextEra Energy revenue YoY (utility + renewables) | SEC:NEE companyfacts (stale: latest FYE 2012-12-31) |
| ENER-DATACENTER-POWER-DEMAND-T1 | Data-center power demand growth (AI-driven) | Utility 10-K segment commentary + EIA / ERCOT / PJM reports (manual) |
| ENER-NUCLEAR-SMR-T2 | Nuclear / SMR progress and orders | NuScale / X-energy / TerraPower / Holtec / NRC announcements (manual; not US SEC filers in standard sense) |
| ENER-REGULATORY-RATECASE-T2 | Utility regulatory / rate-case risk | State PUCs + FERC dockets (manual monitoring; see emergency-exit ENER-EXIT-REGULATORY-SHOCK) |
| ENER-COMMODITY-OIL-T1 | WTI / Brent crude oil price regime | FRED DCOILWTICO / DCOILBRENTEU not in local cache; EIA STEO reports also manual |
| ENER-LNG-CONTRACTS-T2 | LNG export contracts + EU/Asia demand | LNG.com / Cheniere / Venture Global commentary + 8-K announcements (manual) |

_Manual / unverified catalysts are written with status `NEUTRAL` and explicit data-gap notes — no values are invented. They still consume scoring weight, so an unverified sector reads as deliberately cautious until populated._

## Next recommended step
1. **V6.5 Streamlit dashboard** is now the natural next phase — three sector trackers (SEMI / AI / ENERGY) are populated with consistent auto-derived signals, ready to render in a single decision-support UI. (Note: streamlit is NOT installed; V6.5 requires explicit approval to add it.)
2. **V6.4.1 refinement (optional)** could fetch additional FRED series (DCOILWTICO, DHHNGSP, DPROPANEMBTX) to auto-derive the commodity catalysts; segment-level utility load-growth would require XBRL segment extraction (out of current scope).
3. **Do NOT fetch options data** for energy names without an explicit pre-registered hypothesis (V5.9 discipline).
4. The AI-power-infra subsector is structurally coupled to the V6.3 AI tracker — `AI-EXIT-HYPERSCALER-CAPEX-CUT` is cross-referenced in `ENER-EXIT-DATACENTER-CAPEX-CUT` and `ENER-EXIT-AI-POWER-NARRATIVE-REVERSAL`.

## Future roadmap (NOTE ONLY — not implemented)
See `reports/research/sector_tracker/ROADMAP.md` for the full V6.7 / V6.8 / V6.9 plan (company-level signal ledger, sector aggregation from company signals, sector-level historical backtest). None of those phases is implemented; nothing here is tradable.
