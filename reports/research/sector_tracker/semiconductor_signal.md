# SEMICONDUCTOR Sector Thesis Tracker — Signal

*Read-only DECISION-SUPPORT output. NOT a trading signal, NOT a broker order, NOT investment advice. `LIVE_TRADING_ENABLED = False`.*


- Sector: **SEMICONDUCTOR**
- **Signal: SELECTIVE_BUY**
- Normalized score: **+0.280** (raw +7.0 / total weight 25)
- Catalysts: 17 (BULL 7, NEUTRAL 8, NEAR_THRESHOLD 1, BROKEN 1)
- Emergency exit triggered: **False** (triggered: none)

## Top bull drivers
- HBM / memory cycle (MU revenue YoY)
- Memory cycle recovery (MU net income YoY delta)
- Nvidia revenue YoY (AI accelerator demand)
- AMD revenue YoY
- AVGO revenue YoY (AI custom silicon / networking)

## Top risks (BROKEN / NEAR_THRESHOLD)
- Semi inventory cycle (NVDA+AMD+MU+AVGO aggregate InventoryNet YoY)
- Macro regime — long-end rates (DGS10)

## Catalysts (raw)
| catalyst_id | tier | status | catalyst_name | threshold | current | action_if_broken |
|---|---|---|---|---|---|---|
| SEMI-MU-HBM-REV-T1 | 1 | BULL | HBM / memory cycle (MU revenue YoY) | +20% YoY (BULL); -10..+20 NEUTRAL; -25..-10 NEAR; <-25 BROKEN | +48.9% (FY2024->FY2025) | review sector sleeve; pause adds; do not auto-trade |
| SEMI-MU-MEMCYCLE-NI-T1 | 1 | BULL | Memory cycle recovery (MU net income YoY delta) | +$1.0B (BULL); -1..+1 NEUTRAL; -5..-1 NEAR; <-5 BROKEN | +7.76B (FY2024->FY2025) | review sector sleeve |
| SEMI-NVDA-REV-T1 | 1 | BULL | Nvidia revenue YoY (AI accelerator demand) | +20% YoY (BULL); -10..+20 NEUTRAL; -25..-10 NEAR; <-25 BROKEN | +65.5% (FY2025->FY2026) | review sector sleeve; pause adds; do not auto-trade |
| SEMI-NVDA-GM-T1 | 1 | NEUTRAL | Nvidia gross margin | >=72% BULL; 65..72 NEUTRAL; 60..65 NEAR; <60 BROKEN | 71.1% (FYE 2026-01-25) | review NVDA exposure |
| SEMI-AMD-REV-T2 | 2 | BULL | AMD revenue YoY | +20% YoY (BULL); -10..+20 NEUTRAL; -25..-10 NEAR; <-25 BROKEN | +34.3% (FY2024->FY2025) | review sector sleeve; pause adds; do not auto-trade |
| SEMI-AVGO-REV-T2 | 2 | BULL | AVGO revenue YoY (AI custom silicon / networking) | +20% YoY (BULL); -10..+20 NEUTRAL; -25..-10 NEAR; <-25 BROKEN | +23.9% (FY2024->FY2025) | review sector sleeve; pause adds; do not auto-trade |
| SEMI-EQUIPMENT-DEMAND-T2 | 2 | NEUTRAL | Semi equipment demand (AMAT+LRCX+KLAC aggregate revenue YoY) | +20% YoY (BULL); -10..+20 NEUTRAL; -25..-10 NEAR; <-25 BROKEN | +13.6% (latest FYE 2025-10-26) | review equipment-maker exposure |
| SEMI-INVENTORY-CYCLE-T2 | 2 | BROKEN | Semi inventory cycle (NVDA+AMD+MU+AVGO aggregate InventoryNet YoY) | <=+10% BULL (controlled); +10..30 NEUTRAL; +30..50 NEAR; >+50 BROKEN | +51.0% (latest FYE 2026-01-25) | monitor sector inventory; consider pacing |
| SEMI-MACRO-RATES-T2 | 2 | NEAR_THRESHOLD | Macro regime — long-end rates (DGS10) | <=4.00 BULL; <=4.50 NEUTRAL; <=5.00 NEAR; >5.00 BROKEN | 4.57% (2026-05-20) | monitor rates |
| SEMI-MACRO-VOL-T2 | 2 | BULL | Macro regime — equity volatility (VIX) | <=18 BULL; <=22 NEUTRAL; <=30 NEAR; >30 BROKEN | 17.44 (2026-05-20) | monitor volatility regime |
| SEMI-MACRO-CURVE-T2 | 2 | BULL | Macro regime — 2s10s curve (T10Y2Y) | >=+0.30 BULL; >=0 NEUTRAL; >=-0.30 NEAR; <-0.30 BROKEN | +0.53pp (2026-05-20) | monitor curve |
| SEMI-NVDA-DC-REV-T1 | 1 | NEUTRAL | Nvidia data-center revenue (segment) | >+50% YoY BULL; +20..+50 NEUTRAL; 0..+20 NEAR; <0 BROKEN | n/a | review NVDA exposure separately; no auto-trade |
| SEMI-TSM-N3-DEMAND-T1 | 1 | NEUTRAL | TSMC advanced-node (N3/N5) demand | qualitative | n/a | review foundry exposure |
| SEMI-ASML-BOOKINGS-T1 | 1 | NEUTRAL | ASML bookings / EUV demand | qualitative | n/a | review equipment-maker exposure |
| SEMI-CHINA-EXPORT-RISK-T1 | 1 | NEUTRAL | China / US export-control policy risk | no new material restrictions = NEUTRAL; new ban = BROKEN | n/a | see emergency-exit SEMI-EXIT-CHINA-EXPORT-SHOCK |
| SEMI-CUSTOM-SILICON-T2 | 2 | NEUTRAL | Custom silicon / ASIC displacement risk (hyperscaler in-house) | qualitative: accelerating displacement = BROKEN | n/a | monitor NVDA share-of-AI-accelerator commentary |
| SEMI-OPTIONS-RISK-T2 | 2 | NEUTRAL | Options IV-rank / skew / liquidity (semi names) | low IV-rank + tight liquidity = NEUTRAL; elevated risk = BROKEN | n/a | do not fetch options data without explicit approval (V5.9 discipline) |

