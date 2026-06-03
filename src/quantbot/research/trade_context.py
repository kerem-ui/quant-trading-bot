"""Annotate strategy trades with macro / market context (read-only).

Given a trades DataFrame (one row per closed trade with at least
``fill_open`` and ``fill_close``), enrich it with context columns drawn
from market proxies and regime labels.

Hard rules:
  - INPUT TRADE COLUMNS ARE NEVER MUTATED -- the function copies the
    frame before adding columns.
  - REALIZED P&L IS NEVER RECOMPUTED -- it is carried through verbatim.
  - Missing context (e.g. VIX series absent) leaves the corresponding
    annotation column as NaN; the trade row is never dropped.
  - No broker connection, no live data fetch, no strategy re-run.
"""

from __future__ import annotations

import pandas as pd


def _asof_value(series: pd.Series | None, when: pd.Timestamp) -> float:
    """Latest available scalar from ``series`` at or before ``when``."""
    if series is None or len(series) == 0:
        return float("nan")
    sub = series.loc[:when]
    if sub.empty:
        return float("nan")
    v = sub.iloc[-1]
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def _asof_label(series: pd.Series | None, when: pd.Timestamp) -> str:
    if series is None or len(series) == 0:
        return ""
    sub = series.loc[:when]
    if sub.empty:
        return ""
    return str(sub.iloc[-1])


def _window_return(close: pd.Series | None, start: pd.Timestamp,
                    end: pd.Timestamp) -> float:
    if close is None or len(close) == 0 or start >= end:
        return float("nan")
    sub = close.loc[start:end]
    if sub.empty or len(sub) < 2:
        return float("nan")
    return float(sub.iloc[-1] / sub.iloc[0] - 1.0)


