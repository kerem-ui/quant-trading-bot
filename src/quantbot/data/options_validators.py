"""Canonical options-chain validators.

Two layers:
  - ``validate_schema``  : required columns present with sane dtypes;
  - ``validate_quality`` : per-row business rules (bid/ask, spread, IV bounds,
                           Greeks, DTE).

``validate_canonical_chain`` runs both and returns a single
:class:`ValidationReport`. Loaders should validate before caching; consumers
should validate before backtesting.

Note: the older :func:`quantbot.data.validators.validate_options_chain` is
kept for back-compatibility with V1 - this module is the V4 canonical version.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .options_chain_loader import REQUIRED_COLS
from .validators import DataValidationError, ValidationReport

# Default thresholds (configurable per call).
DEFAULT_SPREAD_MAX_PCT = 0.25
DEFAULT_DTE_MAX_CAL_DAYS = 1095          # ~3 years
DEFAULT_IV_MAX = 5.0
DEFAULT_IV_MIN = 1e-4


@dataclass
class OptionsQualityThresholds:
    spread_max_pct: float = DEFAULT_SPREAD_MAX_PCT
    dte_max_calendar_days: int = DEFAULT_DTE_MAX_CAL_DAYS
    iv_min: float = DEFAULT_IV_MIN
    iv_max: float = DEFAULT_IV_MAX
    allow_zero_volume: bool = True
    allow_zero_open_interest: bool = True


def validate_schema(df: pd.DataFrame, *, raise_on_error: bool = False) -> ValidationReport:
    """Check that every REQUIRED_COLS column is present and the frame is non-empty."""
    rep = ValidationReport(symbol="<options_chain>", n_rows=len(df))
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        rep.errors.append(f"missing required columns: {missing}")
    if len(df) == 0:
        rep.errors.append("empty options chain")
    if raise_on_error:
        rep.raise_if_failed()
    return rep


def _count(mask: pd.Series) -> int:
    return int(mask.fillna(False).sum())


def validate_quality(
    df: pd.DataFrame,
    thresholds: OptionsQualityThresholds | None = None,
    *,
    raise_on_error: bool = False,
) -> ValidationReport:
    """Row-level business rules - returns the report (does not drop rows)."""
    t = thresholds or OptionsQualityThresholds()
    rep = ValidationReport(symbol="<options_chain>", n_rows=len(df))
    if len(df) == 0:
        rep.errors.append("empty options chain")
        if raise_on_error:
            rep.raise_if_failed()
        return rep

    # Bid/Ask basic.
    bad = _count(df["bid"] < 0)
    if bad:
        rep.errors.append(f"bid < 0 on {bad} rows")
    bad = _count(df["ask"] < 0)
    if bad:
        rep.errors.append(f"ask < 0 on {bad} rows")
    bad = _count(df["bid"] > df["ask"])
    if bad:
        rep.errors.append(f"bid > ask on {bad} rows")

    # Spread (relative to mid).
    mid = df["mid"].where(df["mid"] > 0)
    spread_pct = ((df["ask"] - df["bid"]) / mid).abs()
    wide = _count(spread_pct > t.spread_max_pct)
    if wide:
        rep.warnings.append(
            f"{wide} rows with spread > {t.spread_max_pct:.0%} of mid")

    # DTE.
    bad = _count(df["dte"] < 0)
    if bad:
        rep.errors.append(f"dte < 0 on {bad} rows")
    bad = _count(df["dte"] > t.dte_max_calendar_days)
    if bad:
        rep.warnings.append(
            f"{bad} rows with dte > {t.dte_max_calendar_days}d")

    # Missing critical fields.
    if df["strike"].isna().any():
        rep.errors.append(f"missing strike on {df['strike'].isna().sum()} rows")
    if df["expiration"].isna().any():
        rep.errors.append(
            f"missing expiration on {df['expiration'].isna().sum()} rows")

    # IV bounds (rows with NaN IV are warnings, not errors - some providers
    # split IV/Greeks into separate endpoints).
    iv = df["implied_volatility"]
    bad = _count(iv <= 0) + _count(iv > t.iv_max)
    if bad:
        rep.errors.append(
            f"implied_volatility out of ({t.iv_min}, {t.iv_max}] on {bad} rows")
    if iv.isna().any():
        rep.warnings.append(f"missing implied_volatility on {iv.isna().sum()} rows")

    # Greeks finite when present.
    for col in ("delta", "gamma", "theta", "vega"):
        s = df[col]
        bad_inf = _count(np.isinf(s.fillna(0.0)))
        if bad_inf:
            rep.errors.append(f"{col} infinite on {bad_inf} rows")
    bad = _count(df["delta"].abs() > 1.0 + 1e-6)
    if bad:
        rep.errors.append(f"|delta| > 1 on {bad} rows")

    # Volume / OI.
    bad = _count(df["volume"] < 0)
    if bad:
        rep.errors.append(f"negative volume on {bad} rows")
    bad = _count(df["open_interest"] < 0)
    if bad:
        rep.errors.append(f"negative open_interest on {bad} rows")
    if not t.allow_zero_volume:
        z = _count(df["volume"] == 0)
        if z:
            rep.warnings.append(f"{z} rows with zero volume")

    # option_type domain.
    if "option_type" in df.columns:
        bad_types = df["option_type"].dropna().str.lower().isin(
            ["call", "put"]).eq(False).sum()
        if bad_types:
            rep.errors.append(
                f"option_type not in (call, put) on {int(bad_types)} rows")

    if raise_on_error:
        rep.raise_if_failed()
    return rep


def validate_canonical_chain(
    df: pd.DataFrame,
    thresholds: OptionsQualityThresholds | None = None,
    *,
    raise_on_error: bool = False,
) -> ValidationReport:
    """Schema + quality in one call. Errors are merged."""
    schema = validate_schema(df, raise_on_error=False)
    if not schema.ok:
        if raise_on_error:
            schema.raise_if_failed()
        return schema
    return validate_quality(df, thresholds, raise_on_error=raise_on_error)


def rejection_reasons(
    df: pd.DataFrame,
    thresholds: OptionsQualityThresholds | None = None,
) -> pd.DataFrame:
    """Per-row reject flags (one column per rule).  Useful for the V4 quality
    report. Returns a boolean DataFrame aligned to ``df.index``."""
    t = thresholds or OptionsQualityThresholds()
    mid = df["mid"].where(df["mid"] > 0)
    iv = df["implied_volatility"]
    out = pd.DataFrame({
        "bid_negative": df["bid"] < 0,
        "ask_negative": df["ask"] < 0,
        "bid_gt_ask": df["bid"] > df["ask"],
        "spread_too_wide": ((df["ask"] - df["bid"]) / mid).abs() > t.spread_max_pct,
        "dte_negative": df["dte"] < 0,
        "dte_too_large": df["dte"] > t.dte_max_calendar_days,
        "iv_out_of_range": (iv <= t.iv_min) | (iv > t.iv_max),
        "delta_out_of_range": df["delta"].abs() > 1.0 + 1e-6,
        "volume_negative": df["volume"] < 0,
        "open_interest_negative": df["open_interest"] < 0,
        "missing_strike": df["strike"].isna(),
        "missing_expiration": df["expiration"].isna(),
    }).fillna(False)
    out["any_reject"] = out.any(axis=1)
    return out


__all__ = [
    "DEFAULT_SPREAD_MAX_PCT", "DEFAULT_DTE_MAX_CAL_DAYS",
    "DEFAULT_IV_MIN", "DEFAULT_IV_MAX",
    "OptionsQualityThresholds", "ValidationReport", "DataValidationError",
    "validate_schema", "validate_quality", "validate_canonical_chain",
    "rejection_reasons",
]
