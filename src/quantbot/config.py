"""Configuration loading.

Loads JSON config files (strategy / data / risk). Configs are kept as plain
dicts intentionally so they round-trip to JSON for report provenance.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def project_root() -> Path:
    """Return the repository root (the directory that contains ``configs/``)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "configs").is_dir():
            return parent
    # Fallback: two levels up from src/quantbot/config.py
    return here.parents[2]


def configs_dir() -> Path:
    return project_root() / "configs"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_strategy_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load strategy_configs.json (the canonical strategy + risk config)."""
    p = Path(path) if path else configs_dir() / "strategy_configs.json"
    return _load_json(p)


def load_data_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load data_config.json, falling back to the committed example file."""
    if path:
        return _load_json(Path(path))
    cdir = configs_dir()
    real = cdir / "data_config.json"
    example = cdir / "data_config.example.json"
    return _load_json(real if real.is_file() else example)


def load_risk_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load risk config.

    Precedence: explicit path -> strategy_configs.json["risk"] -> example file.
    The strategy config's ``risk`` block is treated as authoritative because it
    is the file the specs reference directly.
    """
    if path:
        return _load_json(Path(path))
    strat = load_strategy_config()
    risk = dict(strat.get("risk", {}))
    glob = strat.get("global", {})
    # Surface a couple of global kill-switch values into the risk dict so the
    # RiskManager only needs one mapping.
    risk.setdefault(
        "max_portfolio_drawdown_kill_switch",
        glob.get("max_portfolio_drawdown_kill_switch", 0.20),
    )
    risk.setdefault(
        "max_strategy_drawdown_pause",
        glob.get("max_strategy_drawdown_pause", 0.12),
    )
    return risk


def strategy_params(strategy_key: str, strategy_config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the parameter block for one strategy, e.g. ``S01_trend_following``."""
    cfg = strategy_config or load_strategy_config()
    strategies = cfg.get("strategies", {})
    if strategy_key not in strategies:
        raise KeyError(
            f"Unknown strategy '{strategy_key}'. Available: {sorted(strategies)}"
        )
    return strategies[strategy_key]