def annotate_trades(
    trades: pd.DataFrame, *,
    spy_close: pd.Series | None = None,
    vix_level: pd.Series | None = None,
    dgs10: pd.Series | None = None,
    hyg: pd.Series | None = None,
    lqd: pd.Series | None = None,
    trend_label: pd.Series | None = None,
    vol_label: pd.Series | None = None,
    rates_label: pd.Series | None = None,
    credit_label: pd.Series | None = None,
    combined_regime: pd.Series | None = None,
    event_flags: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return a copy of ``trades`` with macro / regime annotation columns.

    Required input columns: ``fill_open``, ``fill_close``. Everything else
    is optional. If an input is ``None`` the matching column is filled with
    NaN / empty string.
    """
    if "fill_open" not in trades.columns or "fill_close" not in trades.columns:
        raise KeyError("trades must include 'fill_open' and 'fill_close' columns")

    out = trades.copy()
    # Defensive normalization
    out["fill_open"] = pd.to_datetime(out["fill_open"])
    out["fill_close"] = pd.to_datetime(out["fill_close"])

    out["holding_days"] = (out["fill_close"] - out["fill_open"]).dt.days.astype(int)
    out["spy_return_in_trade_pct"] = [
        _window_return(spy_close, s, e) * 100.0
        for s, e in zip(out["fill_open"], out["fill_close"])
    ]
    out["vix_at_entry"] = [_asof_value(vix_level, t) for t in out["fill_open"]]
    out["vix_at_exit"] = [_asof_value(vix_level, t) for t in out["fill_close"]]
    out["vix_change_in_trade"] = out["vix_at_exit"] - out["vix_at_entry"]

    out["dgs10_at_entry"] = [_asof_value(dgs10, t) for t in out["fill_open"]]
    out["dgs10_at_exit"] = [_asof_value(dgs10, t) for t in out["fill_close"]]
    out["dgs10_change_in_trade"] = out["dgs10_at_exit"] - out["dgs10_at_entry"]

    out["hyg_lqd_ratio_at_entry"] = [
        (_asof_value(hyg, t) / _asof_value(lqd, t))
        if (lqd is not None and not pd.isna(_asof_value(lqd, t))
            and _asof_value(lqd, t) != 0)
        else float("nan")
        for t in out["fill_open"]
    ]

    out["trend_at_entry"] = [_asof_label(trend_label, t) for t in out["fill_open"]]
    out["vol_at_entry"] = [_asof_label(vol_label, t) for t in out["fill_open"]]
    out["rates_at_entry"] = [_asof_label(rates_label, t) for t in out["fill_open"]]
    out["credit_at_entry"] = [_asof_label(credit_label, t) for t in out["fill_open"]]
    out["macro_regime_at_entry"] = [
        _asof_label(combined_regime, t) for t in out["fill_open"]
    ]

    # Optional event-flag overlay (DataFrame indexed by date with bool
    # columns like CPI / FOMC / earnings).
    if event_flags is not None and not event_flags.empty:
        flag_cols = list(event_flags.columns)
        for col in flag_cols:
            out[f"event_{col}_in_trade"] = [
                bool(event_flags.loc[(event_flags.index >= s)
                                      & (event_flags.index <= e), col].any())
                if col in event_flags.columns else False
                for s, e in zip(out["fill_open"], out["fill_close"])
            ]
    else:
        out["event_flags_in_trade"] = [None] * len(out)

    return out


def annotate_event_overlap(
    trades: pd.DataFrame,
    events_detailed: pd.DataFrame, *,
    fomc_types: tuple[str, ...] = ("FOMC", "FOMC_MINUTES"),
    cpi_types: tuple[str, ...] = ("CPI",),
    high_importance_values: tuple[str, ...] = ("high",),
) -> pd.DataFrame:
    """Add event-overlap context columns to a trades frame (READ-ONLY).

    ``events_detailed`` is the frame returned by
    :func:`quantbot.events.manual_events.load_events_detailed` (columns
    ``date, event_type, event_name, source, importance, note``).

    Adds (and NEVER mutates existing columns or P&L):
      - event_count_during_trade          (int)
      - cpi_event_during_trade            (bool)
      - fomc_event_during_trade           (bool; groups FOMC + FOMC_MINUTES)
      - high_importance_event_during_trade(bool)
      - events_during_trade               (str; "TYPE:event_name" joined by ';')
      - nearest_event_before_entry        (str; "YYYY-MM-DD TYPE event_name")
      - days_since_nearest_event_before_entry (float; NaN if none)

    Requires ``fill_open`` / ``fill_close`` on ``trades``. If
    ``events_detailed`` is empty, the columns are still added with neutral
    defaults (0 / False / "" / NaN) so downstream code is uniform.
    """
    if "fill_open" not in trades.columns or "fill_close" not in trades.columns:
        raise KeyError("trades must include 'fill_open' and 'fill_close' columns")

    out = trades.copy()
    out["fill_open"] = pd.to_datetime(out["fill_open"])
    out["fill_close"] = pd.to_datetime(out["fill_close"])

    if events_detailed is None or events_detailed.empty:
        out["event_count_during_trade"] = 0
        out["cpi_event_during_trade"] = False
        out["fomc_event_during_trade"] = False
        out["high_importance_event_during_trade"] = False
        out["events_during_trade"] = ""
        out["nearest_event_before_entry"] = ""
        out["days_since_nearest_event_before_entry"] = float("nan")
        return out

    ev = events_detailed.copy()
    ev["date"] = pd.to_datetime(ev["date"])
    fomc_set = {t.upper() for t in fomc_types}
    cpi_set = {t.upper() for t in cpi_types}
    high_set = {v.lower() for v in high_importance_values}

    counts, cpi_f, fomc_f, high_f, lists = [], [], [], [], []
    nearest_str, nearest_days = [], []
    for s, e in zip(out["fill_open"], out["fill_close"]):
        during = ev[(ev["date"] >= s) & (ev["date"] <= e)]
        counts.append(int(len(during)))
        types_during = set(during["event_type"].str.upper())
        cpi_f.append(bool(types_during & cpi_set))
        fomc_f.append(bool(types_during & fomc_set))
        high_f.append(bool((during["importance"].str.lower().isin(high_set)).any())
                       if not during.empty else False)
        if during.empty:
            lists.append("")
        else:
            lists.append("; ".join(
                f"{r.event_type}:{r.event_name}" if str(r.event_name)
                else str(r.event_type)
                for r in during.itertuples(index=False)
            ))
        # nearest event strictly before entry
        before = ev[ev["date"] < s]
        if before.empty:
            nearest_str.append("")
            nearest_days.append(float("nan"))
        else:
            last = before.sort_values("date").iloc[-1]
            nearest_str.append(
                f"{pd.Timestamp(last['date']).date()} {last['event_type']} "
                f"{last['event_name']}".strip()
            )
            nearest_days.append(float((s - pd.Timestamp(last["date"])).days))

    out["event_count_during_trade"] = counts
    out["cpi_event_during_trade"] = cpi_f
    out["fomc_event_during_trade"] = fomc_f
    out["high_importance_event_during_trade"] = high_f
    out["events_during_trade"] = lists
    out["nearest_event_before_entry"] = nearest_str
    out["days_since_nearest_event_before_entry"] = nearest_days
    return out


def summarize_event_overlap(annotated: pd.DataFrame) -> pd.DataFrame:
    """Per-(strategy, P&L bucket) aggregation of event-overlap columns.

    Requires the columns produced by :func:`annotate_event_overlap` plus
    ``realized_pnl`` (and optionally ``strategy``)."""
    needed = {"event_count_during_trade", "cpi_event_during_trade",
              "fomc_event_during_trade", "realized_pnl"}
    missing = needed - set(annotated.columns)
    if missing:
        raise KeyError(f"annotated missing columns: {sorted(missing)}")
    df = annotated.copy()
    df["pnl_bucket"] = df["realized_pnl"].apply(
        lambda v: "win" if v > 0 else ("loss" if v < 0 else "flat")
    )
    group_keys = (["strategy", "pnl_bucket"] if "strategy" in df.columns
                   else ["pnl_bucket"])
    rows = []
    for keys, g in df.groupby(group_keys):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = dict(zip(group_keys, keys))
        row["n_trades"] = len(g)
        row["trades_with_any_event"] = int((g["event_count_during_trade"] > 0).sum())
        row["trades_with_cpi"] = int(g["cpi_event_during_trade"].sum())
        row["trades_with_fomc"] = int(g["fomc_event_during_trade"].sum())
        if "high_importance_event_during_trade" in g.columns:
            row["trades_with_high_importance"] = int(
                g["high_importance_event_during_trade"].sum())
        row["mean_events_per_trade"] = float(g["event_count_during_trade"].mean())
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_winners_vs_losers(annotated: pd.DataFrame) -> pd.DataFrame:
    """Group annotated trades by realized P&L sign and aggregate context."""
    if "realized_pnl" not in annotated.columns:
        raise KeyError("annotated must contain 'realized_pnl'")
    df = annotated.copy()
    df["pnl_bucket"] = df["realized_pnl"].apply(
        lambda v: "win" if v > 0 else ("loss" if v < 0 else "flat")
    )
    grouping_numeric = [
        "holding_days", "spy_return_in_trade_pct",
        "vix_at_entry", "vix_at_exit", "vix_change_in_trade",
        "dgs10_at_entry", "dgs10_change_in_trade",
        "hyg_lqd_ratio_at_entry",
    ]
    grouping_numeric = [c for c in grouping_numeric if c in df.columns]
    out_rows = []
    for bucket, g in df.groupby("pnl_bucket"):
        row = {"pnl_bucket": bucket, "n_trades": len(g)}
        for c in grouping_numeric:
            row[f"{c}_mean"] = float(g[c].mean()) if g[c].notna().any() else float("nan")
            row[f"{c}_median"] = float(g[c].median()) if g[c].notna().any() else float("nan")
        # Most common labels
        for lbl_col in ("trend_at_entry", "vol_at_entry", "rates_at_entry",
                         "credit_at_entry", "macro_regime_at_entry"):
            if lbl_col in g.columns:
                modes = g[lbl_col][g[lbl_col].astype(bool)].mode()
                row[f"{lbl_col}_mode"] = (str(modes.iloc[0])
                                            if len(modes) > 0 else "")
        out_rows.append(row)
    return pd.DataFrame(out_rows)
