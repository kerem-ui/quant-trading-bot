# V5.7.1 / V5.8 Edge-Tradability Final Report — SPY defined-risk verticals (2022)

Consolidates V5.3 (strategy testing), V5.4 (robustness), V5.5 (rolling-window stability), V5.6 (non-overlapping windows), V5.7 (macro/FRED/event context), and the Stage 2A/2B strategy-edge checks into one decision document. Read-only: no new data, no ThetaData, no engine/strategy/default changes, no parameter optimization. `LIVE_TRADING_ENABLED = False`.


**Lens (Roman-Paolucci tradability principles):** profitability is not edge. We decompose expectancy, inspect winner/loss distributions, test sign + magnitude stability across regimes, identify regime dependence, and reject backtest profitability that does not survive a regime shift.


## 1. Is any current strategy deployable? — NO

No defined-risk vertical (bull_call, bear_put, bull_put) shows a positive expectancy that persists across BOTH the 2022 H1 bear and the Q4 recovery. Each is positive only in the regime that matches its directional bias. None is deployable.


## 2. Final verdict table

| strategy  | full_year_return_pct | full_year_expectancy_per_trade | full_year_profit_factor | windows_positive | windows_pf_gt_1 | best_window  | best_window_ret_pct | worst_window | worst_window_ret_pct | sign_stable_across_regimes | verdict                                                                                |
| --------- | -------------------- | ------------------------------ | ----------------------- | ---------------- | --------------- | ------------ | ------------------- | ------------ | -------------------- | -------------------------- | -------------------------------------------------------------------------------------- |
| bull_call | -1.6762              | -98.6000                       | 0.3890                  | 0/5              | 0/5             | oct_dec_2022 | -0.0404             | jan_dec_2022 | -1.6762              | True                       | NOT deployable; improved toward flat in recovery but no persistent positive expectancy |
| bear_put  | 0.1466               | 7.7200                         | 1.0920                  | 3/5              | 3/5             | jan_jun_2022 | 0.6490              | oct_dec_2022 | -0.3250              | False                      | REJECTED as regime-independent edge; regime-directional bearish bet (engine validated) |
| bull_put  | -2.0731              | -98.7200                       | 0.2760                  | 1/5              | 1/5             | oct_dec_2022 | 0.1045              | jan_sep_2022 | -2.3596              | False                      | NOT deployable; positive only in Q4 recovery; regime-directional bullish/credit bet    |

## 3. Expectancy decomposition (primary windows)

`expectancy_per_trade = P(win)*avg_win + P(loss)*avg_loss` ($/trade). `profit_factor = gross_win/|gross_loss|`.

