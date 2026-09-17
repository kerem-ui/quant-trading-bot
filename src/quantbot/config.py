"""Configuration loading.

Loads JSON config files (strategy / data / risk). Configs are kept as plain
dicts intentionally so they round-trip to JSON for report provenance.
"""

from __future__ import annotations

import json
from math import isfinite
from pathlib import Path
from typing import Any


GLOBAL_FIELDS = set("mode allow_live_trading base_currency default_execution cost_filter_multiplier max_portfolio_drawdown_kill_switch max_strategy_drawdown_pause default_commission_bps default_slippage_bps".split())
RISK_FIELDS = set("portfolio_vol_target_annual max_gross_exposure max_net_exposure max_single_symbol_weight max_asset_class_weight max_daily_loss_reduce_risk risk_reduction_factor_on_daily_loss max_portfolio_drawdown_kill_switch max_strategy_drawdown_pause vol_spike_kill_multiple vol_spike_lookback allow_leverage_up max_vol_scale max_total_options_defined_loss max_defined_loss_per_options_trade".split())
STRATEGY_FIELDS = {
    "S01_trend_following": set("rebalance_frequency lookbacks trend_entry_threshold trend_exit_threshold vol_window atr_window trailing_stop_atr_multiple target_vol_annual max_weight_per_symbol long_short cost_filter_multiplier rebalance_band min_holding_days s01_execution_mode s01_confirm_days s01_conviction_lookbacks".split()),
    "S02_factor_blend": set("rebalance_frequency mode min_price min_avg_dollar_volume top_quantile_long bottom_quantile_short long_short max_weight_per_name_long_only max_weight_per_name_long_short factor_weights_price_only".split()),
    "S03_pairs_mean_reversion": set("pair_selection_frequency correlation_window min_rolling_correlation cointegration_pvalue_threshold hedge_ratio_window zscore_window entry_z exit_z stop_z max_holding_days min_half_life max_half_life risk_per_pair max_active_pairs max_pairs_per_symbol target_gross".split()),
    "S04_carry_term_structure": set("requires_futures_chain rebalance_frequency carry_z_window entry_threshold exit_threshold carry_weight trend_weight max_weight_per_market".split()),
    "S05_implied_vs_realized_vol": set("requires_options_chain mode dte_min dte_max iv_percentile_short_vol iv_percentile_long_vol vrp_threshold_vol_points profit_take_credit_fraction stop_loss_credit_multiple exit_dte max_defined_loss_per_trade reject_if_bid_ask_width_pct_gt".split()),
    "S06_long_gamma_scalping": set("requires_options_chain requires_intraday_underlying dte_min dte_max iv_percentile_max delta_hedge_threshold max_premium_per_trade exit_dte".split()),
    "S07_skew_strategy": set("requires_options_chain mode put_skew_percentile_entry dte_min dte_max max_defined_loss_per_trade".split()),
    "S08_calendar_vol_spread": set("requires_options_chain front_dte_min front_dte_max back_dte_min back_dte_max max_defined_loss_per_trade".split()),
    "S09_arbitrage_scanner": set("research_scanner_only requires_options_chain min_edge_after_costs_bps do_not_auto_trade".split()),
    "S10_tail_hedge_overlay": set("overlay_only monthly_hedge_budget dte_min dte_max risk_off_trend_window".split()),
}
FACTOR_FIELDS = set("momentum_12m_ex_1m momentum_3m one_month_reversal low_volatility liquidity".split())


