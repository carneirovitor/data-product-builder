"""Intent: soda_runner maps Contract policy → SodaCL / soft vs hard quarantine semantics."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.lib.config import DEFAULT_CONTRACT_PATH, DEFAULT_SODA_CHECKS_PATH
from src.lib.contract import load_contract, row_rules
from src.lib.soda_runner import (
    _synthesize_outcomes_from_summary,
    fail_condition_from_pass_expression,
    generate_sodacl_from_contract,
    map_scan_to_outcomes,
    outcomes_to_validation_rows,
    SodaCheckOutcome,
)


@pytest.fixture(scope="module")
def contract():
    return load_contract(DEFAULT_CONTRACT_PATH)


def test_fail_condition_inverts_pass_expression():
    expr = "total_amount IS NOT NULL AND total_amount >= 0"
    fail = fail_condition_from_pass_expression(expr)
    assert "NOT (" in fail
    assert expr in fail


def test_generated_sodacl_marks_passenger_count_as_warn_because_protects_q2(contract):
    sodacl = generate_sodacl_from_contract(contract)
    assert "name: passenger_count_range" in sodacl
    # Soft must use warn condition, not fail condition adjacent to that rule
    block_start = sodacl.index("name: passenger_count_range")
    block = sodacl[block_start : block_start + 120]
    assert "warn condition:" in block
    assert "fail condition:" not in block


def test_generated_sodacl_marks_negative_amount_as_warn_because_tlc_adjustments(contract):
    sodacl = generate_sodacl_from_contract(contract)
    idx = sodacl.index("name: total_amount_non_negative")
    block = sodacl[idx : idx + 160]
    assert "warn condition:" in block
    assert "fail condition:" not in block


def test_hand_authored_sodacl_exists_and_lists_hard_and_soft_rules():
    path = DEFAULT_SODA_CHECKS_PATH
    text = path.read_text(encoding="utf-8")
    assert "total_amount_non_negative" in text
    assert "passenger_count_range" in text
    assert "warn condition:" in text
    assert "fail condition:" in text


def test_outcomes_to_validation_rows_soft_never_blocks_scorecard(contract):
    outcomes = [
        SodaCheckOutcome(
            name="passenger_count_range",
            outcome="warn",
            severity="warning",
            dimension="validity",
            measured=0.4,
        ),
        SodaCheckOutcome(
            name="total_amount_non_negative",
            outcome="warn",
            severity="warning",
            dimension="accuracy",
            measured=0.9,
        ),
    ]
    rows = outcomes_to_validation_rows(
        outcomes,
        run_id="r1",
        soft_pass_rates={"passenger_count_range": 0.4},
    )
    soft_amt = next(r for r in rows if r["rule"] == "total_amount_non_negative")
    soft = next(r for r in rows if r["rule"] == "passenger_count_range")
    assert soft_amt["passed"] is True
    assert soft_amt["severity"] == "warning"
    assert soft["passed"] is True
    assert soft["severity"] == "warning"
    assert soft["dimension"] == "validity"


class _FakeOutcome:
    def __init__(self, value):
        self.value = value


class _FakeCheck:
    def __init__(self, name, outcome):
        self.name = name
        self.outcome = _FakeOutcome(outcome)


class _FakeScan:
    def __init__(self, checks):
        self._checks = checks


def test_map_scan_to_outcomes_enriches_dama_dimension_from_contract(contract):
    scan = _FakeScan(
        [
            _FakeCheck("total_amount_non_negative", "fail"),  # soft → coerced to warn
            _FakeCheck("passenger_count_range", "fail"),  # soft → coerced to warn
        ]
    )
    outcomes = map_scan_to_outcomes(scan, contract)
    by_name = {o.name: o for o in outcomes}
    assert by_name["total_amount_non_negative"].dimension == "accuracy"
    assert by_name["total_amount_non_negative"].severity == "warning"
    assert by_name["total_amount_non_negative"].outcome == "warn"
    assert by_name["passenger_count_range"].severity == "warning"
    assert by_name["passenger_count_range"].outcome == "warn"


def test_synthesized_outcomes_use_per_rule_counts_because_quarantine_rate_fails_every_rule(
    contract,
):
    hard = row_rules(contract, severity="error")
    soft = row_rules(contract, severity="warning")
    offender = hard[0]["name"]
    total = 16_526_016
    fail_counts = {rule["name"]: 0 for rule in (*hard, *soft)}
    fail_counts[offender] = 795
    summary = {
        "quarantine_rate": 795 / total,
        "rule_fail_counts": fail_counts,
        "rule_pass_rates": {
            name: (total - count) / total for name, count in fail_counts.items()
        },
    }

    by_name = {o.name: o for o in _synthesize_outcomes_from_summary(contract, summary)}

    assert by_name[offender].outcome == "fail"
    for rule in hard[1:]:
        assert by_name[rule["name"]].outcome == "pass"
        assert by_name[rule["name"]].measured == 1.0


def test_clean_hard_rule_records_pass_because_scorecard_must_match_run_status():
    outcomes = [
        SodaCheckOutcome(
            name="pickup_not_null",
            outcome="pass",
            severity="error",
            dimension="completeness",
            measured=1.0,
            threshold=1.0,
        ),
        SodaCheckOutcome(
            name="dropoff_after_pickup",
            outcome="fail",
            severity="error",
            dimension="consistency",
            measured=0.999952,
            threshold=1.0,
        ),
    ]

    by_rule = {r["rule"]: r for r in outcomes_to_validation_rows(outcomes, run_id="r1")}

    assert by_rule["pickup_not_null"]["passed"] is True
    assert by_rule["pickup_not_null"]["measured"] == 1.0
    # A rule that did fire keeps passed=False, but reports the real rate instead of 0.0
    assert by_rule["dropoff_after_pickup"]["passed"] is False
    assert by_rule["dropoff_after_pickup"]["measured"] == pytest.approx(0.999952)
    assert by_rule["dropoff_after_pickup"]["threshold"] == 1.0


def test_contract_row_rules_align_with_sodacl_names(contract):
    sodacl = DEFAULT_SODA_CHECKS_PATH.read_text()
    for rule in row_rules(contract):
        assert f"name: {rule['name']}" in sodacl
