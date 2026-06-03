"""V5.8 options research feature layer (read-only, causal).

Pure functions that turn the canonical processed options chain (+ the
underlying spot already embedded in it) into reusable research features:
realized vol, IV-surface summaries, causal IV rank/percentile, IV-vs-RV,
skew, term structure, and liquidity diagnostics.

Design rules
------------
- **No look-ahead.** Every rolling feature for date ``t`` uses only data
  with date <= ``t`` (pandas ``.rolling`` windows look backward).
- **No mutation.** Inputs are never modified; functions return new frames.
- **Missing data is graceful.** Deep-ITM/OTM IV is often NaN; functions
  return NaN for a feature rather than raising.
- **Not a trading signal.** These are descriptive features only. Nothing
  here feeds a strategy decision. ``quantbot.LIVE_TRADING_ENABLED`` stays
  ``False``.
- **No new data, no broker.** Operates on whatever DataFrame the caller
  supplies (loaded from the local processed cache).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


# =========================================================================== #
# 1. Realized volatility / underlying features
# =========================================================================== #
def underlying_series_from_chain(chain: pd.DataFrame) -> pd.Series:
    """One ``underlying_price`` per date (first row per date), date-indexed.

    The processed chain repeats ``underlying_price`` on every row of a given
    date; we collapse to a single causal spot series. No stock fetch.
    """
    if "date" not in chain.columns or "underlying_price" not in chain.columns:
        raise KeyError("chain must have 'date' and 'underlying_price'")
    s = (chain.dropna(subset=["underlying_price"])
              .groupby("date")["underlying_price"].first()
              .sort_index())
    s.index = pd.to_datetime(s.index)
    return s.rename("underlying_price")


def realized_vol_features(spot: pd.Series,
                           windows: tuple[int, ...] = (5, 21, 63),
                           ) -> pd.DataFrame:
    """Daily realized-vol + trailing-return features from a spot series.

    Causal: each row uses only past/current closes. RV uses log returns and
    is annualized by sqrt(252).
    """
    spot = spot.sort_index().astype(float)
    logret = np.log(spot / spot.shift(1))
    out = pd.DataFrame(index=spot.index)
    out["underlying_price"] = spot
    out["log_return_1d"] = logret
    for w in windows:
        rv = logret.rolling(w, min_periods=max(2, w // 2)).std(ddof=1) \
                   * np.sqrt(TRADING_DAYS_PER_YEAR)
        out[f"rv_{w}d_annualized"] = rv
        out[f"ret_{w}d"] = spot.pct_change(w)
    # simple, transparent trend flag (21d return sign)
    if "ret_21d" in out.columns:
        out["trend_up_21d"] = out["ret_21d"] > 0
    out.index.name = "date"
    return out


# =========================================================================== #
# 2. IV surface summary (per date)
# =========================================================================== #
def _select_expiration_near(chain_today: pd.DataFrame, target_dte: int,
                             dte_band: tuple[int, int]) -> pd.Timestamp | None:
    """Expiration whose DTE is closest to target within [lo,hi]; fallback to
    the globally-closest expiration if none is in band. None if empty."""
    if chain_today.empty:
        return None
    lo, hi = dte_band
    grp = chain_today.groupby("expiration")["dte"].first()
    in_band = grp[(grp >= lo) & (grp <= hi)]
    pool = in_band if not in_band.empty else grp
    chosen = pool.iloc[(pool - target_dte).abs().argsort()].index[0]
    return pd.Timestamp(chosen)


def _iv_at_delta(sub: pd.DataFrame, option_type: str,
                 target_delta: float,
                 max_delta_dist: float | None = None) -> float:
    """IV of the row whose signed delta is closest to ``target_delta`` for
    the given option_type (drops NaN IV/delta). NaN if none.

    If ``max_delta_dist`` is given, the nearest available delta must be
    within that distance of the target, otherwise NaN is returned. This
    prevents mislabeling (e.g. reporting ATM IV as a '25-delta IV' when no
    option near 0.25 delta exists)."""
    s = sub[(sub["option_type"].str.lower() == option_type.lower())]
    s = s.dropna(subset=["delta", "implied_volatility"])
    if s.empty:
        return float("nan")
    dist = (s["delta"] - target_delta).abs()
    idx = dist.idxmin()
    if max_delta_dist is not None and float(dist.loc[idx]) > max_delta_dist:
        return float("nan")
    return float(s.loc[idx, "implied_volatility"])


def _atm_iv(sub: pd.DataFrame) -> float:
    """ATM IV = mean of (call IV nearest delta +0.50, put IV nearest -0.50),
    dropping NaN. NaN if neither available."""
    c = _iv_at_delta(sub, "call", 0.50)
    p = _iv_at_delta(sub, "put", -0.50)
    vals = [v for v in (c, p) if not (v is None or np.isnan(v))]
    return float(np.mean(vals)) if vals else float("nan")


def iv_summary_for_date(chain_today: pd.DataFrame, *,
                        target_dte: int = 30,
                        dte_band: tuple[int, int] = (25, 45)) -> dict:
    """Per-date IV-surface summary computed from the in-band expiration
    closest to ``target_dte``. Returns a dict (one row)."""
    date = (pd.Timestamp(chain_today["date"].iloc[0])
            if not chain_today.empty else pd.NaT)
    row = {
        "date": date, "iv_expiration": pd.NaT, "iv_dte": np.nan,
        "atm_iv": np.nan,
        "iv_25d_call": np.nan, "iv_25d_put": np.nan,
        "iv_30d_call": np.nan, "iv_30d_put": np.nan,
        "median_iv_calls": np.nan, "median_iv_puts": np.nan,
        "median_iv_all": np.nan, "iv_coverage": np.nan,
        "n_contracts": int(len(chain_today)),
    }
    if chain_today.empty:
        return row
    row["iv_coverage"] = float(chain_today["implied_volatility"].notna().mean())
    row["median_iv_calls"] = float(
        chain_today.loc[chain_today["option_type"].str.lower() == "call",
                        "implied_volatility"].median())
    row["median_iv_puts"] = float(
        chain_today.loc[chain_today["option_type"].str.lower() == "put",
                        "implied_volatility"].median())
    row["median_iv_all"] = float(chain_today["implied_volatility"].median())

    exp = _select_expiration_near(chain_today, target_dte, dte_band)
    if exp is None:
        return row
    sub = chain_today[chain_today["expiration"] == exp]
    row["iv_expiration"] = exp
    row["iv_dte"] = int(sub["dte"].iloc[0])
    # ATM uses nearest-to-0.50 (no tolerance); wings require an option
    # actually near the target delta (tolerance 0.10) to avoid mislabeling.
    row["atm_iv"] = _atm_iv(sub)
    row["iv_25d_call"] = _iv_at_delta(sub, "call", 0.25, max_delta_dist=0.10)
    row["iv_25d_put"] = _iv_at_delta(sub, "put", -0.25, max_delta_dist=0.10)
    row["iv_30d_call"] = _iv_at_delta(sub, "call", 0.30, max_delta_dist=0.10)
    row["iv_30d_put"] = _iv_at_delta(sub, "put", -0.30, max_delta_dist=0.10)
    return row


def iv_summary_panel(chain: pd.DataFrame, *,
                     target_dte: int = 30,
                     dte_band: tuple[int, int] = (25, 45)) -> pd.DataFrame:
    rows = [iv_summary_for_date(chain[chain["date"] == d],
                                 target_dte=target_dte, dte_band=dte_band)
            for d in sorted(chain["date"].unique())]
    out = pd.DataFrame(rows)
    out["date"] = pd.to_datetime(out["date"])
    return out.sort_values("date").reset_index(drop=True)


# =========================================================================== #
# 3. IV percentile / IV rank (causal rolling)
# =========================================================================== #
def iv_rank_features(iv_series: pd.Series,
                     windows: tuple[int, ...] = (63, 126),
                     min_periods: int | None = None) -> pd.DataFrame:
    """Causal rolling IV percentile + IV rank.

    For each date t and window W (looking BACK, inclusive of t):
      iv_percentile = fraction of the W values <= the value at t
      iv_rank       = (iv_t - min_W) / (max_W - min_W)
    Dates with fewer than ``min_periods`` observations -> NaN +
    insufficient_history flag.
    """
    iv = iv_series.sort_index().astype(float)
    out = pd.DataFrame(index=iv.index)
    out["atm_iv"] = iv
    for w in windows:
        mp = min_periods if min_periods is not None else max(20, w // 3)

        def _pctile(window_vals: np.ndarray) -> float:
            cur = window_vals[-1]
            valid = window_vals[~np.isnan(window_vals)]
            if np.isnan(cur) or len(valid) < mp:
                return np.nan
            return float((valid <= cur).mean())

        def _rank(window_vals: np.ndarray) -> float:
            cur = window_vals[-1]
            valid = window_vals[~np.isnan(window_vals)]
            if np.isnan(cur) or len(valid) < mp:
                return np.nan
            lo, hi = valid.min(), valid.max()
            if hi == lo:
                return np.nan
            return float((cur - lo) / (hi - lo))

        out[f"iv_percentile_{w}d"] = iv.rolling(w, min_periods=1).apply(
            _pctile, raw=True)
        out[f"iv_rank_{w}d"] = iv.rolling(w, min_periods=1).apply(
            _rank, raw=True)
        out[f"insufficient_history_{w}d"] = (
            iv.notna().rolling(w, min_periods=1).sum() < mp)
    out.index.name = "date"
    return out


# =========================================================================== #
# 4. IV vs RV features
# =========================================================================== #
def iv_rv_features(iv_summary: pd.DataFrame,
                   rv_features: pd.DataFrame) -> pd.DataFrame:
    """Merge ATM IV with realized vol and compute IV-RV spreads/ratios.

    ATM IV is a fraction (e.g. 0.20); RV from realized_vol_features is also
    annualized fraction -> directly comparable.
    """
    iv = iv_summary[["date", "atm_iv"]].copy()
    iv["date"] = pd.to_datetime(iv["date"])
    rv = rv_features.reset_index()[["date", "rv_21d_annualized",
                                     "rv_63d_annualized"]].copy()
    rv["date"] = pd.to_datetime(rv["date"])
    out = iv.merge(rv, on="date", how="left")
    out["iv_minus_rv21"] = out["atm_iv"] - out["rv_21d_annualized"]
    out["iv_minus_rv63"] = out["atm_iv"] - out["rv_63d_annualized"]
    out["iv_over_rv21"] = out["atm_iv"] / out["rv_21d_annualized"].replace(0, np.nan)
    out["high_iv_vs_rv"] = out["iv_minus_rv21"] > 0
    return out


# =========================================================================== #
# 5. Skew features
# =========================================================================== #
def skew_features(iv_summary: pd.DataFrame) -> pd.DataFrame:
    """Per-date skew from the IV summary. Uses 25-delta; falls back to
    30-delta when a 25-delta wing IV is missing (documented in
    ``skew_delta_basis``)."""
    df = iv_summary.copy()
    df["date"] = pd.to_datetime(df["date"])
    rows = []
    for _, r in df.iterrows():
        atm = r["atm_iv"]
        c25, p25 = r["iv_25d_call"], r["iv_25d_put"]
        c30, p30 = r["iv_30d_call"], r["iv_30d_put"]
        # choose 25d basis if both wings present, else 30d
        if not (pd.isna(c25) or pd.isna(p25)):
            cw, pw, basis = c25, p25, "25d"
        elif not (pd.isna(c30) or pd.isna(p30)):
            cw, pw, basis = c30, p30, "30d"
        else:
            cw, pw, basis = (c25 if not pd.isna(c25) else c30), \
                            (p25 if not pd.isna(p25) else p30), "mixed"
        rows.append({
            "date": r["date"],
            "atm_iv": atm,
            "skew_delta_basis": basis,
            "put_skew": (pw - atm) if not (pd.isna(pw) or pd.isna(atm)) else np.nan,
            "call_skew": (cw - atm) if not (pd.isna(cw) or pd.isna(atm)) else np.nan,
            "put_call_skew": (pw - cw) if not (pd.isna(pw) or pd.isna(cw)) else np.nan,
        })
    return pd.DataFrame(rows)


# =========================================================================== #
# 6. Term structure features
# =========================================================================== #
def term_structure_for_date(chain_today: pd.DataFrame, *,
                            near: tuple[int, int] = (7, 14),
                            mid: tuple[int, int] = (21, 30),
                            far: tuple[int, int] = (30, 45)) -> dict:
    """ATM IV at near / mid / far DTE buckets + slope and ratio.

    ATM IV per bucket = mean of (call nearest +0.50, put nearest -0.50)
    using the bucket's expiration closest to the bucket midpoint.
    """
    date = (pd.Timestamp(chain_today["date"].iloc[0])
            if not chain_today.empty else pd.NaT)
    out = {"date": date, "atm_iv_near": np.nan, "atm_iv_mid": np.nan,
           "atm_iv_far": np.nan, "near_dte": np.nan, "mid_dte": np.nan,
           "far_dte": np.nan, "ts_slope": np.nan, "ts_ratio": np.nan}
    if chain_today.empty:
        return out
    for name, band in (("near", near), ("mid", mid), ("far", far)):
        target = (band[0] + band[1]) // 2
        exp = _select_expiration_near(chain_today, target, band)
        if exp is None:
            continue
        sub = chain_today[chain_today["expiration"] == exp]
        # only accept if the chosen expiration's DTE is actually inside band
        dte = int(sub["dte"].iloc[0])
        if not (band[0] <= dte <= band[1]):
            continue
        out[f"atm_iv_{name}"] = _atm_iv(sub)
        out[f"{name}_dte"] = dte
    near_iv, far_iv = out["atm_iv_near"], out["atm_iv_far"]
    if not (pd.isna(near_iv) or pd.isna(far_iv)):
        out["ts_slope"] = far_iv - near_iv
        out["ts_ratio"] = far_iv / near_iv if near_iv != 0 else np.nan
    return out


def term_structure_panel(chain: pd.DataFrame, **kw) -> pd.DataFrame:
    rows = [term_structure_for_date(chain[chain["date"] == d], **kw)
            for d in sorted(chain["date"].unique())]
    out = pd.DataFrame(rows)
    out["date"] = pd.to_datetime(out["date"])
    return out.sort_values("date").reset_index(drop=True)


# =========================================================================== #
# 7. Liquidity / cost features
# =========================================================================== #
def _spread_pct(df: pd.DataFrame) -> pd.Series:
    mid = (df["bid"] + df["ask"]) / 2.0
    sp = (df["ask"] - df["bid"]) / mid.where(mid > 0)
    return sp.replace([np.inf, -np.inf], np.nan)


def liquidity_features_for_date(chain_today: pd.DataFrame, *,
                                spread_max_pct: float = 0.25) -> dict:
    date = (pd.Timestamp(chain_today["date"].iloc[0])
            if not chain_today.empty else pd.NaT)
    out = {
        "date": date, "n_contracts": int(len(chain_today)),
        "median_spread_pct": np.nan, "p75_spread_pct": np.nan,
        "share_zero_bid": np.nan, "share_zero_volume": np.nan,
        "share_spread_gt_25pct": np.nan, "usable_contracts": 0,
        "total_volume": 0, "open_interest_missing": True,
    }
    if chain_today.empty:
        return out
    sp = _spread_pct(chain_today)
    out["median_spread_pct"] = float(sp.median())
    out["p75_spread_pct"] = float(sp.quantile(0.75))
    out["share_zero_bid"] = float((chain_today["bid"] <= 0).mean())
    out["share_zero_volume"] = float((chain_today["volume"] == 0).mean())
    out["share_spread_gt_25pct"] = float((sp > spread_max_pct).mean())
    usable = chain_today[(chain_today["bid"] > 0) & (sp <= spread_max_pct)]
    out["usable_contracts"] = int(len(usable))
    out["total_volume"] = int(chain_today["volume"].fillna(0).sum())
    oi = chain_today.get("open_interest")
    out["open_interest_missing"] = bool(oi is None or (oi.fillna(0) == 0).all())
    return out


def liquidity_panel(chain: pd.DataFrame, **kw) -> pd.DataFrame:
    rows = [liquidity_features_for_date(chain[chain["date"] == d], **kw)
            for d in sorted(chain["date"].unique())]
    out = pd.DataFrame(rows)
    out["date"] = pd.to_datetime(out["date"])
    return out.sort_values("date").reset_index(drop=True)


# =========================================================================== #
# 10. Causality / no-lookahead checks
# =========================================================================== #
def assert_causal_panel(df: pd.DataFrame, date_col: str = "date") -> None:
    """Assert the feature panel's dates are strictly monotonically increasing
    (a necessary condition for the causal-rolling guarantee)."""
    d = pd.to_datetime(df[date_col])
    if not d.is_monotonic_increasing:
        raise AssertionError("feature panel dates are not monotonically increasing")
    if d.duplicated().any():
        raise AssertionError("feature panel has duplicate dates")