## Emergency exits
| exit_id | status | scenario | trigger | action |
|---|---|---|---|---|
| SEMI-EXIT-NVDA-DC-SEQ-DECLINE | MONITORING | Nvidia data-center revenue posts a sequential (QoQ) decline | NVDA reported DC revenue QoQ < 0% in two consecutive quarterly 10-Q / earnings 8-K releases | research-only: re-evaluate sector sleeve; consider defined-risk hedges via the existing options layer (separate approval required); NO order execution |
| SEMI-EXIT-HYPERSCALER-CAPEX-CUT | MONITORING | Hyperscaler capex guide is cut materially | MSFT / GOOGL / AMZN / META capex guidance YoY revised lower by >= 10% across two consecutive prints | research-only: re-evaluate sector sleeve; consider defined-risk hedges via the existing options layer (separate approval required); NO order execution |
| SEMI-EXIT-HBM-ASP-DETERIORATION | MONITORING | HBM ASP / memory gross margin deteriorates sharply | MU gross-margin guide cut > 500 bps QoQ OR HBM ASP commentary turns negative in MU/SK Hynix releases | research-only: re-evaluate sector sleeve; consider defined-risk hedges via the existing options layer (separate approval required); NO order execution |
| SEMI-EXIT-CHINA-EXPORT-SHOCK | MONITORING | Major new US/China export-control restriction on AI chips | New BIS rule or Entity-List action materially restricting AI accelerator exports / specific names | research-only: re-evaluate sector sleeve; consider defined-risk hedges via the existing options layer (separate approval required); NO order execution |
| SEMI-EXIT-CUSTOM-SILICON-DISPLACE | MONITORING | Custom silicon displacement of merchant AI accelerators accelerates | Two or more hyperscalers disclose accelerating share shift to in-house ASIC (TPU / Trainium / Maia) over consecutive prints | research-only: re-evaluate sector sleeve; consider defined-risk hedges via the existing options layer (separate approval required); NO order execution |
| SEMI-EXIT-INVENTORY-SHARP-NEG | MONITORING | Semiconductor inventory cycle turns sharply negative | Aggregate semi-customer inventory days rise materially QoQ AND two or more sector names guide revenue lower on inventory digestion | research-only: re-evaluate sector sleeve; consider defined-risk hedges via the existing options layer (separate approval required); NO order execution |

