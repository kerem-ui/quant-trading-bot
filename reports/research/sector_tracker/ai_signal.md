# AI Sector Thesis Tracker — Signal

*Read-only DECISION-SUPPORT output. NOT a trading signal, NOT a broker order, NOT investment advice. `LIVE_TRADING_ENABLED = False`.*


- Sector: **AI**
- **Signal: SELECTIVE_BUY**
- Normalized score: **+0.310** (raw +9.0 / total weight 29)
- Catalysts: 20 (BULL 8, NEUTRAL 11, NEAR_THRESHOLD 1, BROKEN 0)
- Emergency exit triggered: **False** (triggered: none)

## Top bull drivers
- Hyperscaler capex (MSFT+GOOGL+META aggregate YoY)
- Meta revenue YoY
- Alphabet operating margin
- Macro regime — 2s10s curve (T10Y2Y)
- Macro regime — equity volatility (VIX)

## Top risks (BROKEN / NEAR_THRESHOLD)
- Macro regime — long-end rates (DGS10)

## Catalysts (raw)
| catalyst_id | tier | status | catalyst_name | threshold | current | action_if_broken |
|---|---|---|---|---|---|---|
| AI-MSFT-REV-T1 | 1 | NEUTRAL | Microsoft revenue YoY | +20% YoY (BULL); -10..+20 NEUTRAL; -25..-10 NEAR; <-25 BROKEN | +14.9% (FY2024->FY2025) | review thesis (no order) |
| AI-GOOGL-REV-T1 | 1 | NEUTRAL | Alphabet revenue YoY | +20% YoY (BULL); -10..+20 NEUTRAL; -25..-10 NEAR; <-25 BROKEN | +15.1% (FY2024->FY2025) | review thesis (no order) |
| AI-AMZN-REV-T1 | 1 | NEUTRAL | Amazon revenue YoY | +20% YoY (BULL); -10..+20 NEUTRAL; -25..-10 NEAR; <-25 BROKEN | +12.4% (FY2024->FY2025) | review thesis (no order) |
| AI-META-REV-T1 | 1 | BULL | Meta revenue YoY | +20% YoY (BULL); -10..+20 NEUTRAL; -25..-10 NEAR; <-25 BROKEN | +22.2% (FY2024->FY2025) | review thesis (no order) |
| AI-ORCL-REV-T1 | 1 | NEUTRAL | Oracle revenue YoY (cloud + Stargate) | +20% YoY (BULL); -10..+20 NEUTRAL; -25..-10 NEAR; <-25 BROKEN | +8.4% (FY2024->FY2025) | review thesis (no order) |
| AI-HYPERSCALER-CAPEX-T1 | 1 | BULL | Hyperscaler capex (MSFT+GOOGL+META aggregate YoY) | +20% YoY (BULL); -10..+20 NEUTRAL; -25..-10 NEAR; <-25 BROKEN | +68.1% (latest FYE 2025-12-31) | review AI-infrastructure exposure (no order) |
| AI-PLTR-REV-T2 | 2 | BULL | Palantir revenue YoY | +20% YoY (BULL); -10..+20 NEUTRAL; -25..-10 NEAR; <-25 BROKEN | +56.2% (FY2024->FY2025) | review thesis (no order) |
| AI-MSFT-OPMARGIN-T2 | 2 | BULL | Microsoft operating margin | >=30% BULL; 20..30 NEUTRAL; 10..20 NEAR; <10 BROKEN | 45.6% (FYE 2025-06-30) | review thesis |
| AI-GOOGL-OPMARGIN-T2 | 2 | BULL | Alphabet operating margin | >=30% BULL; 20..30 NEUTRAL; 10..20 NEAR; <10 BROKEN | 32.0% (FYE 2025-12-31) | review thesis |
| AI-RD-GROWTH-T2 | 2 | BULL | R&D growth (MSFT+GOOGL+META+ORCL aggregate YoY) | +20% YoY (BULL); -10..+20 NEUTRAL; -25..-10 NEAR; <-25 BROKEN | +22.2% (latest FYE 2025-12-31) | review AI R&D commitment (no order) |
| AI-MACRO-RATES-T2 | 2 | NEAR_THRESHOLD | Macro regime — long-end rates (DGS10) | <=4.00 BULL; <=4.50 NEUTRAL; <=5.00 NEAR; >5.00 BROKEN | 4.57% (2026-05-20) | monitor rates |
| AI-MACRO-VOL-T2 | 2 | BULL | Macro regime — equity volatility (VIX) | <=18 BULL; <=22 NEUTRAL; <=30 NEAR; >30 BROKEN | 17.44 (2026-05-20) | monitor volatility regime |
| AI-MACRO-CURVE-T2 | 2 | BULL | Macro regime — 2s10s curve (T10Y2Y) | >=+0.30 BULL; >=0 NEUTRAL; >=-0.30 NEAR; <-0.30 BROKEN | +0.53pp (2026-05-20) | monitor curve |
| AI-OPENAI-ARR-T1 | 1 | NEUTRAL | OpenAI ARR / funding status | >$10B ARR + funded = BULL; $5..10B = NEUTRAL; <$5B / funding stress = BROKEN | n/a | review AI infrastructure thesis (no order) |
| AI-ANTHROPIC-ARR-T1 | 1 | NEUTRAL | Anthropic ARR / private valuation | qualitative: rising ARR + funded = BULL; stress = BROKEN | n/a | review AI infrastructure thesis (no order) |
| AI-REGULATION-RISK-T1 | 1 | NEUTRAL | AI regulation / export-control risk | no new material AI/chip rule = NEUTRAL; new ban/Section-232/EU AI Act enforcement = BROKEN | n/a | see emergency-exit AI-EXIT-REGULATION-SHOCK |
| AI-MODEL-PRICING-T2 | 2 | NEUTRAL | AI model API pricing pressure | pricing stable / capacity-led = NEUTRAL; sustained > 30% price cuts = BROKEN | n/a | review margin assumptions (no order) |
| AI-ENTERPRISE-ROI-T2 | 2 | NEUTRAL | Enterprise AI ROI evidence | rising adoption metrics + ROI case studies = BULL; broad disillusionment + reversed deployments = BROKEN | n/a | review thesis breadth (no order) |
| AI-CUSTOM-SILICON-T2 | 2 | NEUTRAL | Hyperscaler custom silicon displacement of merchant accelerators | qualitative: accelerating share to TPU/Trainium/Maia = BROKEN | n/a | review NVDA share assumptions; cross-referenced in semi tracker |
| AI-OPTIONS-RISK-T2 | 2 | NEUTRAL | Options IV-rank / skew / liquidity (AI names) | low IV-rank + tight liquidity = NEUTRAL; elevated risk = BROKEN | n/a | do not fetch options data without explicit approval (V5.9 discipline) |

