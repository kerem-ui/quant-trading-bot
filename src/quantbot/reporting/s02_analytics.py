"""V3 S02 core-strategy analytics (READ-ONLY).

Pure reporting/analytics. Nothing here changes strategy logic, defaults, or
config. Every function returns DataFrames / dicts; formatting + file output is
done by ``scripts/report_s02_v3.py``.

Contribution convention
-----------------------
The engine computes the day-d portfolio return from the weights held at the
*start* of day d, i.e. the post-execution weights recorded on day d-1. So the
correct per-symbol daily contribution is ``weights.shift(1) * asset_returns``;
summed across symbols this reproduces ``result.returns`` (gross of cost, which
the engine deducts separately from equity).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..backtest.performance import rolling_sharpe
from ..risk.drawdown import drawdown_series, max_drawdown
from ..risk.stress import STRESS_WINDOWS
from ..utils.math import TRADING_DAYS_PER_YEAR, annualize_return, annualize_vol
from . import factor_attribution as fa
from .benchmark import buy_and_hold_returns, relative_metrics


# --------------------------------------------------------------------------- #
# shared helpers
# --------------------------------------------------------------------------- #
def aligned_asset_returns(result, panel: dict[str, pd.DataFrame],
                          field: str = "adjusted_close") -> pd.DataFrame:
    """Wide asset returns aligned to the result's weight index."""
    rets = pd.DataFrame(
        {s: df[field].pct_change() for s, df in panel.items()}
    ).reindex(result.weights.index)
    return rets[result.weights.columns.intersection(rets.columns)]


