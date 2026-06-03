"""Backtest plots (matplotlib, non-interactive Agg backend).

Figures are saved to ``reports/figures``; nothing is shown interactively so
this runs headless in scripts and tests.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt  # noqa: E402

from ..risk.drawdown import drawdown_series  # noqa: E402
from .performance_imports import rolling_sharpe  # noqa: E402


def plot_equity_curve(result, path: str | Path) -> Path:
    fig, ax = plt.subplots(figsize=(10, 4))
    result.equity_curve.plot(ax=ax, color="navy", lw=1.2)
    ax.set_title("Equity Curve")
    ax.set_ylabel("Equity")
    ax.grid(alpha=0.3)
    return _save(fig, path)


def plot_drawdown(result, path: str | Path) -> Path:
    dd = drawdown_series(result.equity_curve)
    fig, ax = plt.subplots(figsize=(10, 3))
    ax.fill_between(dd.index, dd.values, 0.0, color="firebrick", alpha=0.5)
    ax.set_title("Drawdown")
    ax.set_ylabel("Drawdown")
    ax.grid(alpha=0.3)
    return _save(fig, path)


def plot_rolling_sharpe(result, path: str | Path, window: int = 126) -> Path:
    rs = rolling_sharpe(result.returns, window)
    fig, ax = plt.subplots(figsize=(10, 3))
    rs.plot(ax=ax, color="darkgreen", lw=1.0)
    ax.axhline(0.0, color="black", lw=0.6)
    ax.set_title(f"Rolling Sharpe ({window}d)")
    ax.grid(alpha=0.3)
    return _save(fig, path)


def plot_exposure(result, path: str | Path) -> Path:
    w = result.weights.fillna(0.0)
    fig, ax = plt.subplots(figsize=(10, 3))
    w.abs().sum(axis=1).plot(ax=ax, label="gross", color="purple", lw=1.0)
    w.sum(axis=1).plot(ax=ax, label="net", color="orange", lw=1.0)
    ax.set_title("Exposure")
    ax.legend()
    ax.grid(alpha=0.3)
    return _save(fig, path)


def _save(fig, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path
