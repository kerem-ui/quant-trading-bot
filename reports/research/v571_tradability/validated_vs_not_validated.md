# V5.7.1 Validated vs NOT validated

## Validated (mechanics / infrastructure)

- V5.0 options backtest engine: decision<fill causality, daily MTM, expiration settlement, force-close at final bar, defined-risk debit/credit accounting. Verified across 24+ (window x strategy) runs, all causality-clean, deterministic.
- Defined-risk debit AND credit vertical accounting (bull_call / bear_put debit; bull_put credit). Naked / unlimited-risk structures are impossible by construction.
- No look-ahead / causality discipline (asserted in engine + tested).
- ThetaData historical options pipeline: full calendar-year SPY 2022, 1,096,626 canonical rows, 251 date-files, 100% Greeks coverage, 0 validator hard rejects, 0 processed duplicate rows.
- IV / Greeks enrichment (greeks/eod), edge-of-band 472 handling, 240s OPEX timeout, multi-chunk EOD + Greeks-regeneration repair.
- Cost / spread sensitivity reporting (V5.4).
- Rolling-window (V5.5) + non-overlapping (V5.6) stability framework.
- Macro / FRED / event read-only research + annotation layer (V5.7), including expectancy / tradability decomposition.
- 219/219 pytest green throughout.


## NOT validated (no evidence yet)

- A deployable trading edge.
- Regime-independent profitability for any of the three verticals.
- Live / paper execution of any kind.
- IBKR (or any broker) execution.
- Any options strategy suitable for deployment.
- Macro / regime / event signals as TRADING filters (V5.7 is annotation only; no signal feeds the engine).