## Scoring scheme (pre-declared, not optimized)
- Tier 1 weight = 2; Tier 2 weight = 1.
- Status values: BULL=+1, NEUTRAL=0, NEAR_THRESHOLD=-1, BROKEN=-2.
- Normalized score = sum(weight × status) / sum(weight).
- Bands: >= 0.50 ACCUMULATE; >= 0.20 SELECTIVE_BUY; >= -0.10 HOLD; >= -0.30 AVOID_NEW_BUY; >= -0.60 REDUCE; else EXIT_WATCH.
- Any TRIGGERED emergency exit overrides → EXIT_WATCH.
- **No broker orders are produced.** The signal label is a research recommendation only; validation in V6.6 is separate.

**This is a research signal, not a trading signal, not investment advice, and not order execution.**

## Auto-derived catalysts (V6.2.1)

| catalyst_id | tier | status | current_value | source |
|---|---|---|---|---|
| SEMI-MU-HBM-REV-T1 | 1 | BULL | +48.9% (FY2024->FY2025) | SEC_EDGAR |
| SEMI-MU-MEMCYCLE-NI-T1 | 1 | BULL | +7.76B (FY2024->FY2025) | SEC_EDGAR |
| SEMI-NVDA-REV-T1 | 1 | BULL | +65.5% (FY2025->FY2026) | SEC_EDGAR |
| SEMI-NVDA-GM-T1 | 1 | NEUTRAL | 71.1% (FYE 2026-01-25) | SEC_EDGAR |
| SEMI-AMD-REV-T2 | 2 | BULL | +34.3% (FY2024->FY2025) | SEC_EDGAR |
| SEMI-AVGO-REV-T2 | 2 | BULL | +23.9% (FY2024->FY2025) | SEC_EDGAR |
| SEMI-EQUIPMENT-DEMAND-T2 | 2 | NEUTRAL | +13.6% (latest FYE 2025-10-26) | SEC_EDGAR |
| SEMI-INVENTORY-CYCLE-T2 | 2 | BROKEN | +51.0% (latest FYE 2026-01-25) | SEC_EDGAR |
| SEMI-MACRO-RATES-T2 | 2 | NEAR_THRESHOLD | 4.57% (2026-05-20) | FRED |
| SEMI-MACRO-VOL-T2 | 2 | BULL | 17.44 (2026-05-20) | YFINANCE |
| SEMI-MACRO-CURVE-T2 | 2 | BULL | +0.53pp (2026-05-20) | FRED |
## Data gaps (unverified / MANUAL or stale catalysts)

| catalyst_id | catalyst_name | source_detail |
|---|---|---|
| SEMI-NVDA-DC-REV-T1 | Nvidia data-center revenue (segment) | NVDA 10-Q segment table (not in standard companyfacts top-level concepts; segment XBRL extraction is out of V6.2.1 scope) |
| SEMI-TSM-N3-DEMAND-T1 | TSMC advanced-node (N3/N5) demand | TSM 20-F / monthly revenue release (foreign filer; 20-F not in V6.1 SUPPORTED_FORMS) |
| SEMI-ASML-BOOKINGS-T1 | ASML bookings / EUV demand | ASML 20-F / Q-report (foreign filer) |
| SEMI-CHINA-EXPORT-RISK-T1 | China / US export-control policy risk | BIS/Commerce/State announcements (manual monitoring) |
| SEMI-CUSTOM-SILICON-T2 | Custom silicon / ASIC displacement risk (hyperscaler in-house) | manual tracking of Google TPU / AWS Trainium / Microsoft Maia announcements + hyperscaler 10-Qs |

_Manual / unverified catalysts are written with status `NEUTRAL` and explicit data-gap notes — no values are invented. They still consume scoring weight, so an unverified sector reads as deliberately cautious until populated._

## Next recommended step
1. **(Optional) TSM / ASML foreign-filer support** — would require extending the company layer to 20-F / 6-K forms; out of V6.2.1 scope.
2. **NVDA segment data** (data-center revenue) is still MANUAL — XBRL segment extraction is non-trivial and intentionally deferred.
3. **V6.3 AI tracker** is the natural next phase now that the company layer auto-derives reliably for US filers.
4. **Do NOT fetch options data** for semi names without an explicit pre-registered hypothesis (V5.9 discipline).

## Future roadmap (NOTE ONLY — not implemented)
See `reports/research/sector_tracker/ROADMAP.md` for the full V6.7 / V6.8 / V6.9 plan (company-level signal ledger, sector aggregation from company signals, sector-level historical backtest). None of those phases is implemented; nothing here is tradable.
