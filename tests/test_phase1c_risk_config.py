"""Phase 1C: final hard constraints, loss units, config authority, Git hygiene."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess

import numpy as np
import pandas as pd
import pytest

from quantbot import config
from quantbot.backtest.engine import BacktestEngine
from quantbot.options.risk import OptionsRiskLimits, evaluate_candidate
from quantbot.options.structures import VerticalSpread
from quantbot.portfolio.construction import apply_constraints
from quantbot.risk.greeks import aggregate_structure_greeks, options_loss_within_limit
from quantbot.risk.risk_manager import RiskManager
from quantbot.risk import var_es

ROOT = Path(__file__).resolve().parents[1]


def test_final_net_adjustment_cannot_break_single_or_sector_cap():
    rm = RiskManager(dict(max_single_symbol_weight=.15, max_asset_class_weight=.15,
                          max_gross_exposure=1, max_net_exposure=0))
    out, state = rm.process(pd.Series(dict(A=.15, B=.15, C=-.15)),
                            sector_map=dict(A="a", B="b", C="c"))
    assert out.abs().max() <= .15 + 1e-12
    assert out.abs().sum() <= 1 + 1e-12
    assert abs(out.sum()) <= 1e-12
    assert state.net_exposure == pytest.approx(out.sum())


def test_net_cap_never_creates_a_position_in_an_inactive_symbol():
    rm = RiskManager(dict(max_net_exposure=.05, max_asset_class_weight=1))
    out, _ = rm.process(pd.Series(dict(A=.15, B=0.0)))
    assert out.B == 0
    assert out.A <= .05 + 1e-12


def test_market_neutrality_survives_asymmetric_sector_caps():
    rm = RiskManager(dict(max_single_symbol_weight=1, max_asset_class_weight=.1))
    out, _ = rm.process(pd.Series(dict(A=.2, B=-.1, C=-.1)),
                        sector_map=dict(A="a", B="b", C="c"), market_neutral=True)
    assert abs(out.sum()) <= 1e-12
    assert out.abs().max() <= .1 + 1e-12


def test_daily_loss_derisk_cannot_be_undone_by_volatility_scale_up():
    rm = RiskManager(dict(max_single_symbol_weight=1, max_asset_class_weight=1))
    out, _ = rm.process(pd.Series(dict(A=.2)), asset_vols=pd.Series(dict(A=.01)),
                        prev_day_return=-.03, allow_leverage_up=True)
    assert out.A <= .1 + 1e-12


@pytest.mark.parametrize("key,value", [("max_single_symbol_weight", -.1),
    ("max_gross_exposure", np.nan), ("max_net_exposure", np.inf),
    ("max_asset_class_weight", -.1), ("risk_reduction_factor_on_daily_loss", 2)])
def test_invalid_risk_limits_fail_explicitly(key, value):
    with pytest.raises(ValueError):
        RiskManager({key: value})


def test_missing_sector_membership_is_conservatively_capped_as_one_group():
    out, state = RiskManager(dict(max_single_symbol_weight=1, max_asset_class_weight=.2)).process(
        pd.Series(dict(A=.3, B=.3)))
    assert out.abs().sum() <= .2 + 1e-12
    assert any("unmapped" in s for s in state.notes)


def test_portfolio_preclamp_actually_enforces_documented_net_limit():
    out = apply_constraints(pd.Series(dict(A=.15, B=.15, C=-.15)),
                            dict(max_single_symbol_weight=.15, max_net_exposure=0))
    assert out.abs().max() <= .15 + 1e-12
    assert abs(out.sum()) <= 1e-12


def test_engine_preserves_strategy_name_cap_after_vol_scaling():
    from test_etf_accounting_regressions import _panel, _ScheduledWeights
    strategy = _ScheduledWeights({60: .04})
    strategy.max_weight = .04
    strategy.long_only = True
    rm = RiskManager(dict(max_asset_class_weight=1))
    rm.volatility_target_scale = lambda *args, **kwargs: 4.0
    result = BacktestEngine(risk_manager=rm).run(strategy, _panel())
    assert result.orders
    assert all(abs(o.target_weight) <= .04 + 1e-12 for o in result.orders)


def test_structure_loss_is_converted_from_signed_pnl_to_positive_dollars():
    spread = VerticalSpread("call", 100, 110, long_price=4, short_price=1.5, spot=100)
    assert spread.max_loss() == pytest.approx(-250)
    risk = aggregate_structure_greeks([spread, spread])
    assert risk.max_loss == pytest.approx(500)
    assert not options_loss_within_limit(risk.max_loss, 10000, .04)
    assert options_loss_within_limit(risk.max_loss, 10000, .05)


@pytest.mark.parametrize("loss", [-500, np.nan, np.inf])
def test_loss_limit_does_not_accept_invalid_magnitudes(loss):
    assert not options_loss_within_limit(loss, 10000, .05)


@pytest.mark.parametrize("loss", [None, np.nan, -np.inf])
def test_unknown_structure_loss_does_not_become_zero(loss):
    structure = SimpleNamespace(net_greeks=lambda: {}, max_loss=lambda: loss)
    with pytest.raises(ValueError, match="loss"):
        aggregate_structure_greeks([structure])


@pytest.mark.parametrize("loss", [np.nan, 100, -np.inf])
def test_options_candidate_rejects_invalid_signed_maximum_loss(loss):
    c = SimpleNamespace(net_cash=-100, max_loss=loss, width=5, is_naked=False)
    assert not evaluate_candidate(c, OptionsRiskLimits(), current_open_positions=0,
        initial_capital=10000, current_portfolio_defined_loss=0).accepted


@pytest.mark.parametrize("fn", [var_es.historical_var, var_es.historical_es,
                                var_es.parametric_var, var_es.parametric_es])
def test_loss_fraction_diagnostics_are_nonnegative_on_all_gain_series(fn):
    assert fn(pd.Series([.01, .01, .01])) == pytest.approx(0)


def test_both_repository_config_paths_resolve_to_one_authority():
    assert config.load_strategy_config(ROOT / "strategy_configs.json") == config.load_strategy_config()


def write_config(tmp_path, obj):
    path = tmp_path / "custom.json"
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


def test_duplicate_json_fields_are_rejected(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema_version":"1.0","schema_version":"2.0"}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        config.load_strategy_config(path)


@pytest.mark.parametrize("section", ["global", "risk", "S01_trend_following"])
def test_unknown_configuration_fields_are_rejected(tmp_path, section):
    obj = deepcopy(config.load_strategy_config())
    block = obj[section] if section in obj else obj["strategies"][section]
    block["misspelled_ineffective_limit"] = .25
    with pytest.raises(ValueError, match="unknown"):
        config.load_strategy_config(write_config(tmp_path, obj))


def test_unsupported_long_short_configuration_cannot_silently_do_nothing(tmp_path):
    obj = deepcopy(config.load_strategy_config())
    obj["strategies"]["S01_trend_following"]["long_short"] = True
    with pytest.raises(ValueError, match="long_short"):
        config.load_strategy_config(write_config(tmp_path, obj))


def test_divergent_root_payload_cannot_silently_coexist(tmp_path, monkeypatch):
    obj = json.loads((ROOT / "configs/strategy_configs.json").read_text())
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs/strategy_configs.json").write_text(json.dumps(obj))
    obj["risk"]["max_net_exposure"] = .05
    (tmp_path / "strategy_configs.json").write_text(json.dumps(obj))
    monkeypatch.setattr(config, "project_root", lambda: tmp_path)
    with pytest.raises(ValueError, match="legacy|divergent|redirect"):
        config.load_strategy_config()


def ignored(path):
    result = subprocess.run(["git", "-c", "core.excludesFile=NUL", "check-ignore", "--no-index", "-q", path],
        cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode in (0, 1), result.stderr
    return result.returncode == 0


@pytest.mark.parametrize("path", ["src/quantbot/data/__init__.py", "src/quantbot/data/loaders.py",
                                   "src/quantbot/data/options_providers/synthetic.py"])
def test_data_source_code_is_trackable(path):
    assert not ignored(path)


@pytest.mark.parametrize("path", ["data/local.csv", "data/options/chain.parquet",
    "src/quantbot/data/__pycache__/loaders.pyc", "outputs/run.json", "logs/run.log",
    ".venv/Lib/site-packages/local.py", "reports/options/run.csv", ".env"])
def test_local_datasets_generated_files_and_secrets_stay_ignored(path):
    assert ignored(path)


@pytest.mark.parametrize("seed", range(6))
def test_final_constraints_hold_together_across_adversarial_portfolios(seed):
    rng = np.random.default_rng(seed)
    symbols = list("ABCDEFGH")
    sectors = {s: str(i % 3) for i, s in enumerate(symbols)}
    for _ in range(30):
        single, gross, net, sector = rng.uniform(0, .3), rng.uniform(0, 2), rng.uniform(0, .5), rng.uniform(0, .4)
        strategy_cap = rng.uniform(0, .2)
        neutral, long_only = bool(rng.integers(2)), bool(rng.integers(2))
        rm = RiskManager(dict(max_single_symbol_weight=single, max_gross_exposure=gross,
            max_net_exposure=net, max_asset_class_weight=sector, max_vol_scale=10))
        raw = pd.Series(rng.normal(0, .5, len(symbols)), index=symbols)
        out, state = rm.process(raw, asset_vols=pd.Series(.01, index=symbols),
            allow_leverage_up=True, market_neutral=neutral, long_only=long_only,
            strategy_max_weight=strategy_cap, sector_map=sectors)
        assert out.abs().max() <= min(single, strategy_cap) + 1e-10
        assert out.abs().sum() <= gross + 1e-10
        assert abs(out.sum()) <= (0 if neutral else net) + 1e-10
        assert (out.abs().groupby(pd.Series(sectors)).sum() <= sector + 1e-10).all()
        assert not long_only or (out >= -1e-10).all()
        assert ((out == 0) | (np.sign(out) == np.sign(raw))).all()
        assert state.gross_exposure == pytest.approx(out.abs().sum())


def test_incompatible_long_only_and_neutral_requirements_safely_flatten():
    out, _ = RiskManager({}).process(pd.Series(dict(A=.1, B=.1)),
                                     long_only=True, market_neutral=True)
    assert out.eq(0).all()


def test_final_validator_detects_a_later_broken_transform(monkeypatch):
    rm = RiskManager({})
    monkeypatch.setattr(rm, "apply_exposure_caps", lambda w: w * 100)
    with pytest.raises(ValueError, match="final portfolio"):
        rm.process(pd.Series(dict(A=.1)))


@pytest.mark.parametrize("field,value", [("max_loss_per_trade", np.nan),
    ("max_width", -.1), ("max_concurrent_positions", 1.5),
    ("max_portfolio_defined_loss_pct", 5), ("allow_naked", True)])
def test_options_limits_cannot_disable_hard_checks_via_invalid_configuration(field, value):
    with pytest.raises(ValueError):
        OptionsRiskLimits(**{field: value})


def test_direct_risk_configuration_rejects_unknown_limit():
    with pytest.raises(ValueError, match="unknown"):
        RiskManager({"max_gross_expsoure": .1})


def test_portfolio_greeks_requires_positive_loss_amounts():
    from quantbot.risk.greeks import PortfolioGreeks
    with pytest.raises(ValueError, match="loss"):
        PortfolioGreeks(max_loss=-100)


def test_duplicate_cross_section_risk_setting_cannot_conflict(tmp_path):
    obj = deepcopy(config.load_strategy_config())
    obj["risk"]["max_portfolio_drawdown_kill_switch"] = .01
    with pytest.raises(ValueError, match="conflicting"):
        config.load_strategy_config(write_config(tmp_path, obj))


def test_canonical_loading_is_cwd_independent_and_preserves_newer_values(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    obj = config.load_strategy_config()
    assert obj == config.load_strategy_config(ROOT / "strategy_configs.json")
    p = config.strategy_params("S01_trend_following", obj)
    assert p["cost_filter_multiplier"] == 4 and p["min_holding_days"] == 20
    assert p["long_short"] is False
    p3 = config.strategy_params("S03_pairs_mean_reversion", obj)
    assert (p3["min_rolling_correlation"], p3["cointegration_pvalue_threshold"], p3["target_gross"]) == (.65, .1, .6)
    risk = config.load_risk_config()
    assert risk["max_single_symbol_weight"] == obj["risk"]["max_single_symbol_weight"]


@pytest.mark.parametrize("entry", ["run_s01.py", "run_s02.py", "run_s03.py", "run_core.py",
                                   "run_compare.py", "research_edge.py", "report_s02_v3.py"])
def test_relevant_script_entry_points_share_the_canonical_loader(entry, monkeypatch):
    import runpy
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    namespace = runpy.run_path(str(ROOT / "scripts" / entry))
    assert namespace["load_strategy_config"] is config.load_strategy_config
    assert namespace["load_strategy_config"]() == config.load_strategy_config()


def test_inactive_configuration_fields_are_explicitly_classified():
    diagnostics = config.configuration_diagnostics()
    assert "OptionsRiskLimits" in diagnostics["risk.max_total_options_defined_loss"]
    assert "long-only" in diagnostics["strategies.S02_factor_blend.bottom_quantile_short"]
    assert "disabled" in diagnostics["strategies.S05_implied_vs_realized_vol"]


def test_all_existing_data_python_sources_are_visible_to_git():
    sources = list((ROOT / "src/quantbot/data").rglob("*.py"))
    assert len(sources) >= 12
    for path in sources:
        assert not ignored(path.relative_to(ROOT).as_posix())


def test_nonfinite_json_configuration_is_rejected_even_outside_risk_block(tmp_path):
    obj = deepcopy(config.load_strategy_config())
    obj["global"]["default_commission_bps"] = np.nan
    with pytest.raises(ValueError, match="finite"):
        config.load_strategy_config(write_config(tmp_path, obj))


@pytest.mark.parametrize("strategy,key", [("S01_trend_following", "max_weight_per_symbol"),
    ("S02_factor_blend", "max_weight_per_name_long_only")])
def test_negative_strategy_hard_cap_is_rejected_at_config_load(tmp_path, strategy, key):
    obj = deepcopy(config.load_strategy_config())
    obj["strategies"][strategy][key] = -.1
    with pytest.raises(ValueError, match=key):
        config.load_strategy_config(write_config(tmp_path, obj))


def test_unsupported_pair_selection_frequency_is_not_silently_ignored(tmp_path):
    obj = deepcopy(config.load_strategy_config())
    obj["strategies"]["S03_pairs_mean_reversion"]["pair_selection_frequency"] = "daily"
    with pytest.raises(ValueError, match="pair_selection_frequency"):
        config.load_strategy_config(write_config(tmp_path, obj))


def test_fee_declarations_are_not_misrepresented_as_wired_entrypoint_controls():
    notes = config.configuration_diagnostics()
    assert "explicit" in notes.get("global.default_commission_bps", "")
    assert "explicit" in notes.get("global.default_slippage_bps", "")