| window       | strategy  | trades | win_rate | total_return_pct | avg_win_dollar | avg_loss_dollar | expectancy_per_trade_dollar | profit_factor | payoff_ratio | max_drawdown_pct | total_cost |
| ------------ | --------- | ------ | -------- | ---------------- | -------------- | --------------- | --------------------------- | ------------- | ------------ | ---------------- | ---------- |
| jan_jun_2022 | bear_put  | 10     | 0.7000   | 0.6490           | 158.5429       | -153.6000       | 64.9000                     | 2.4084        | 1.0322       | -0.4367          | 508.0000   |
| jul_sep_2022 | bear_put  | 5      | 0.6000   | -0.0285          | 163.7333       | -259.8500       | -5.7000                     | 0.9452        | 0.6301       | -0.5565          | 291.5000   |
| oct_dec_2022 | bear_put  | 5      | 0.2000   | -0.3250          | 121.4000       | -111.6000       | -65.0000                    | 0.2720        | 1.0878       | -0.6914          | 156.0000   |
| jan_sep_2022 | bear_put  | 15     | 0.6667   | 0.5090           | 160.1000       | -218.4000       | 33.9333                     | 1.4661        | 0.7331       | -0.8622          | 782.0000   |
| jan_dec_2022 | bear_put  | 19     | 0.5263   | 0.1466           | 174.7500       | -177.8778       | 7.7158                      | 1.0916        | 0.9824       | -1.0109          | 911.4000   |
| jan_jun_2022 | bull_call | 8      | 0.1250   | -1.2658          | 258.9000       | -217.8143       | -158.2250                   | 0.1698        | 1.1886       | -1.3790          | 134.8000   |
| jul_sep_2022 | bull_call | 5      | 0.4000   | -0.5115          | 157.4000       | -275.4333       | -102.3000                   | 0.3810        | 0.5715       | -1.0488          | 80.5000    |
| oct_dec_2022 | bull_call | 4      | 0.5000   | -0.0404          | 171.6500       | -191.8500       | -10.1000                    | 0.8947        | 0.8947       | -0.5987          | 101.4000   |
| jan_sep_2022 | bull_call | 13     | 0.3077   | -1.6213          | 181.0250       | -260.6000       | -124.7154                   | 0.3087        | 0.6946       | -1.6213          | 217.3000   |
| jan_dec_2022 | bull_call | 17     | 0.3529   | -1.6762          | 177.9000       | -249.4182       | -98.6000                    | 0.3891        | 0.7133       | -1.7614          | 318.2000   |
| jan_jun_2022 | bull_put  | 11     | 0.1818   | -1.4701          | 60.1500        | -176.7111       | -133.6455                   | 0.0756        | 0.3404       | -1.7382          | 270.1000   |
| jul_sep_2022 | bull_put  | 6      | 0.5000   | -0.9376          | 87.9000        | -400.4333       | -156.2667                   | 0.2195        | 0.2195       | -1.1981          | 174.6000   |
| oct_dec_2022 | bull_put  | 5      | 0.8000   | 0.1045           | 73.7750        | -190.6000       | 20.9000                     | 1.5483        | 0.3871       | -0.2767          | 75.5000    |
| jan_sep_2022 | bull_put  | 16     | 0.3125   | -2.3596          | 72.3000        | -247.3727       | -147.4750                   | 0.1329        | 0.2923       | -2.3596          | 419.6000   |
| jan_dec_2022 | bull_put  | 21     | 0.4762   | -2.0731          | 79.1000        | -260.3727       | -98.7190                    | 0.2762        | 0.3038       | -2.3703          | 492.1000   |

## 4. Regime dependence (does the strategy's sign track the regime?)

| strategy  | window       | regime                              | total_return_pct | profit_factor | positive_window | profit_factor_gt1 |
| --------- | ------------ | ----------------------------------- | ---------------- | ------------- | --------------- | ----------------- |
| bull_call | jan_jun_2022 | bear / downtrend                    | -1.2658          | 0.1698        | False           | False             |
| bull_call | jul_sep_2022 | bear-rally then renewed decline     | -0.5115          | 0.3810        | False           | False             |
| bull_call | oct_dec_2022 | bear-low -> Q4 recovery -> Dec fade | -0.0404          | 0.8947        | False           | False             |
| bull_call | jan_sep_2022 | bear + partial rebound              | -1.6213          | 0.3087        | False           | False             |
| bull_call | jan_dec_2022 | full-year mixed (bear -> recovery)  | -1.6762          | 0.3891        | False           | False             |
| bear_put  | jan_jun_2022 | bear / downtrend                    | 0.6490           | 2.4084        | True            | True              |
| bear_put  | jul_sep_2022 | bear-rally then renewed decline     | -0.0285          | 0.9452        | False           | False             |
| bear_put  | oct_dec_2022 | bear-low -> Q4 recovery -> Dec fade | -0.3250          | 0.2720        | False           | False             |
| bear_put  | jan_sep_2022 | bear + partial rebound              | 0.5090           | 1.4661        | True            | True              |
| bear_put  | jan_dec_2022 | full-year mixed (bear -> recovery)  | 0.1466           | 1.0916        | True            | True              |
| bull_put  | jan_jun_2022 | bear / downtrend                    | -1.4701          | 0.0756        | False           | False             |
| bull_put  | jul_sep_2022 | bear-rally then renewed decline     | -0.9376          | 0.2195        | False           | False             |
| bull_put  | oct_dec_2022 | bear-low -> Q4 recovery -> Dec fade | 0.1045           | 1.5483        | True            | True              |
| bull_put  | jan_sep_2022 | bear + partial rebound              | -2.3596          | 0.1329        | False           | False             |
| bull_put  | jan_dec_2022 | full-year mixed (bear -> recovery)  | -2.0731          | 0.2762        | False           | False             |

**Pattern:** bear_put is positive (PF>1) ONLY in down-trend windows; bull_put is positive (PF>1) ONLY in the Q4 recovery window; bull_call is never PF>1 (best is near-flat in the recovery). The signs are a mirror image driven by spot direction + vega (VIX 16->29 in the H1 bear; VIX 30->22 in the Q4 recovery). This is directional exposure, NOT independent structural edge.


