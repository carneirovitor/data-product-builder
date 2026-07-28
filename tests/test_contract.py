"""Intent: contract is DCS 0.9.3 with hard vs soft severity protecting Q2."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.lib.config import DEFAULT_CONTRACT_PATH, DEFAULT_PRODUCT_PATH
from src.lib.contract import (
    ContractError,
    assert_contract_valid,
    load_contract,
    row_rules,
    validate_contract_structure,
)
from src.lib.metadata import load_product


@pytest.fixture(scope="module")
def contract():
    return load_contract(DEFAULT_CONTRACT_PATH)


@pytest.fixture(scope="module")
def product():
    return load_product(DEFAULT_PRODUCT_PATH)


def test_contract_parses_as_dcs_093(contract):
    assert contract["dataContractSpecification"] == "0.9.3"
    assert "models" in contract
    assert "quality" in contract
    assert "fitness_for_use" in contract


def test_contract_structure_is_valid(contract):
    errors = validate_contract_structure(contract)
    assert errors == [], errors


def test_passenger_count_is_warning_because_protects_q2_fleet_bias(contract):
    rule = next(r for r in contract["quality"] if r["name"] == "passenger_count_range")
    assert rule["severity"] == "warning"
    assert rule["scope"] == "row"
    assert rule["dimension"] == "validity"


def test_negative_amount_is_warning_because_tlc_adjustments_not_errors(contract):
    rule = next(r for r in contract["quality"] if r["name"] == "total_amount_non_negative")
    assert rule["severity"] == "warning"
    assert rule["dimension"] == "accuracy"
    assert "adjustment" in rule.get("description", "").lower() or "refund" in rule.get("description", "").lower()


def test_hard_timestamps_and_completeness_are_error_for_quarantine(contract):
    hard_names = {r["name"] for r in row_rules(contract, severity="error")}
    assert "total_amount_non_negative" not in hard_names
    assert "dropoff_after_pickup" in hard_names
    assert "vendor_id_not_null" in hard_names
    assert "total_amount_not_null" in hard_names


def test_assert_fails_loud_when_passenger_count_made_error(contract):
    bad = dict(contract)
    quality = [dict(r) for r in contract["quality"]]
    for r in quality:
        if r["name"] == "passenger_count_range":
            r["severity"] = "error"
    bad["quality"] = quality
    with pytest.raises(ContractError, match="passenger_count_range"):
        assert_contract_valid(bad)


def test_every_consumption_output_has_a_model_because_undeclared_interface_is_ungoverned(
    contract, product
):
    """Consumption is the product's published surface, so nothing may ship there
    without declared columns — that is what puts comments and tags in the catalog.
    Quarantine and the governance views are operational, not part of the interface."""
    published = {
        out["fqn"].split(".")[-1]
        for out in product["outputs"]
        if out["fqn"].startswith("consumption.")
    }
    undeclared = published - set(contract["models"])
    assert undeclared == set(), f"consumption outputs without a contract model: {undeclared}"


def test_kpi_models_expose_run_id_because_a_metric_without_lineage_is_unauditable(contract):
    for name in (
        "kpi_yellow_avg_total_amount_monthly",
        "kpi_fleet_avg_passenger_count_hourly",
    ):
        assert "run_id" in contract["models"][name]["fields"]


def test_dama_dimensions_in_use_are_honest_for_a_batch_product(contract):
    """Historical overwrite has no freshness SLA — do not invent timeliness rules."""
    dims = {r["dimension"] for r in contract["quality"]}
    expected = {
        "accuracy",
        "completeness",
        "consistency",
        "validity",
        "uniqueness",
    }
    assert expected.issubset(dims)
    assert "timeliness" not in dims
    by_name = {r["name"]: r for r in contract["quality"]}
    assert by_name["month_coverage"]["dimension"] == "completeness"
    assert by_name["volume_sanity"]["dimension"] == "completeness"
