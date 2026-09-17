"""V2.2 read-only edge diagnostics.

PURE DIAGNOSTICS. This script does not change any default, config, or strategy
logic. It builds in-memory variant configs only to *measure* edge quality and
prints a structured report + a final verdict block.

Sections
  S01: 1) trade-duration distribution  2) per-trade net PnL distribution
       3) turnover attribution by trade
  S03: 4) per-pair walk-forward net-of-cost survivor table
       5) pair stability diagnostics
  S02: 6) factor attribution (isolated sleeves)
       7) sleeve attribution (leave-one-out marginal)
       8) sub-period stability
       9) null comparison vs equal-weight and random-weight ensembles

Run:  python scripts/research_edge.py [--source cache|auto|synthetic]
"""

from __future__ import annotations

import argparse
import itertools

import numpy as np
import pandas as pd
from _common import detect_data_source

from quantbot.backtest.engine import BacktestEngine
from quantbot.backtest.performance import compute_metrics
from quantbot.config import (
    load_data_config,
    load_risk_config,
    load_strategy_config,
    strategy_params,
)
from quantbot.costs.transaction_costs import EquityCostModel
from quantbot.data.loaders import load_universe_from_config
from quantbot.indicators.pairs import (
    compute_spread,
    estimate_half_life,
    rolling_correlation,
    rolling_hedge_ratio,
    spread_zscore,
)
from quantbot.risk.risk_manager import RiskManager
from quantbot.strategies.s01_trend_following import S01TrendFollowing
from quantbot.strategies.s02_factor_blend import S02FactorBlend
from quantbot.strategies.s03_pairs_mean_reversion import generate_pair_signals
from quantbot.utils.math import TRADING_DAYS_PER_YEAR, annualize_return, annualize_vol

pd.set_option("display.width", 180)
pd.set_option("display.max_columns", 40)

SUBPERIODS = [("2010-2014", "2010-01-01", "2014-12-31"),
              ("2015-2019", "2015-01-01", "2019-12-31"),
              ("2020-2026", "2020-01-01", "2026-12-31")]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _sharpe(r: pd.Series) -> float:
    r = r.dropna()
    sd = r.std(ddof=1)
    return float(r.mean() / sd * np.sqrt(TRADING_DAYS_PER_YEAR)) if sd > 1e-18 else np.nan


def _spells(weight: pd.Series, eps: float = 1e-6) -> list[tuple[int, int]]:
    """Index ranges [i0, i1] of contiguous held (|w|>eps) spells."""
    held = (weight.abs() > eps).to_numpy()
    spells, i = [], 0
    n = len(held)
    while i < n:
        if held[i]:
            j = i
            while j + 1 < n and held[j + 1]:
                j += 1
            spells.append((i, j))
            i = j + 1
        else:
            i += 1
    return spells