def contribution_frame(result, panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Per-symbol daily return contribution (date x symbol).

    ``c_{s,d} = w_{s,d-1} * r_{s,d}``;  ``sum_s c_{s,d} ~= result.returns``.
    """
    w = result.weights.fillna(0.0)
    rets = aligned_asset_returns(result, panel)
    cols = w.columns.intersection(rets.columns)
    contrib = (w[cols].shift(1) * rets[cols]).fillna(0.0)
    return contrib


def _years(idx: pd.Index) -> float:
    return max(len(idx) / TRADING_DAYS_PER_YEAR, 1e-9)


# --------------------------------------------------------------------------- #
# 1. ETF-level contribution analysis
# --------------------------------------------------------------------------- #
def etf_contribution(result, panel: dict[str, pd.DataFrame]) -> dict:
    """Contribution by ETF, best/worst, yearly, avg weight, turnover by ETF."""
    contrib = contribution_frame(result, panel)
    w = result.weights.fillna(0.0)[contrib.columns]
    years = _years(w.index)

    by_etf = contrib.sum().sort_values(ascending=False)
    yearly = contrib.groupby(contrib.index.year).sum().T  # rows=ETF, cols=year
    avg_weight_all = w.mean()
    held = w.where(w.abs() > 1e-9)
    avg_weight_when_held = held.mean()
    days_held = (w.abs() > 1e-9).sum()
    turnover_by_etf = (w.diff().abs().sum() / years).sort_values(ascending=False)

    summary = pd.DataFrame({
        "total_contribution": by_etf,
        "avg_weight_all_days": avg_weight_all,
        "avg_weight_when_held": avg_weight_when_held,
        "days_held": days_held,
        "pct_days_held": days_held / max(len(w), 1),
        "annual_turnover": turnover_by_etf,
    }).sort_values("total_contribution", ascending=False)

    return {
        "summary": summary,
        "by_etf": by_etf,
        "best": by_etf.head(5),
        "worst": by_etf.tail(5).sort_values(),
        "yearly_by_etf": yearly,
        "total_arithmetic_return": float(by_etf.sum()),
    }


# --------------------------------------------------------------------------- #
# 2. Factor analysis
# --------------------------------------------------------------------------- #
def _sharpe(r: pd.Series) -> float:
    r = r.dropna()
    sd = r.std(ddof=1)
    return float(r.mean() / sd * np.sqrt(TRADING_DAYS_PER_YEAR)) if sd > 1e-18 else np.nan


def factor_analysis(panel: dict[str, pd.DataFrame], sector_map: dict[str, str],
                    subperiods: list[tuple[str, str, str]],
                    n_random: int = 16) -> dict:
    """Sleeve contribution, correlation, sub-period factor stability, and a
    factor-weight sensitivity summary. Reuses the V2.3 attribution module."""
    iso, sleeve_rets = fa.isolated_sleeves(panel, sector_map)
    loo, blend = fa.leave_one_out(panel, sector_map)
    corr = fa.sleeve_return_correlation(sleeve_rets)

    # Factor stability by sub-period (Sharpe of each isolated sleeve).
    rows = []
    for f, r in sleeve_rets.items():
        row = {"factor": f}
        for label, s, e in subperiods:
            seg = r.loc[(r.index >= s) & (r.index <= e)]
            row[label] = _sharpe(seg)
        rows.append(row)
    subperiod_stability = pd.DataFrame(rows).set_index("factor")

    nc = fa.null_comparison(panel, sector_map, n_random=n_random)
    weight_sensitivity = {
        "default_sharpe": nc["default_sharpe"],
        "equal_weight_sharpe": nc["equal_weight_sharpe"],
        "random_mean": nc["random_mean"],
        "random_min": nc["random_min"],
        "random_max": nc["random_max"],
        "random_frac_positive": nc["random_frac_positive"],
        "edge_is_robust": nc["edge_is_robust"],
    }
    return {
        "sleeves": iso,
        "leave_one_out": loo,
        "blend": blend,
        "correlation": corr,
        "subperiod_stability": subperiod_stability,
        "weight_sensitivity": weight_sensitivity,
    }


# --------------------------------------------------------------------------- #
# 3. Regime analysis
# --------------------------------------------------------------------------- #
def _seg_stats(s: pd.Series, b: pd.Series | None = None) -> dict:
    s = s.dropna()
    out = {
        "n_days": int(len(s)),
        "cum_return": float((1 + s).prod() - 1.0) if len(s) else np.nan,
        "ann_return": annualize_return(s),
        "ann_vol": annualize_vol(s),
        "sharpe": _sharpe(s),
        "max_drawdown": float(max_drawdown((1 + s).cumprod())) if len(s) else np.nan,
    }
    if b is not None:
        b = b.reindex(s.index).dropna()
        if len(b):
            out["spy_cum_return"] = float((1 + b).prod() - 1.0)
    return out


def regime_analysis(result, panel: dict[str, pd.DataFrame],
                    spy_symbol: str = "SPY") -> dict:
    """S02 in bull/bear (SPY vs 200d SMA), high/low-vol, crisis windows, and
    explicit 2020 / 2022 sub-analyses."""
    r = result.returns
    spy_px = panel[spy_symbol]["adjusted_close"].reindex(r.index).ffill()
    spy_ret = spy_px.pct_change()
    sma200 = spy_px.rolling(200, min_periods=100).mean()
    # Use yesterday's regime label (no look-ahead in the conditioning).
    bull = (spy_px > sma200).shift(1).fillna(False).astype(bool)
    vol20 = spy_ret.rolling(20, min_periods=10).std()
    hi_vol = (vol20 > vol20.median()).shift(1).fillna(False).astype(bool)

    regimes = pd.DataFrame({
        "SPY bull (>200dma)": _seg_stats(r[bull], spy_ret[bull]),
        "SPY bear (<200dma)": _seg_stats(r[~bull], spy_ret[~bull]),
        "high-vol regime": _seg_stats(r[hi_vol], spy_ret[hi_vol]),
        "low-vol regime": _seg_stats(r[~hi_vol], spy_ret[~hi_vol]),
        "SPY up days": _seg_stats(r[spy_ret > 0], spy_ret[spy_ret > 0]),
        "SPY down days": _seg_stats(r[spy_ret < 0], spy_ret[spy_ret < 0]),
    }).T

    crisis_rows = {}
    for label, start, end in STRESS_WINDOWS:
        seg = r.loc[(r.index >= start) & (r.index <= end)]
        if len(seg) < 5:
            continue
        crisis_rows[f"{label} ({start}->{end})"] = _seg_stats(
            seg, spy_ret.loc[seg.index])
    crisis = pd.DataFrame(crisis_rows).T

    def _win(start, end):
        s = r.loc[(r.index >= start) & (r.index <= end)]
        return _seg_stats(s, spy_ret.loc[s.index])

    def _yr(y):
        s = r[r.index.year == y]
        return _seg_stats(s, spy_ret.loc[s.index])

    explicit = pd.DataFrame({
        "COVID 2020 (02-15..04-15)": _win("2020-02-15", "2020-04-15"),
        "Bear 2022 (01-01..10-31)": _win("2022-01-01", "2022-10-31"),
        "Full 2020": _yr(2020),
        "Full 2022": _yr(2022),
    }).T

    return {"regimes": regimes, "crisis_windows": crisis, "explicit": explicit}


# --------------------------------------------------------------------------- #
# 4. Risk analysis
# --------------------------------------------------------------------------- #
def _bucket(series: pd.Series, sector_map: dict[str, str]) -> pd.Series:
    grp = pd.Series({s: sector_map.get(s, s) for s in series.index})
    return series.groupby(grp).sum()


def risk_analysis(result, panel: dict[str, pd.DataFrame],
                  sector_map: dict[str, str], roll: int = 63) -> dict:
    """Exposure by bucket, drawdown contribution, risk contribution by
    ETF/bucket, rolling vol and rolling Sharpe."""
    w = result.weights.fillna(0.0)
    contrib = contribution_frame(result, panel)
    cols = contrib.columns
    port = contrib.sum(axis=1)

    # Exposure by bucket (mean gross weight per sector).
    sec = pd.Series({s: sector_map.get(s, s) for s in cols})
    bucket_w = w[cols].T.groupby(sec).sum().T          # date x bucket
    exposure_by_bucket = pd.DataFrame({
        "avg_gross": bucket_w.abs().mean(),
        "max_gross": bucket_w.abs().max(),
    }).sort_values("avg_gross", ascending=False)

    # Max-drawdown window and per-symbol contribution within it.
    eq = result.equity_curve
    dd = drawdown_series(eq)
    trough = dd.idxmin()
    peak = eq.loc[:trough].idxmax()
    dd_mask = (contrib.index > peak) & (contrib.index <= trough)
    dd_contrib_etf = contrib.loc[dd_mask].sum().sort_values()
    dd_contrib_bucket = _bucket(dd_contrib_etf, sector_map).sort_values()

    # Risk contribution: rc_s = cov(c_s, port)/std(port); sum_s rc_s = std(port)
    sd = port.std(ddof=1)
    if sd > 1e-18:
        rc = contrib.apply(lambda c: c.cov(port)) / sd
    else:
        rc = pd.Series(0.0, index=cols)
    rc_ann = (rc * np.sqrt(TRADING_DAYS_PER_YEAR)).sort_values(ascending=False)
    rc_frac = (rc / rc.sum()).reindex(rc_ann.index) if rc.sum() != 0 else rc_ann * np.nan
    risk_contrib_etf = pd.DataFrame({
        "ann_risk_contribution": rc_ann,
        "pct_of_total_risk": rc_frac,
    })
    risk_contrib_bucket = _bucket(rc_ann, sector_map).sort_values(ascending=False)

    rolling_vol = port.rolling(roll, min_periods=roll // 2).std() * np.sqrt(
        TRADING_DAYS_PER_YEAR)
    roll_sharpe = rolling_sharpe(result.returns, window=126)

    return {
        "exposure_by_bucket": exposure_by_bucket,
        "drawdown_window": {"peak": str(pd.Timestamp(peak).date()),
                            "trough": str(pd.Timestamp(trough).date()),
                            "depth": float(dd.min())},
        "drawdown_contribution_etf": dd_contrib_etf,
        "drawdown_contribution_bucket": dd_contrib_bucket,
        "risk_contribution_etf": risk_contrib_etf,
        "risk_contribution_bucket": risk_contrib_bucket,
        "rolling_vol": rolling_vol,
        "rolling_sharpe": roll_sharpe,
    }


# --------------------------------------------------------------------------- #
# 5. Benchmark analysis
# --------------------------------------------------------------------------- #
def equal_weight_basket_returns(panel: dict[str, pd.DataFrame],
                                field: str = "adjusted_close") -> pd.Series:
    """Daily-rebalanced equal-weight long-only basket of the ETF universe
    (a naive passive benchmark)."""
    rets = pd.DataFrame({s: df[field].pct_change() for s, df in panel.items()})
    out = rets.mean(axis=1)
    out.name = "equal_weight_basket"
    return out


def benchmark_analysis(result, panel: dict[str, pd.DataFrame],
                       extra_benchmarks: dict[str, pd.Series] | None = None,
                       spy_symbol: str = "SPY") -> dict:
    """S02 vs SPY buy-hold, an equal-weight ETF basket, and any extra
    benchmarks (e.g. SHY cash proxy). Returns a tidy relative-metrics table."""
    benches: dict[str, pd.Series] = {}
    if spy_symbol in panel:
        benches["SPY_buyhold"] = buy_and_hold_returns(panel, spy_symbol)
    benches["equal_weight_basket"] = equal_weight_basket_returns(panel)
    for name, series in (extra_benchmarks or {}).items():
        benches[name] = series

    cols = ["strat_cagr", "bench_cagr", "excess_cagr", "strat_sharpe",
            "bench_sharpe", "tracking_error", "beta_to_bench", "correlation",
            "information_ratio", "down_capture"]
    rows = {}
    for name, b in benches.items():
        m = relative_metrics(result.returns, b)
        rows[name] = {k: m.get(k) for k in cols}
    table = pd.DataFrame(rows).T[cols]
    table.index.name = "benchmark"
    return {"table": table, "benchmark_returns": benches}
