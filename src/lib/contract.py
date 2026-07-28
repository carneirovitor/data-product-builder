"""Load and structurally validate Data Contract Specification 0.9.3 YAML."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REQUIRED_TOP_LEVEL = ("dataContractSpecification", "id", "info", "models")
REQUIRED_QUALITY_KEYS = ("name", "dimension", "scope", "severity")
VALID_DIMENSIONS = {
    "accuracy",
    "completeness",
    "consistency",
    "timeliness",
    "validity",
    "uniqueness",
}
VALID_SEVERITIES = {"error", "warning"}
VALID_SCOPES = {"row", "aggregate"}


class ContractError(ValueError):
    """Raised when the contract fails structural validation — fail loud."""


def load_contract(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise ContractError(f"Contract not found: {path}")
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ContractError("Contract root must be a mapping")
    return data


def validate_contract_structure(contract: dict[str, Any]) -> list[str]:
    """Return list of structural issues (empty = ok)."""
    errors: list[str] = []

    for key in REQUIRED_TOP_LEVEL:
        if key not in contract:
            errors.append(f"missing top-level key: {key}")

    spec = contract.get("dataContractSpecification")
    if spec is not None and str(spec) != "0.9.3":
        errors.append(
            f"expected dataContractSpecification '0.9.3', got {spec!r} "
            "(do not mix Bitol ODCS v3 schema here)"
        )

    info = contract.get("info") or {}
    if not info.get("owner"):
        errors.append("info.owner is required for accountability")

    models = contract.get("models") or {}
    if "taxi_trips" not in models:
        errors.append("models.taxi_trips is required")

    for rule in contract.get("quality") or []:
        for key in REQUIRED_QUALITY_KEYS:
            if key not in rule:
                errors.append(f"quality rule missing '{key}': {rule.get('name', rule)}")
        dim = rule.get("dimension")
        if dim and dim not in VALID_DIMENSIONS:
            errors.append(f"invalid dimension '{dim}' on rule {rule.get('name')}")
        sev = rule.get("severity")
        if sev and sev not in VALID_SEVERITIES:
            errors.append(f"invalid severity '{sev}' on rule {rule.get('name')}")
        scope = rule.get("scope")
        if scope and scope not in VALID_SCOPES:
            errors.append(f"invalid scope '{scope}' on rule {rule.get('name')}")

    # Soft vs hard intent checks for known trade-offs
    quality_by_name = {r.get("name"): r for r in (contract.get("quality") or [])}
    pc = quality_by_name.get("passenger_count_range")
    if pc and pc.get("severity") != "warning":
        errors.append(
            "passenger_count_range must be severity=warning to protect Q2 fleet bias"
        )

    neg_amt = quality_by_name.get("total_amount_non_negative")
    if neg_amt and neg_amt.get("severity") != "warning":
        errors.append(
            "total_amount_non_negative must be severity=warning — TLC negatives may be adjustments"
        )

    hard_expected = {
        "dropoff_after_pickup",
        "vendor_id_not_null",
        "total_amount_not_null",
        "pickup_not_null",
        "dropoff_not_null",
        "taxi_type_valid",
        "year_month_in_window",
    }
    for name in hard_expected:
        rule = quality_by_name.get(name)
        if not rule:
            errors.append(f"missing hard quality rule: {name}")
        elif rule.get("severity") != "error":
            errors.append(f"hard rule {name} must have severity=error")

    fitness = contract.get("fitness_for_use") or []
    if not fitness:
        errors.append("fitness_for_use block is required")

    profiling = contract.get("profiling") or {}
    if not profiling.get("columns"):
        errors.append("profiling.columns is required")

    return errors


def assert_contract_valid(contract: dict[str, Any]) -> None:
    errors = validate_contract_structure(contract)
    if errors:
        joined = "; ".join(errors)
        raise ContractError(f"Contract validation failed: {joined}")


def row_rules(contract: dict[str, Any], *, severity: str | None = None) -> list[dict]:
    rules = [
        r
        for r in (contract.get("quality") or [])
        if r.get("scope") == "row" and r.get("expression")
    ]
    if severity:
        rules = [r for r in rules if r.get("severity") == severity]
    return rules


def aggregate_rules(contract: dict[str, Any]) -> list[dict]:
    return [r for r in (contract.get("quality") or []) if r.get("scope") == "aggregate"]


def fitness_rules(contract: dict[str, Any]) -> list[dict]:
    return list(contract.get("fitness_for_use") or [])


def profiling_spec(contract: dict[str, Any]) -> dict[str, Any]:
    return dict(contract.get("profiling") or {})
