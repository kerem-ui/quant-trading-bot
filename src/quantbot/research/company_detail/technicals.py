"""V7.5.1 — Deterministic technical indicators (research context only).

Computes a small, pre-declared set of indicators from a local
:class:`PriceSeries`. All periods are fixed (RSI 14 / SMA 50 / SMA 200);
there is no parameter optimisation and no overbought/oversold trading
label. The output is **context only** — the V7.4 PortTech and V7.7
Protection labels are not affected.

If there is insufficient price history to compute a given indicator, the
corresponding field is the string ``"n/a"`` (mirrors the V7.1 Portfolio
totals pattern). The Company Detail page renders these strings verbatim.

No I/O, no network. ``quantbot.LIVE_TRADING_ENABLED`` stays ``False``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .price_cache import PriceSeries

# --------------------------------------------------------------------------- #
# Pre-declared indicator periods
# --------------------------------------------------------------------------- #
RSI_PERIOD: int = 14
SMA_SHORT_PERIOD: int = 50
SMA_LONG_PERIOD: int = 200

# Look-back windows for returns (in trading days).
RETURN_1W_DAYS: int = 5
RETURN_1M_DAYS: int = 21
RETURN_3M_DAYS: int = 63
RETURN_1Y_DAYS: int = 252

# Drawdown look-back. Falls back to whatever history is available.
DRAWDOWN_LOOKBACK: int = 252


TECHNICAL_SNAPSHOT_FIELDS: tuple[str, ...] = (
    "ticker",
    "cache_path",
    "latest_date",
    "latest_close",
    "return_1w",
    "return_1m",
    "return_3m",
    "return_1y",
    "rsi_14",
    "sma_50",
    "sma_200",
    "distance_to_sma_50_pct",
    "distance_to_sma_200_pct",
    "drawdown_from_1y_high_pct",
    "data_gap_note",
)


@dataclass(frozen=True)
class TechnicalSnapshot:
    """Compact technicals summary used by the Company Detail page.

    Every numeric-looking field is a *string* (formatted ``"%.2f"`` for
    indicators, ``"%.2f%%"`` for returns/distances, or the literal
    ``"n/a"`` when the cache lacks enough rows). The renderer never
    re-parses these.
    """

    ticker: str
    cache_path: str = ""
    latest_date: str = ""
    latest_close: str = "n/a"
    return_1w: str = "n/a"
    return_1m: str = "n/a"
    return_3m: str = "n/a"
    return_1y: str = "n/a"
    rsi_14: str = "n/a"
    sma_50: str = "n/a"
    sma_200: str = "n/a"
    distance_to_sma_50_pct: str = "n/a"
    distance_to_sma_200_pct: str = "n/a"
    drawdown_from_1y_high_pct: str = "n/a"
    data_gap_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Pure indicator helpers — testable in isolation.
# --------------------------------------------------------------------------- #
def compute_rsi(
    closes: list[float], period: int = RSI_PERIOD,
) -> float | None:
    """Wilder's smoothed RSI. ``None`` if fewer than ``period + 1`` rows.

    The function uses Wilder's classical recurrence:
    ``avg_gain_new = (avg_gain_old * (period - 1) + gain) / period``.
    Returns 100 if the loss accumulator collapses to zero (the standard
    interpretation when every move was up).
    """
    if period <= 0:
        raise ValueError(f"RSI period must be positive, got {period!r}")
    if len(closes) <= period:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(diff if diff > 0 else 0.0)
        losses.append(-diff if diff < 0 else 0.0)
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def compute_sma(
    closes: list[float], period: int,
) -> float | None:
    """Simple moving average over the last ``period`` rows.

    ``None`` if the series has fewer than ``period`` rows.
    """
    if period <= 0:
        raise ValueError(f"SMA period must be positive, got {period!r}")
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def compute_return_pct(
    closes: list[float], n_days_back: int,
) -> float | None:
    """Percent return from ``n_days_back`` rows ago to the latest close.

    ``None`` if the series has ``n_days_back`` or fewer rows (so the
    look-back close is unavailable).
    """
    if n_days_back <= 0:
        raise ValueError(
            f"return look-back must be positive, got {n_days_back!r}"
        )
    if len(closes) <= n_days_back:
        return None
    prior = closes[-1 - n_days_back]
    if prior == 0:
        return None
    return ((closes[-1] - prior) / prior) * 100.0


def compute_drawdown_from_high_pct(
    closes: list[float],
    lookback: int = DRAWDOWN_LOOKBACK,
) -> float | None:
    """Percent drawdown from the rolling-``lookback`` high to the latest.

    Uses up to ``lookback`` rows; falls back to whatever history is
    available when shorter. ``None`` if the series is empty.
    """
    if not closes:
        return None
    if lookback <= 0:
        raise ValueError(f"lookback must be positive, got {lookback!r}")
    window = closes[-lookback:] if len(closes) >= lookback else closes
    peak = max(window)
    if peak <= 0:
        return None
    return ((closes[-1] - peak) / peak) * 100.0


def compute_distance_to_sma_pct(
    latest_close: float | None, sma: float | None,
) -> float | None:
    """Percent distance of ``latest_close`` from ``sma`` (positive =
    above the moving average)."""
    if latest_close is None or sma is None or sma == 0:
        return None
    return ((latest_close - sma) / sma) * 100.0


def _fmt_indicator(v: float | None, ndigits: int = 2) -> str:
    if v is None:
        return "n/a"
    return f"{v:.{ndigits}f}"


def _fmt_pct(v: float | None, ndigits: int = 2) -> str:
    if v is None:
        return "n/a"
    return f"{v:+.{ndigits}f}%"


def _fmt_drawdown(v: float | None) -> str:
    # Drawdown is always ≤ 0; format with explicit sign and "%"
    if v is None:
        return "n/a"
    return f"{v:.2f}%"


# --------------------------------------------------------------------------- #
# Composition entry point
# --------------------------------------------------------------------------- #
def compute_technical_snapshot(
    series: PriceSeries | None,
    *,
    ticker: str = "",
    cache_path: str = "",
) -> TechnicalSnapshot:
    """Compose a :class:`TechnicalSnapshot` from a :class:`PriceSeries`.

    Pure. ``None`` series → an empty snapshot whose ``data_gap_note``
    explains that no cache was found.
    """
    if series is None or series.n_rows == 0:
        return TechnicalSnapshot(
            ticker=ticker,
            cache_path=cache_path,
            data_gap_note=(
                "Price cache not available. No live fetch performed."
            ),
        )

    closes = list(series.closes)
    latest_close = series.latest_close
    sma_short = compute_sma(closes, SMA_SHORT_PERIOD)
    sma_long = compute_sma(closes, SMA_LONG_PERIOD)

    # Collect per-indicator gaps so the operator knows what wasn't computable.
    gaps: list[str] = []
    if len(closes) <= RSI_PERIOD:
        gaps.append(
            f"RSI({RSI_PERIOD}) needs >{RSI_PERIOD} rows; "
            f"cache has {len(closes)}"
        )
    if len(closes) < SMA_SHORT_PERIOD:
        gaps.append(
            f"SMA({SMA_SHORT_PERIOD}) needs ≥{SMA_SHORT_PERIOD} rows; "
            f"cache has {len(closes)}"
        )
    if len(closes) < SMA_LONG_PERIOD:
        gaps.append(
            f"SMA({SMA_LONG_PERIOD}) needs ≥{SMA_LONG_PERIOD} rows; "
            f"cache has {len(closes)}"
        )
    if len(closes) <= RETURN_1Y_DAYS:
        gaps.append(
            f"1Y return needs >{RETURN_1Y_DAYS} rows; "
            f"cache has {len(closes)}"
        )

    return TechnicalSnapshot(
        ticker=ticker or series.ticker,
        cache_path=cache_path or series.cache_path,
        latest_date=series.latest_date,
        latest_close=_fmt_indicator(latest_close),
        return_1w=_fmt_pct(compute_return_pct(closes, RETURN_1W_DAYS)),
        return_1m=_fmt_pct(compute_return_pct(closes, RETURN_1M_DAYS)),
        return_3m=_fmt_pct(compute_return_pct(closes, RETURN_3M_DAYS)),
        return_1y=_fmt_pct(compute_return_pct(closes, RETURN_1Y_DAYS)),
        rsi_14=_fmt_indicator(compute_rsi(closes)),
        sma_50=_fmt_indicator(sma_short),
        sma_200=_fmt_indicator(sma_long),
        distance_to_sma_50_pct=_fmt_pct(
            compute_distance_to_sma_pct(latest_close, sma_short),
        ),
        distance_to_sma_200_pct=_fmt_pct(
            compute_distance_to_sma_pct(latest_close, sma_long),
        ),
        drawdown_from_1y_high_pct=_fmt_drawdown(
            compute_drawdown_from_high_pct(closes),
        ),
        data_gap_note=" ; ".join(gaps),
    )


__all__ = [
    # constants
    "RSI_PERIOD", "SMA_SHORT_PERIOD", "SMA_LONG_PERIOD",
    "RETURN_1W_DAYS", "RETURN_1M_DAYS", "RETURN_3M_DAYS",
    "RETURN_1Y_DAYS", "DRAWDOWN_LOOKBACK",
    "TECHNICAL_SNAPSHOT_FIELDS",
    # schema
    "TechnicalSnapshot",
    # indicators
    "compute_rsi", "compute_sma", "compute_return_pct",
    "compute_drawdown_from_high_pct", "compute_distance_to_sma_pct",
    # composition
    "compute_technical_snapshot",
]
