# V5.7.1 Next research plan (ranked)

Priorities are RESEARCH directions, not deployment steps. `LIVE_TRADING_ENABLED` stays False until a real, regime-robust edge is demonstrated out-of-sample.


## A. New strategy research (highest priority)

The three directional verticals are exhausted as edge candidates. Research instead structures whose thesis is NOT pure direction:
- **IV / volatility-risk-premium (VRP):** sell defined-risk premium when implied >> realized; the V5.7 layer already has IV + a realized-vol helper to build the IV-RV spread signal.
- **Range-filtered defined-risk credit structures:** iron condors / credit spreads gated by an explicit IV-rank / expected-move filter, so entries require a vol-premium condition, not a direction call.
- **Calendar / diagonal spreads** if the data's DTE coverage supports a front/back structure (term-structure premium).
- **Regime-aware strategy selection** (e.g. bear_put in down regimes, bull_put in up regimes) — but this is only worth pursuing AFTER strict out-of-sample testing, since it risks fitting the 2022 regime labels.
Every new structure must clear the SAME falsification stack (V5.3->V5.6 + Stage 2A/2B-style regime splits) before any edge claim.


## B. Company / fundamentals research layer

- SEC EDGAR (10-K / 10-Q / 8-K) read-only ingestion.
- Balance-sheet / debt / liquidity / revenue-earnings context.
- Company-specific options research (e.g. AAPL / NVDA) once a single-name options dataset is approved.
- LSEG / Datastream only if a license is available.
Read-only and additive, like the V5.7 macro layer. No trading signal until separately validated.


## C. Optional 2023 Q1 confirmation

- SPY Jan-Mar 2023 (one quarter) is OPTIONAL out-of-sample confirmation in a non-2022 recovery/sideways regime.
- Expected to re-confirm the regime-directional reading (bull_put relatively better, bear_put worse). Not required for the verdict.
- Fetch ONLY if paired with a specific new hypothesis (e.g. testing an IV/VRP structure on fresh data), not to re-test rejected verticals.


## D. V6 paper trading — NOT yet

- Premature: no edge established.
- Would require live options data + options permission (and, for IBKR paper orders, a broker connection) — all currently OUT of scope.
- Defer until a strategy demonstrates regime-robust positive expectancy out-of-sample.