def _unique_fields(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _finite_json_number(raw: str) -> float:
    value = float(raw)
    if not isfinite(value):
        raise ValueError(f"nonfinite JSON number: {raw}")
    return value


def _check_fields(block: dict, allowed: set, location: str) -> None:
    if not isinstance(block, dict):
        raise ValueError(f"{location} must be an object")
    unknown = set(block) - allowed
    if unknown:
        raise ValueError(f"unknown fields in {location}: {sorted(unknown)}")


def validate_strategy_config(cfg: dict) -> None:
    """Validate known fields and reject contradictory/unsupported active settings."""
    _check_fields(cfg, {"schema_version", "global", "risk", "strategies"}, "config")
    if cfg.get("schema_version") != "1.0" or not all(k in cfg for k in ("global", "risk", "strategies")):
        raise ValueError("strategy config requires schema_version 1.0, global, risk, strategies")
    _check_fields(cfg["global"], GLOBAL_FIELDS, "global")
    _check_fields(cfg["risk"], RISK_FIELDS, "risk")
    _check_fields(cfg["strategies"], set(STRATEGY_FIELDS), "strategies")
    g, risk = cfg["global"], cfg["risk"]
    if g.get("allow_live_trading", False) is not False or g.get("mode") != "research_backtest_only":
        raise ValueError("only research_backtest_only with allow_live_trading=false is supported")
    if g.get("default_execution") not in ("next_open", "next_close"):
        raise ValueError("unsupported default_execution")
    for key in ("max_portfolio_drawdown_kill_switch", "max_strategy_drawdown_pause"):
        if key in risk and key in g and risk[key] != g[key]:
            raise ValueError(f"conflicting duplicate risk/global setting: {key}")
    for key, value in risk.items():
        if key == "allow_leverage_up":
            if not isinstance(value, bool):
                raise ValueError("allow_leverage_up must be boolean")
        elif not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
            raise ValueError(f"risk.{key} must be finite and nonnegative")
    from .risk.risk_manager import RiskManager
    RiskManager(risk | {k: g[k] for k in ("max_portfolio_drawdown_kill_switch", "max_strategy_drawdown_pause") if k in g})
    for name, params in cfg["strategies"].items():
        _check_fields(params, STRATEGY_FIELDS[name] | {"enabled", "role"}, name)
        if not isinstance(params.get("enabled", False), bool):
            raise ValueError(f"{name}.enabled must be boolean")
        if name[:3] not in ("S01", "S02", "S03") and params.get("enabled", False):
            raise ValueError(f"{name} is a disabled placeholder, not an implemented strategy")
        if name[:3] in ("S01", "S02") and params.get("long_short", False) is not False:
            raise ValueError(f"{name}.long_short is unsupported; strategy is long-only")
        if "rebalance_frequency" in params and params["rebalance_frequency"] not in ("daily", "weekly", "monthly"):
            raise ValueError(f"unsupported rebalance_frequency in {name}")
        if name == "S01_trend_following" and params.get("s01_execution_mode", "binary") not in ("binary", "conviction"):
            raise ValueError("unsupported s01_execution_mode")
        if name == "S03_pairs_mean_reversion" and params.get("pair_selection_frequency", "monthly") != "monthly":
            raise ValueError("S03 pair_selection_frequency currently supports only monthly")
        for key in ("max_weight_per_symbol", "max_weight_per_name_long_only", "max_weight_per_name_long_short"):
            if key in params:
                value = params[key]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
                    raise ValueError(f"{name}.{key} must be finite and nonnegative")
        if name == "S02_factor_blend":
            if params.get("mode", "price_only_v1") != "price_only_v1":
                raise ValueError("S02 supports only price_only_v1")
            factors = params.get("factor_weights_price_only", {})
            _check_fields(factors, FACTOR_FIELDS, "factor_weights_price_only")
            if factors and (any(not isfinite(v) or v < 0 for v in factors.values()) or sum(factors.values()) <= 0):
                raise ValueError("factor weights must be finite, nonnegative and have positive sum")


def configuration_diagnostics(cfg: dict | None = None) -> dict[str, str]:
    """Report retained declarative/inactive fields; these are not enforced controls.

    Explicit strategy CLI invocation selects that strategy; enabled/role metadata
    is not an automatic scheduler. Disabled research specifications are preserved.
    """
    cfg = load_strategy_config() if cfg is None else cfg
    notes = {
        "global.base_currency": "USD reporting convention; no currency conversion",
        "global.cost_filter_multiplier": "legacy declaration; S01 uses its own strategy value",
        "global.default_commission_bps": "requires explicit equity_cost_model_from_config; entrypoints currently use model defaults",
        "global.default_slippage_bps": "requires explicit equity_cost_model_from_config; entrypoints currently use model defaults",
        "risk.max_total_options_defined_loss": "future declaration; daily options engine uses OptionsRiskLimits",
        "risk.max_defined_loss_per_options_trade": "future declaration; daily options engine uses dollar OptionsRiskLimits",
        "risk.vol_spike_lookback": "not computed by RiskManager; caller must supply vol_spike_ratio",
        "strategies.S02_factor_blend.bottom_quantile_short": "inactive: S02 is long-only",
        "strategies.S02_factor_blend.max_weight_per_name_long_short": "inactive: S02 is long-only",
        "strategies.S01_trend_following.s01_confirm_days": "only effective in conviction mode",
        "strategies.S01_trend_following.s01_conviction_lookbacks": "only effective in conviction mode",
    }
    for name, params in cfg.get("strategies", {}).items():
        notes[f"strategies.{name}.enabled"] = "declarative metadata; explicit CLI selects the strategy"
        notes[f"strategies.{name}.role"] = "research/reporting classification"
        if name[:3] not in ("S01", "S02", "S03"):
            notes[f"strategies.{name}"] = "retained disabled research specification; not active runtime controls"
    return notes


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
        return json.load(fh, object_pairs_hook=_unique_fields,
                         parse_float=_finite_json_number, parse_constant=_finite_json_number)


def load_strategy_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load strategy_configs.json (the canonical strategy + risk config)."""
    canonical = configs_dir() / "strategy_configs.json"
    legacy = project_root() / "strategy_configs.json"
    if legacy.is_file():
        redirect = _load_json(legacy)
        if redirect.get("$ref") != "configs/strategy_configs.json" or set(redirect) - {"$ref", "_comment"}:
            raise ValueError("legacy strategy_configs.json must be a redirect, not a divergent payload")
    p = Path(path).resolve() if path else canonical
    if p.resolve() == legacy.resolve():
        p = canonical
    cfg = _load_json(p)
    validate_strategy_config(cfg)
    return cfg


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

    Precedence: explicit path -> canonical strategy config risk/global blocks.
    The strategy config's ``risk`` block is treated as authoritative because it
    is the file the specs reference directly.
    """
    if path:
        risk = _load_json(Path(path))
        _check_fields(risk, RISK_FIELDS | {"_comment"}, "risk")
        return {k: v for k, v in risk.items() if k != "_comment"}
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