## Emergency exits
| exit_id | status | scenario | trigger | action |
|---|---|---|---|---|
| AI-EXIT-HYPERSCALER-CAPEX-CUT | MONITORING | Big-Tech / hyperscaler capex guide cut materially | MSFT / GOOGL / AMZN / META aggregate capex guidance YoY revised LOWER by >=10% across two consecutive prints | research-only: re-evaluate sector sleeve; consider defined-risk hedges via the existing options layer (separate approval required); NO order execution |
| AI-EXIT-CLOUD-DECEL | MONITORING | Cloud growth decelerates across Azure / AWS / Google Cloud | Two of {Azure / AWS / Google Cloud} report cloud-segment growth deceleration QoQ over two consecutive quarters | research-only: re-evaluate sector sleeve; consider defined-risk hedges via the existing options layer (separate approval required); NO order execution |
| AI-EXIT-INFRA-FINANCING-STRESS | MONITORING | AI infrastructure financing stress or major customer renegotiation | Material AI compute commitment renegotiated lower OR publicly reported financing stress at a major lab / hyperscaler | research-only: re-evaluate sector sleeve; consider defined-risk hedges via the existing options layer (separate approval required); NO order execution |
| AI-EXIT-LAB-SCALING-PULLBACK | MONITORING | Frontier AI lab pulls back on scaling commitments | OpenAI / Anthropic / GOOGL DeepMind / Meta AI publicly delay / cancel next-generation training-run plans | research-only: re-evaluate sector sleeve; consider defined-risk hedges via the existing options layer (separate approval required); NO order execution |
| AI-EXIT-MODEL-PRICING-COLLAPSE | MONITORING | AI model token price erosion accelerates sharply | Sustained > 50% price cuts across multiple frontier providers within a quarter | research-only: re-evaluate sector sleeve; consider defined-risk hedges via the existing options layer (separate approval required); NO order execution |
| AI-EXIT-REGULATION-SHOCK | MONITORING | Major AI regulation / export-control shock | New material rule (US export controls / EU AI Act enforcement action / China response) targeting AI accelerators or model deployment | research-only: re-evaluate sector sleeve; consider defined-risk hedges via the existing options layer (separate approval required); NO order execution |

## Scoring scheme (pre-declared, not optimized)
- Tier 1 weight = 2; Tier 2 weight = 1.
- Status values: BULL=+1, NEUTRAL=0, NEAR_THRESHOLD=-1, BROKEN=-2.
- Normalized score = sum(weight × status) / sum(weight).
- Bands: >= 0.50 ACCUMULATE; >= 0.20 SELECTIVE_BUY; >= -0.10 HOLD; >= -0.30 AVOID_NEW_BUY; >= -0.60 REDUCE; else EXIT_WATCH.
- Any TRIGGERED emergency exit overrides → EXIT_WATCH.
- **No broker orders are produced.** The signal label is a research recommendation only; validation in V6.6 is separate.

