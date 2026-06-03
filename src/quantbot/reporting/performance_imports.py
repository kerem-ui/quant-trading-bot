"""Re-export of performance helpers used by reporting (avoids a circular
import between reporting.plots and backtest.performance)."""

from ..backtest.performance import (  # noqa: F401
    compute_metrics,
    monthly_returns_table,
    rolling_sharpe,
    yearly_returns,
)
