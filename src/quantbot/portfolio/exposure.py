"""Exposure accounting for reports and risk checks."""

from __future__ import annotations

import pandas as pd


def gross_exposure(weights: pd.Series) -> float:
    return float(weights.abs().sum())


def net_exposure(weights: pd.Series) -> float:
    return float(weights.sum())


def long_exposure(weights: pd.Series) -> float:
    return float(weights[weights > 0].sum())


def short_exposure(weights: pd.Series) -> float:
    return float(weights[weights < 0].sum())


def sector_exposure(weights: pd.Series, sector_map: dict[str, str]) -> pd.Series:
    """Net signed exposure aggregated by sector / asset class."""
    sec = pd.Series({s: sector_map.get(s, s) for s in weights.index})
    return weights.groupby(sec).sum()


def exposure_summary(weights: pd.Series, sector_map: dict[str, str] | None = None) -> dict:
    out = {
        "gross": gross_exposure(weights),
        "net": net_exposure(weights),
        "long": long_exposure(weights),
        "short": short_exposure(weights),
        "n_positions": int((weights != 0).sum()),
    }
    if sector_map:
        out["by_sector"] = sector_exposure(weights, sector_map).round(4).to_dict()
    return out