**This is a research signal, not a trading signal, not investment advice, and not order execution.**

## Auto-derived catalysts (V6.3)

| catalyst_id | tier | status | current_value | source |
|---|---|---|---|---|
| AI-MSFT-REV-T1 | 1 | NEUTRAL | +14.9% (FY2024->FY2025) | SEC_EDGAR |
| AI-GOOGL-REV-T1 | 1 | NEUTRAL | +15.1% (FY2024->FY2025) | SEC_EDGAR |
| AI-AMZN-REV-T1 | 1 | NEUTRAL | +12.4% (FY2024->FY2025) | SEC_EDGAR |
| AI-META-REV-T1 | 1 | BULL | +22.2% (FY2024->FY2025) | SEC_EDGAR |
| AI-ORCL-REV-T1 | 1 | NEUTRAL | +8.4% (FY2024->FY2025) | SEC_EDGAR |
| AI-HYPERSCALER-CAPEX-T1 | 1 | BULL | +68.1% (latest FYE 2025-12-31) | SEC_EDGAR |
| AI-PLTR-REV-T2 | 2 | BULL | +56.2% (FY2024->FY2025) | SEC_EDGAR |
| AI-MSFT-OPMARGIN-T2 | 2 | BULL | 45.6% (FYE 2025-06-30) | SEC_EDGAR |
| AI-GOOGL-OPMARGIN-T2 | 2 | BULL | 32.0% (FYE 2025-12-31) | SEC_EDGAR |
| AI-RD-GROWTH-T2 | 2 | BULL | +22.2% (latest FYE 2025-12-31) | SEC_EDGAR |
| AI-MACRO-RATES-T2 | 2 | NEAR_THRESHOLD | 4.57% (2026-05-20) | FRED |
| AI-MACRO-VOL-T2 | 2 | BULL | 17.44 (2026-05-20) | YFINANCE |
| AI-MACRO-CURVE-T2 | 2 | BULL | +0.53pp (2026-05-20) | FRED |
## Data gaps (unverified / MANUAL or stale catalysts)

| catalyst_id | catalyst_name | source_detail |
|---|---|---|
| AI-OPENAI-ARR-T1 | OpenAI ARR / funding status | Private company — no SEC filings; rely on operator-curated entries |
| AI-ANTHROPIC-ARR-T1 | Anthropic ARR / private valuation | Private company — no SEC filings |
| AI-REGULATION-RISK-T1 | AI regulation / export-control risk | BIS / Commerce / EU AI Act / state-level announcements (manual monitoring) |
| AI-MODEL-PRICING-T2 | AI model API pricing pressure | OpenAI / Anthropic / GOOGL Gemini / xAI public pricing pages (manual tracking) |
| AI-ENTERPRISE-ROI-T2 | Enterprise AI ROI evidence | Hyperscaler 10-Q / 10-K AI revenue commentary, Gartner / IDC adoption reports (manual) |
| AI-CUSTOM-SILICON-T2 | Hyperscaler custom silicon displacement of merchant accelerators | MSFT / GOOGL / AMZN 10-K + earnings commentary (manual) |

_Manual / unverified catalysts are written with status `NEUTRAL` and explicit data-gap notes — no values are invented. They still consume scoring weight, so an unverified sector reads as deliberately cautious until populated._

## Next recommended step
1. **V6.4 Energy / power infrastructure tracker** is the natural next phase now that the AI driver auto-derives reliably for the major US AI infrastructure filers.
2. **V6.3.1 refinement (optional)** could add: (a) segment-level cloud growth (Azure / AWS / Google Cloud) — requires XBRL segment extraction, currently out of scope; (b) OpenAI / Anthropic manual-entry helpers; (c) AMZN R&D under non-standard tag (`TechnologyAndContentExpense`) — still requires care.
3. **Do NOT fetch options data** for AI names without an explicit pre-registered hypothesis (V5.9 discipline).
4. The hyperscaler-capex BULL is the dominant AI-infrastructure investment signal here; the emergency-exit `AI-EXIT-HYPERSCALER-CAPEX-CUT` is the most important monitor.

## Future roadmap (NOTE ONLY — not implemented)
See `reports/research/sector_tracker/ROADMAP.md` for the full V6.7 / V6.8 / V6.9 plan (company-level signal ledger, sector aggregation from company signals, sector-level historical backtest). None of those phases is implemented; nothing here is tradable.