# --------------------------------------------------------------------------- #
# S01 diagnostics
# --------------------------------------------------------------------------- #
def s01_diagnostics(panel, sector_map, sc):
    p = strategy_params("S01_trend_following", sc)
    eng = BacktestEngine(
        risk_manager=RiskManager(load_risk_config()),
        rebalance_band=float(p.get("rebalance_band", 0.0)),
    )
    res = eng.run(S01TrendFollowing(p, sector_map=sector_map), panel, sector_map=sector_map)
    quantities = res.quantities
    durations, net_pnls, gross_pnls = [], [], []
    for sym in quantities.columns:
        for i0, i1 in _spells(quantities[sym], eps=0.0):
            dur = i1 - i0 + 1
            # Include the actual exit bar's P&L and fees. The old four-calendar-
            # day fee window could overlap a subsequent trade and double-count.
            end = min(i1 + 1, len(quantities) - 1)
            span = slice(i0, end + 1)
            gross = float(res.gross_pnl[sym].iloc[span].sum()) / res.initial_capital
            c = float((res.trading_costs[sym] + res.borrow_costs[sym]).iloc[span].sum()) / res.initial_capital
            durations.append(dur)
            gross_pnls.append(gross)
            net_pnls.append(gross - c)

    dur = pd.Series(durations, dtype=float)
    net = pd.Series(net_pnls)
    gross = pd.Series(gross_pnls)
    n_trades = len(dur)
    years = len(quantities) / TRADING_DAYS_PER_YEAR
    ta = res.turnover_attribution()
    m = compute_metrics(res)

    print("\n" + "=" * 78)
    print("S01  TREND FOLLOWING  - edge vs churn")
    print("=" * 78)
    print(f"CAGR={m['cagr']:.4f}  Sharpe={m['sharpe']:.3f}  maxDD={m['max_drawdown']:.4f}"
          f"  cost_drag={m['cost_drag_pct_of_initial']:.4f}")

    print("\n[1] Trade-duration distribution (trading days)")
    if n_trades:
        q = dur.quantile([.1, .25, .5, .75, .9, 1.0])
        print(f"  trades={n_trades}  trades/yr={n_trades / years:.1f}  "
              f"mean={dur.mean():.1f}  median={dur.median():.0f}")
        print(f"  p10/p25/p50/p75/p90/max = "
              f"{q.iloc[0]:.0f}/{q.iloc[1]:.0f}/{q.iloc[2]:.0f}/{q.iloc[3]:.0f}/"
              f"{q.iloc[4]:.0f}/{q.iloc[5]:.0f}")
        short = float((dur < 21).mean())
        print(f"  short trades (<21d, churn proxy): {short:.1%}")

    print("\n[2] Per-trade NET PnL distribution (fraction of initial capital)")
    if n_trades:
        win = float((net > 0).mean())
        print(f"  mean={net.mean():+.5f}  median={net.median():+.5f}  "
              f"std={net.std():.5f}  hit-rate={win:.1%}")
        print(f"  best={net.max():+.4f}  worst={net.min():+.4f}  "
              f"skew={net.skew():+.2f}  sum={net.sum():+.4f}")
        print(f"  gross sum={gross.sum():+.4f}  -> cost ate "
              f"{(gross.sum() - net.sum()):.4f} of it")
        # concentration: do long trades carry the PnL?
        order = dur.sort_values().index
        tert = max(1, n_trades // 3)
        short_pnl = net.loc[order[:tert]].sum()
        long_pnl = net.loc[order[-tert:]].sum()
        print(f"  PnL from shortest 1/3 trades = {short_pnl:+.4f} ; "
              f"longest 1/3 = {long_pnl:+.4f}")

    print("\n[3] Turnover attribution by trade")
    print(f"  annual one-way turnover = {res.annual_turnover:.3f}")
    print(f"  entry={ta['annual_entry']:.2f} ({ta['entry_pct']:.0%})  "
          f"exit={ta['annual_exit']:.2f} ({ta['exit_pct']:.0%})  "
          f"resize={ta['annual_resize']:.2f} ({ta['resize_pct']:.0%})")
    verdict = (
        "EDGE-LIKE" if (n_trades and net.skew() > 0.5 and long_pnl > short_pnl
                        and net.sum() > 0) else "CHURN-DOMINATED"
    )
    print(f"  --> S01 trade-quality verdict: {verdict}")
    return {"verdict": verdict, "median_dur": float(dur.median()) if n_trades else 0.0,
            "skew": float(net.skew()) if n_trades else 0.0,
            "net_sum": float(net.sum()) if n_trades else 0.0}


# --------------------------------------------------------------------------- #
# S03 per-pair walk-forward survivor + stability
# --------------------------------------------------------------------------- #
def _pair_net_returns(a: pd.Series, b: pd.Series, p: dict, cm: EquityCostModel,
                       borrow_bps: float = 50.0, g: float = 0.5) -> pd.Series:
    """Gross-normalised dollar-neutral single-pair net-of-cost daily returns,
    using the SAME signal logic + cost model as S03 (no look-ahead)."""
    a, b = a.align(b, join="inner")
    hr = rolling_hedge_ratio(a, b, int(p["hedge_ratio_window"]))
    spread = compute_spread(a, b, hr)
    z = spread_zscore(spread, int(p["zscore_window"]))
    corr = rolling_correlation(a, b, int(p["correlation_window"]))
    sig = generate_pair_signals(
        z, float(p["entry_z"]), float(p["exit_z"]), float(p["stop_z"]),
        int(p["max_holding_days"]), corr, 0.50,
    ).astype(float)
    held = sig.shift(1).fillna(0.0)                       # enter t, earn t+1
    ra, rb = a.pct_change(), b.pct_change()
    gross = held * g * (ra - rb)                          # long A / short B at +1
    chg = sig.diff().abs().fillna(0.0)
    trade_cost = chg * (2 * g) * cm.one_way_bps() / 1e4   # two legs per change
    borrow = (held.abs() > 0).astype(float) * g * borrow_bps / 1e4 / TRADING_DAYS_PER_YEAR
    return (gross - trade_cost - borrow).fillna(0.0)


def s03_diagnostics(panel, sector_map, sc):
    p = strategy_params("S03_pairs_mean_reversion", sc)
    cm = EquityCostModel()
    syms = list(panel)
    same_sector = [
        (x, y) for x, y in itertools.combinations(sorted(syms), 2)
        if sector_map.get(x) == sector_map.get(y)
    ]
    print("\n" + "=" * 78)
    print("S03  PAIRS  - is there ANY robust ETF-pair edge?")
    print("=" * 78)
    print(f"same-sector candidate pairs (default universe): {len(same_sector)}")

    rows = []
    for x, y in same_sector:
        a = panel[x]["adjusted_close"]
        b = panel[y]["adjusted_close"]
        nr = _pair_net_returns(a, b, p, cm)
        per_win, hls, pos_windows = {}, [], 0
        for label, s, e in SUBPERIODS:
            seg = nr.loc[(nr.index >= s) & (nr.index <= e)]
            cum = float((1 + seg).prod() - 1.0)
            per_win[label] = cum
            if cum > 0:
                pos_windows += 1
            aa = a.loc[(a.index >= s) & (a.index <= e)]
            bb = b.loc[(b.index >= s) & (b.index <= e)]
            if len(aa) > 60:
                hr = rolling_hedge_ratio(aa, bb, min(252, len(aa) // 2)).iloc[-1]
                hl = estimate_half_life(compute_spread(aa, bb, hr))
            else:
                hl = np.inf
            hls.append(hl)
        hl_ok = all(2.0 <= h <= 45.0 for h in hls)
        full_cum = float((1 + nr).prod() - 1.0)
        survivor = (pos_windows == len(SUBPERIODS)) and hl_ok and full_cum > 0
        rows.append({
            "pair": f"{x}/{y}", "sector": sector_map.get(x),
            **{f"net_{k.split('-')[0]}": round(v, 4) for k, v in per_win.items()},
            "pos_windows": f"{pos_windows}/{len(SUBPERIODS)}",
            "full_net": round(full_cum, 4),
            "hl_stable": hl_ok, "SURVIVOR": survivor,
        })
    tbl = pd.DataFrame(rows).sort_values("full_net", ascending=False)
    print("\n[4] Per-pair walk-forward NET-of-cost (gross-normalised, "
          "dollar-neutral, incl. borrow)")
    print(tbl.to_string(index=False))
    n_surv = int(tbl["SURVIVOR"].sum())

    print("\n[5] Pair stability diagnostics (rolling corr / hedge-ratio drift / "
          "half-life CV)")
    st = []
    for x, y in same_sector:
        a = panel[x]["adjusted_close"]; b = panel[y]["adjusted_close"]
        a, b = a.align(b, join="inner")
        corr = rolling_correlation(a, b, int(p["correlation_window"])).dropna()
        hr = rolling_hedge_ratio(a, b, int(p["hedge_ratio_window"])).dropna()
        hl_series = []
        for s, e in [(w[1], w[2]) for w in SUBPERIODS]:
            aa = a.loc[(a.index >= s) & (a.index <= e)]
            bb = b.loc[(b.index >= s) & (b.index <= e)]
            if len(aa) > 60:
                h = rolling_hedge_ratio(aa, bb, min(252, len(aa) // 2)).iloc[-1]
                hl_series.append(estimate_half_life(compute_spread(aa, bb, h)))
        hl_arr = np.array([h for h in hl_series if np.isfinite(h)], dtype=float)
        st.append({
            "pair": f"{x}/{y}",
            "corr_mean": round(corr.mean(), 3) if len(corr) else np.nan,
            "corr_min": round(corr.min(), 3) if len(corr) else np.nan,
            "hedge_cv": round(hr.std() / abs(hr.mean()), 3) if len(hr) and hr.mean() else np.nan,
            "hl_mean": round(float(hl_arr.mean()), 1) if hl_arr.size else np.inf,
            "hl_cv": round(float(hl_arr.std() / hl_arr.mean()), 2) if hl_arr.size and hl_arr.mean() else np.nan,
        })
    print(pd.DataFrame(st).to_string(index=False))
    print(f"\n  --> S03 robust survivors (pre-registered bar): {n_surv} "
          f"of {len(same_sector)} pairs")
    return {"n_pairs": len(same_sector), "n_survivors": n_surv,
            "best_full_net": float(tbl["full_net"].max())}


# --------------------------------------------------------------------------- #
# S02 attribution / robustness / null
# --------------------------------------------------------------------------- #
FACTORS = ["momentum_12m_ex_1m", "momentum_3m", "one_month_reversal",
           "low_volatility", "liquidity"]


def _run_s02(panel, sector_map, weights: dict) -> dict:
    base = strategy_params("S02_factor_blend", load_strategy_config())
    cfg = {**base, "factor_weights_price_only": weights}
    res = BacktestEngine(risk_manager=RiskManager(load_risk_config())).run(
        S02FactorBlend(cfg, sector_map=sector_map), panel, sector_map=sector_map
    )
    m = compute_metrics(res)
    return {"cagr": m["cagr"], "sharpe": m["sharpe"],
            "maxDD": m["max_drawdown"], "turnover": m["annual_turnover"],
            "_res": res}


def s02_diagnostics(panel, sector_map, sc):
    base_w = strategy_params("S02_factor_blend", sc).get(
        "factor_weights_price_only",
        {"momentum_12m_ex_1m": .45, "momentum_3m": .20, "one_month_reversal": .20,
         "low_volatility": .10, "liquidity": .05})
    print("\n" + "=" * 78)
    print("S02  FACTOR BLEND  - does the edge survive attribution / null tests?")
    print("=" * 78)

    blend = _run_s02(panel, sector_map, base_w)
    print(f"DEFAULT blend: CAGR={blend['cagr']:.4f} Sharpe={blend['sharpe']:.3f} "
          f"maxDD={blend['maxDD']:.4f} turnover={blend['turnover']:.2f}")

    print("\n[6] Factor attribution - isolated single-factor sleeves")
    iso = {}
    for f in FACTORS:
        r = _run_s02(panel, sector_map, {f: 1.0})
        iso[f] = r
        print(f"  {f:22s} CAGR={r['cagr']:+.4f} Sharpe={r['sharpe']:+.3f} "
              f"maxDD={r['maxDD']:+.4f}")

    print("\n[7] Sleeve attribution - leave-one-out (marginal vs default blend)")
    for f in FACTORS:
        w = {k: v for k, v in base_w.items() if k != f}
        if not w:
            continue
        r = _run_s02(panel, sector_map, w)
        print(f"  drop {f:22s} -> Sharpe {r['sharpe']:+.3f} "
              f"(d {r['sharpe'] - blend['sharpe']:+.3f})  "
              f"CAGR d {r['cagr'] - blend['cagr']:+.4f}")

    print("\n[8] Sub-period stability (default blend)")
    rr = blend["_res"].returns
    for label, s, e in SUBPERIODS:
        seg = rr.loc[(rr.index >= s) & (rr.index <= e)].dropna()
        if len(seg) < 30:
            continue
        print(f"  {label}: CAGR={annualize_return(seg):+.4f} "
              f"vol={annualize_vol(seg):.4f} Sharpe={_sharpe(seg):+.3f} "
              f"cum={(1 + seg).prod() - 1:+.3f}")

    print("\n[9] Null comparison")
    eq = _run_s02(panel, sector_map, {f: 1 / len(FACTORS) for f in FACTORS})
    print(f"  equal-weight factors : Sharpe={eq['sharpe']:+.3f} "
          f"CAGR={eq['cagr']:+.4f}  (default={blend['sharpe']:+.3f})")
    rng = np.random.default_rng(12345)
    sh = []
    N = 24
    for _ in range(N):
        v = rng.random(len(FACTORS))
        r = _run_s02(panel, sector_map, dict(zip(FACTORS, v / v.sum())))
        sh.append(r["sharpe"])
    sh = np.array(sh)
    pct = float((sh < blend["sharpe"]).mean())
    print(f"  random-weight ensemble (N={N}): Sharpe mean={sh.mean():+.3f} "
          f"sd={sh.std():.3f} min={sh.min():+.3f} max={sh.max():+.3f}")
    print(f"  fraction of random < default = {pct:.0%} ; "
          f"fraction of random with Sharpe>0 = {(sh > 0).mean():.0%}")
    edge_is_factors = (sh > 0).mean() > 0.7 and eq["sharpe"] > 0.4
    print(f"  --> S02 edge source: "
          f"{'ROBUST (factors themselves, not weight-tuned)' if edge_is_factors else 'WEIGHT-SENSITIVE (suspect)'}")
    return {"default_sharpe": blend["sharpe"], "equal_sharpe": eq["sharpe"],
            "rand_pos_frac": float((sh > 0).mean()), "rand_pct": pct,
            "edge_is_factors": bool(edge_is_factors)}


def s01_binary_vs_conviction(panel, sector_map, sc):
    """V2.3 experiment: binary (default) vs opt-in conviction mode, judged on
    the V2.2 edge metrics + a confirm_days plateau check (display only)."""
    from quantbot.risk.risk_manager import RiskManager as _RM

    base = strategy_params("S01_trend_following", sc)
    rb = float(base.get("rebalance_band", 0.0))

    def run(cfg):
        eng = BacktestEngine(risk_manager=_RM(load_risk_config()), rebalance_band=rb)
        res = eng.run(S01TrendFollowing(cfg, sector_map=sector_map), panel,
                      sector_map=sector_map)
        m = compute_metrics(res)
        ta = res.turnover_attribution()
        return res, m, ta

    _, mb, tb = run(base)
    conv = {**base, "s01_execution_mode": "conviction"}
    _, mc, tc = run(conv)

    print("\n" + "=" * 78)
    print("S01  EXPERIMENT  - binary (default) vs conviction (opt-in)")
    print("=" * 78)
    hdr = f"{'metric':16s} {'BINARY':>12s} {'CONVICTION':>12s}"
    print(hdr)
    for k in ["cagr", "sharpe", "sortino", "max_drawdown",
              "max_dd_duration_days", "annual_turnover",
              "total_transaction_cost", "cost_drag_pct_of_initial"]:
        print(f"{k:16s} {mb[k]:>12.4f} {mc[k]:>12.4f}")
    be_b = tb["entry_pct"] + tb["exit_pct"]
    be_c = tc["entry_pct"] + tc["exit_pct"]
    print(f"{'binary-flip %':16s} {be_b:>12.0%} {be_c:>12.0%}  "
          "(entry+exit share of turnover; lower = fewer flips)")

    # confirm_days plateau (robustness, NOT optimisation)
    print("\n[plateau] conviction across confirm_days (display only):")
    sharpes = []
    for cd in (1, 3, 5, 8):
        cfg = {**conv, "s01_confirm_days": cd}
        _, m, _ = run(cfg)
        sharpes.append(m["sharpe"])
        print(f"  confirm_days={cd}: Sharpe={m['sharpe']:+.3f} "
              f"CAGR={m['cagr']:+.4f} maxDD={m['max_drawdown']:+.4f} "
              f"ddDur={m['max_dd_duration_days']}d turn={m['annual_turnover']:.2f}")
    sh = np.array(sharpes)
    plateau_stable = bool(sh.min() > 0 and (sh.max() - sh.min()) < 0.15)

    better = (
        mc["sharpe"] >= mb["sharpe"]
        and mc["max_dd_duration_days"] <= mb["max_dd_duration_days"]
        and mc["annual_turnover"] <= mb["annual_turnover"] + 1e-9
        and mc["cagr"] > 0
    )
    rec = ("DESERVES FURTHER RESEARCH" if (better and plateau_stable)
           else "NOT COMPELLING")
    print(f"\n  --> conviction vs binary: {rec} "
          f"(better={better}, plateau_stable={plateau_stable})")
    return {"bin_sharpe": mb["sharpe"], "conv_sharpe": mc["sharpe"],
            "bin_dd": int(mb["max_dd_duration_days"]),
            "conv_dd": int(mc["max_dd_duration_days"]),
            "plateau_stable": plateau_stable, "recommendation": rec}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="cache")
    args = ap.parse_args()
    dc = load_data_config()
    dc["source"] = args.source
    sc = load_strategy_config()

    p1, sm1 = load_universe_from_config("s01_trend", dc)
    p2, sm2 = load_universe_from_config("s02_factor", dc)
    p3, sm3 = load_universe_from_config("s03_pairs", dc)
    print(detect_data_source(p1))

    s1 = s01_diagnostics(p1, sm1, sc)
    s1c = s01_binary_vs_conviction(p1, sm1, sc)
    s3 = s03_diagnostics(p3, sm3, sc)
    s2 = s02_diagnostics(p2, sm2, sc)

    print("\n" + "#" * 78)
    print("# VERDICT (read-only diagnostics; no defaults changed)")
    print("#" * 78)
    print(f"S01: {s1['verdict']}  (median trade {s1['median_dur']:.0f}d, "
          f"net-PnL skew {s1['skew']:+.2f}, net sum {s1['net_sum']:+.4f})")
    print(f"S01 conviction experiment: {s1c['recommendation']} "
          f"(BIN Sharpe {s1c['bin_sharpe']:.3f} ddDur {s1c['bin_dd']}d -> "
          f"CONV Sharpe {s1c['conv_sharpe']:.3f} ddDur {s1c['conv_dd']}d; "
          f"plateau {'STABLE' if s1c['plateau_stable'] else 'UNSTABLE'})")
    print(f"S03: {s3['n_survivors']}/{s3['n_pairs']} pairs pass the robust "
          f"survivor bar (best full net {s3['best_full_net']:+.4f})")
    print(f"S02: edge {'ROBUST' if s2['edge_is_factors'] else 'SUSPECT'} "
          f"(default Sharpe {s2['default_sharpe']:.3f}, equal-weight "
          f"{s2['equal_sharpe']:.3f}, {s2['rand_pos_frac']:.0%} of random "
          f"weightings Sharpe>0)")


if __name__ == "__main__":
    main()
