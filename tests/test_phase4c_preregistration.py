"""Integrity checks for the pre-performance Phase 4C research registration.

No new market data or performance evaluation is used by these tests.
"""
from dataclasses import asdict
from datetime import date
import json
from pathlib import Path

import pytest

from quantbot.data.storage.provenance import file_digest, load_sealed, safe_metadata
from quantbot.options.s05_spec import S05Parameters

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "research/phase4c/s05-v1/preregistration.json"
SPEC = ROOT / "research/phase4b/s05-v1/specification.json"
SPEC_SHA = "996afd429eb4461408c8a5c2cce81fdd7e9f214e02cefbfabcfbad14b563b4f0"


@pytest.fixture
def plan():
    return load_sealed(PLAN)


def test_preregistration_is_sealed_and_portable(plan):
    assert plan["kind"] == "phase4c_preregistration"
    assert plan["performance_evaluated_before_registration"] is False
    safe_metadata(plan)


def test_frozen_specification_is_byte_identical(plan):
    assert file_digest(SPEC) == SPEC_SHA == plan["frozen_specification"]["file_sha256"]
    spec = load_sealed(SPEC)
    assert spec["parameters"] == asdict(S05Parameters())
    assert spec["manifest_sha256"] == plan["frozen_specification"]["manifest_sha256"]
    assert plan["baseline_commit"] == "0d46cd9d21a8fe2b3ab041cb5067f0b331a4383a"


@pytest.mark.parametrize("name,start,end", [
    ("development", "2022-01-01", "2023-01-31"),
    ("validation", "2023-02-01", "2024-12-31"),
    ("holdout", "2025-01-01", "2026-08-31"),
])
def test_fixed_nonoverlapping_periods(plan, name, start, end):
    period = plan["periods"][name]
    assert (period["start"], period["end"]) == (start, end)
    assert date.fromisoformat(start) <= date.fromisoformat(end)
    if name != "development":
        previous = "development" if name == "validation" else "validation"
        assert date.fromisoformat(plan["periods"][previous]["end"]) < date.fromisoformat(start)


def test_holdout_end_is_latest_complete_month_at_registration(plan):
    registered = date.fromisoformat(plan["registered_on"])
    assert registered == date(2026, 9, 18)
    assert plan["periods"]["holdout"]["end"] == "2026-08-31"
    assert plan["periods"]["holdout"]["label"] == "retrospective_post_specification_holdout"
    assert plan["history_audit"]["untouched_oos_claim"] is False


def test_warmup_does_not_authorize_earlier_trades(plan):
    warmup = plan["data_acquisition"]["warmup"]
    assert warmup["options_start"] == "2022-01-01"
    assert warmup["performance_included"] is False
    assert warmup["weaken_minimum_valid_observations"] is False
    assert plan["period_execution"]["trade_outside_period"] is False
    assert plan["period_execution"]["initial_cash_per_symbol_period_usd"] == 100000


def test_symbol_extension_does_not_rewrite_frozen_universe(plan):
    spec = load_sealed(SPEC)
    assert spec["rules"]["universe"] == ["SPY", "QQQ"]
    assert plan["symbols"]["core"] == ["SPY", "QQQ"]
    assert plan["symbols"]["conditional_replication"] == ["IWM"]
    assert plan["symbols"]["combined_capital_portfolio"] is False
    assert plan["symbols"]["choose_symbols_using_performance"] is False


def test_cost_scenarios_only_change_explicit_costs(plan):
    costs = plan["cost_sensitivity"]
    assert costs["multipliers"] == [0, 1, 2]
    assert costs["changed_fields"] == ["per_contract_fee", "multi_leg_penalty"]
    assert costs["base_per_contract_fee_usd"] == .65
    assert costs["base_multi_leg_penalty_usd"] == 1
    assert costs["change_bid_ask"] is False
    assert costs["change_gross_credit_exit_thresholds"] is False
    assert costs["change_economic_parameters"] is False


def test_data_scope_and_nulls_are_explicit(plan):
    scope = plan["data_acquisition"]
    assert scope["option_max_dte"] == 45
    assert scope["option_granularity"] == "daily_eod"
    assert scope["provider"] == "thetadata"
    assert scope["normalization_version"] == "theta-v3-1"
    assert scope["missing_numeric_policy"] == "null_never_zero"
    assert scope["oi_required"] is False
    assert scope["local_iv_fallback"] is False
    assert scope["paid_changes_without_approval"] is False
    assert scope["underlying"]["price_basis"] == "adjusted_close"
    for field in ("underlying", "date", "expiration", "strike", "option_type", "bid", "ask", "implied_volatility", "delta", "underlying_price"):
        assert field in scope["required_fields"]


def test_publication_and_holdout_gates_are_registered(plan):
    gates = plan["execution_gates"]
    assert gates["require_committed_and_pushed_plan_before_download"] is True
    assert gates["require_spec_hash_before_and_after_each_run"] is True
    assert gates["require_quality_audit_before_performance"] is True
    assert gates["require_validation_seal_before_holdout"] is True
    assert gates["seal_includes_all_cost_scenarios_and_available_symbols"] is True
    assert gates["continue_after_poor_validation"] is True
    assert gates["holdout_evaluation_batches"] == 1
    assert gates["replay_allows_parameter_changes"] is False


def test_classification_has_explicit_predefined_evidence_thresholds(plan):
    rule = plan["classification"]
    assert rule["minimum_completed_trades_total_per_symbol"] == 30
    assert rule["minimum_completed_trades_each_period"] == 10
    assert rule["minimum_chain_and_underlying_session_coverage"] == .95
    assert rule["maximum_largest_winner_share_of_positive_pnl"] == .25
    assert rule["maximum_top_five_winner_share_of_positive_pnl"] == .60
    assert rule["validated_requires_positive_base_and_double_cost_in_both_periods"] is True
    assert set(rule["statuses"]) == {"RESEARCH-VALIDATED", "RESEARCH-UNCERTAIN", "RESEARCH-REJECTED"}
    assert rule["claim_alpha_or_live_readiness"] is False


def test_required_metrics_and_reconciliation_are_registered(plan):
    metrics = plan["metrics"]
    for name in ("eligible_decision_dates", "threshold_signals", "selected_condors", "submitted_entries", "rejections_by_reason", "completed_trades", "expectancy", "return_on_risk_deployed", "max_drawdown", "max_simultaneous_defined_risk", "gross_premium_turnover", "commissions", "additional_slippage", "entry_conditions", "exit_reasons", "by_calendar_year", "by_underlying", "concentration"):
        assert name in metrics
    assert plan["reconciliation"] == {"rtol": 1e-12, "atol": 1e-8, "reuse_phase4b_ledger_checks": True}


def test_tampered_registration_is_detected(tmp_path):
    value = json.loads(PLAN.read_text(encoding="utf-8"))
    value["periods"]["holdout"]["start"] = "2026-01-01"
    path = tmp_path / "changed.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        load_sealed(path)