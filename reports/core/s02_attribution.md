# S02 (CORE) - Deep Attribution & Robustness

_loaded 18 symbols x 4119 bars (2010-01-04 -> 2026-05-19). If yfinance was unreachable this is SYNTHETIC data (illustrative only, not market data) - see console log above._

DEFAULT blend: CAGR=0.0209 Sharpe=0.815 Sortino=0.964 maxDD=-0.0448 turnover=1.57 cost_drag=0.0149
vs SPY buy-hold: excess_cagr=-0.1201 IR=-0.822 beta=0.114 down_capture=0.118 (strat Sharpe 0.815 vs SPY 0.856)

## [A] Isolated single-factor sleeves
                      cagr  sharpe  max_drawdown  annual_turnover
factor                                                           
momentum_12m_ex_1m  0.0198  0.7619       -0.0433           0.9364
momentum_3m         0.0163  0.6693       -0.0488           1.7522
one_month_reversal  0.0169  0.6077       -0.0837           2.7337
low_volatility      0.0146  1.1149       -0.0241           0.6118
liquidity           0.0204  0.7836       -0.0474           0.2719

(If every sleeve is positive, the edge is the FACTORS, not the blend.)

## [B] Leave-one-out marginal (vs default blend)
                    sharpe  d_sharpe  d_cagr
dropped                                     
momentum_12m_ex_1m  0.7676   -0.0476 -0.0044
momentum_3m         0.7438   -0.0715 -0.0012
one_month_reversal  0.7947   -0.0206 -0.0015
low_volatility      0.8057   -0.0095  0.0004
liquidity           0.9043    0.0890  0.0015

## [C] Sleeve return correlation (diversification)
                    momentum_12m_ex_1m  momentum_3m  one_month_reversal  low_volatility  liquidity
momentum_12m_ex_1m                1.00         0.71                0.64            0.59       0.80
momentum_3m                       0.71         1.00                0.43            0.58       0.69
one_month_reversal                0.64         0.43                1.00            0.47       0.76
low_volatility                    0.59         0.58                0.47            1.00       0.56
liquidity                         0.80         0.69                0.76            0.56       1.00

## [D] Sub-period stability (default blend)
  2010-2014: CAGR=+0.0179 vol=0.0210 Sharpe=+0.852 cum=+0.092
  2015-2019: CAGR=+0.0163 vol=0.0221 Sharpe=+0.740 cum=+0.084
  2020-2026: CAGR=+0.0271 vol=0.0314 Sharpe=+0.868 cum=+0.185

## [E] Regime-conditional (vs SPY)
                 n_days  ann_return  ann_vol  hit_rate
regime                                                
SPY up days        2279      0.2405   0.0200    0.7609
SPY down days      1827     -0.1993   0.0241    0.2135
high-vol regime    2054      0.0207   0.0309    0.5078
low-vol regime     2055      0.0213   0.0196    0.5285

## [F] Robustness battery

Walk-forward (out-of-sample folds):
 fold test_start   test_end  oos_cagr  oos_vol  oos_total_return
    0 2013-04-15 2016-07-19    0.0245   0.0225            0.0822
    1 2016-07-20 2019-10-24    0.0155   0.0212            0.0516
    2 2019-10-25 2023-02-01    0.0231   0.0340            0.0774
    3 2023-02-02 2026-05-14    0.0323   0.0277            0.1092

Cost sensitivity:
 slippage_bps   cagr  sharpe  max_drawdown  annual_turnover  total_cost
          0.0 0.0209  0.8153       -0.0448           1.5719   8964.1897
          1.0 0.0209  0.8153       -0.0448           1.5719  11936.2180
          3.0 0.0209  0.8153       -0.0448           1.5719  17856.3471
          5.0 0.0209  0.8153       -0.0449           1.5719  23744.7111
         10.0 0.0209  0.8153       -0.0449           1.5719  38327.7298

Parameter sensitivity (rebalance x top_quantile) - DISPLAY ONLY:
rebalance_frequency  top_quantile_long   cagr  sharpe  max_drawdown  annual_turnover  total_cost  avg_gross
            monthly                0.2 0.0209  0.8153       -0.0448           1.5719  14900.2635     0.1503
            monthly                0.3 0.0283  0.8417       -0.0588           1.6614  16566.0011     0.2107
            monthly                0.4 0.0322  0.8106       -0.0700           1.6640  17355.3896     0.2612
          quarterly                0.2 0.0200  0.7344       -0.0662           0.6045   5605.2042     0.1490
          quarterly                0.3 0.0249  0.6907       -0.0948           0.7023   6821.2226     0.2077
          quarterly                0.4 0.0283  0.6748       -0.1044           0.7513   7630.2958     0.2565

## [G] Null comparison
  default_sharpe: 0.8152528176166521
  equal_weight_sharpe: 0.8035306627175989
  random_mean: 0.8318788077000843
  random_min: 0.6257786061500934
  random_max: 0.9882141574322358
  random_frac_positive: 1.0
  default_percentile_in_random: 0.4166666666666667
  edge_is_robust: True

--> S02 edge: ROBUST (factor-driven, not weight-tuned)