## 5. bear_put falsification — CONFIRMED REJECTED

| window       | trades | win_rate | total_return_pct | expectancy_per_trade_dollar | profit_factor |
| ------------ | ------ | -------- | ---------------- | --------------------------- | ------------- |
| jan_jun_2022 | 10     | 0.7000   | 0.6490           | 64.9000                     | 2.4084        |
| jul_sep_2022 | 5      | 0.6000   | -0.0285          | -5.7000                     | 0.9452        |
| oct_dec_2022 | 5      | 0.2000   | -0.3250          | -65.0000                    | 0.2720        |
| jan_sep_2022 | 15     | 0.6667   | 0.5090           | 33.9333                     | 1.4661        |
| jan_dec_2022 | 19     | 0.5263   | 0.1466           | 7.7158                      | 1.0916        |

Expectancy/trade decays monotonically as non-bear regime is added: +$64.90 (Jan-Jun) -> +$33.93 (Jan-Sep) -> -$5.70 (Jul-Sep) -> -$65.00 (Oct-Dec). Profit factor falls 2.41 -> 0.27. The Jan-Jun +0.65% was a clean-bear artifact; it does NOT survive the Q4 recovery. bear_put is **rejected as a regime-independent tradable edge** and confirmed as a regime-directional bearish bet.


## 6. Winner / loss distribution read

- **bear_put:** avg win ~$159 vs avg loss ~$154 (payoff ~1.0); lives or dies on win PROBABILITY, which is regime-driven (70% in the bear, 20% in the recovery). Wins do not structurally outsize losses.
- **bull_put:** small avg win (~$73) vs larger avg loss (~$190); payoff ratio < 0.4; needs a very high win rate to profit, achieved ONLY in the calm recovery (80% Oct-Dec) and never in down regimes.
- **bull_call:** avg win ~$178 vs avg loss ~$250; payoff < 1 and low win rate; negative expectancy in every primary window.
- Across regimes, **no strategy keeps profit factor > 1** outside its favorable regime. Average wins do NOT compensate average losses on a through-the-cycle basis.


## 7. What is validated vs NOT validated

See `validated_vs_not_validated.md`. In short: the **engine, data pipeline, defined-risk accounting, IV/Greeks enrichment, robustness/stability framework, and macro/event research layer are validated**; a **deployable trading edge is NOT**.


## 8. Do we need 2023 data? — OPTIONAL, not required

Full-year 2022 already rejected all three verticals as regime-independent edges. A single confirmatory quarter (SPY Jan-Mar 2023, a non-2022 recovery/sideways regime) would only RE-CONFIRM the regime-directional reading; it is not needed to reach the verdict. Further 2023 data should be fetched ONLY in service of a specific NEW hypothesis (e.g. an IV/VRP strategy), not to keep re-testing a rejected edge.


## 9. Recommended next research directions

See `next_research_plan.md` for the ranked plan (A: new strategy research incl. IV/VRP & range-filtered credit structures; B: company/fundamentals layer; C: optional 2023 Q1 confirmation; D: paper trading — NOT yet).


## 10. Final answers

1. **Is any current strategy deployable?** No.
2. **Was bear_put falsified as a regime-independent edge?** Yes — rejected (Oct-Dec −0.33%, PF 0.27, expectancy −$65/trade).
3. **What did the bot validate?** Engine mechanics, defined-risk debit/credit accounting, no-look-ahead causality, the ThetaData historical pipeline (full-year SPY 2022: 1,096,626 rows, 100% Greeks, 0 hard rejects, 0 dup rows), IV/Greeks enrichment, cost/spread sensitivity, rolling/non-overlapping stability, and the macro/FRED/event read-only context layer.
4. **What next?** Move to NEW strategy research (IV/VRP, range-filtered defined-risk credit structures) and/or a company/fundamentals research layer — not more testing of the rejected verticals.
5. **Fetch 2023 now or move on?** Move on. 2023 Q1 is optional confirmation only; the verdict is already reached on 2022.


**Deployment warning:** This is a research finding, not a trading recommendation. No defined-risk vertical is deployable. No live trading, no broker, no IBKR. `LIVE_TRADING_ENABLED` remains False.
