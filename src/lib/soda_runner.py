"""Soda Core execution engine — scan Spark DF, map results, materialize quarantine.

Contract (DCS 0.9.3) = policy / ownership / DAMA metadata / fitness.
SodaCL = executable checks. Quarantine uses the same fail predicates so every
hard failure is retained as a multi-rule incident trail.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.lib.config import DEFAULT_SODA_CHECKS_PATH
from src.lib.contract import row_rules

if TYPE_CHECKING:
    from pyspark.sql import DataFrame, SparkSession

logger = logging.getLogger(__name__)

DEFAULT_SODA_CHECKS = DEFAULT_SODA_CHECKS_PATH
DATASET_NAME = "taxi_trips"


@dataclass
class SodaCheckOutcome:
    name: str
    outcome: str  # pass | fail | warn | error | unknown
    severity: str  # error | warning
    dimension: str
    scope: str = "row"
    measured: float | None = None
    threshold: float | None = None


@dataclass
class SodaGateResult:
    clean: Any
    quarantine: Any
    summary: dict[str, Any]
    check_outcomes: list[SodaCheckOutcome] = field(default_factory=list)
    scan_exit_code: int = 0
    scan_logs: str = ""


def fail_condition_from_pass_expression(expression: str) -> str:
    """Invert a contract pass expression into a Soda fail condition."""
    return f"NOT ({expression}) OR ({expression}) IS NULL"


def generate_sodacl_from_contract(contract: dict[str, Any], dataset: str = DATASET_NAME) -> str:
    """Thin translator: contract row rules → SodaCL failed-rows checks."""
    lines = [f"checks for {dataset}:"]
    for rule in row_rules(contract):
        name = rule["name"]
        fail_cond = fail_condition_from_pass_expression(rule["expression"])
        if rule.get("severity") == "warning":
            lines.append("  - failed rows:")
            lines.append(f"      name: {name}")
            lines.append(f"      warn condition: {fail_cond}")
        else:
            lines.append("  - failed rows:")
            lines.append(f"      name: {name}")
            lines.append(f"      fail condition: {fail_cond}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_sodacl_from_contract(
    contract: dict[str, Any],
    path: str | Path = DEFAULT_SODA_CHECKS,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(generate_sodacl_from_contract(contract), encoding="utf-8")
    return path


def _rule_meta(contract: dict[str, Any]) -> dict[str, dict]:
    return {r["name"]: r for r in (contract.get("quality") or []) if r.get("name")}


def _parse_sodacl_check_names(sodacl_text: str) -> list[str]:
    return re.findall(r"^\s+name:\s*([^\s#]+)", sodacl_text, flags=re.MULTILINE)


def run_soda_scan(
    spark: "SparkSession",
    df: "DataFrame",
    *,
    sodacl_path: str | Path | None = None,
    sodacl_yaml: str | None = None,
    dataset_name: str = DATASET_NAME,
    scan_definition_name: str = "taxi_trips_dq",
    data_source_name: str = "spark_df",
) -> tuple[int, str, Any]:
    """Execute Soda Core scan against a Spark DataFrame (temp view)."""
    from soda.scan import Scan

    view = dataset_name
    df.createOrReplaceTempView(view)

    if sodacl_yaml is None:
        path = Path(sodacl_path or DEFAULT_SODA_CHECKS)
        if not path.exists():
            raise FileNotFoundError(f"SodaCL checks not found: {path}")
        sodacl_yaml = path.read_text(encoding="utf-8")

    scan = Scan()
    scan.set_scan_definition_name(scan_definition_name)
    scan.set_data_source_name(data_source_name)
    scan.add_spark_session(spark, data_source_name=data_source_name)
    scan.add_sodacl_yaml_str(sodacl_yaml)

    exit_code = scan.execute()
    logs = scan.get_logs_text() or ""
    logger.info("SODA scan exit_code=%s dataset=%s", exit_code, dataset_name)
    if logs:
        logger.debug("SODA logs:\n%s", logs)
    return int(exit_code), logs, scan


def map_scan_to_outcomes(
    scan: Any,
    contract: dict[str, Any],
    *,
    sodacl_yaml: str | None = None,
) -> list[SodaCheckOutcome]:
    """Map Soda check results → outcomes enriched with DAMA dimension from contract."""
    meta = _rule_meta(contract)
    outcomes: list[SodaCheckOutcome] = []
    seen: set[str] = set()

    check_results = getattr(scan, "_checks", None) or getattr(scan, "checks", None) or []
    for check in check_results:
        name = (
            getattr(check, "name", None)
            or getattr(check, "check_name", None)
            or _extract_name_from_check(check)
        )
        if not name:
            continue
        seen.add(name)
        outcome_raw = getattr(check, "outcome", None)
        outcome = str(getattr(outcome_raw, "value", outcome_raw) or "unknown").lower()
        rule = meta.get(name, {})
        severity = rule.get("severity", "error")
        # Soft rules that warn should not count as hard fail for job kill via Soda alone
        if severity == "warning" and outcome == "fail":
            outcome = "warn"
        outcomes.append(
            SodaCheckOutcome(
                name=name,
                outcome=outcome,
                severity=severity,
                dimension=rule.get("dimension", "validity"),
                scope=rule.get("scope", "row"),
            )
        )

    # Fallback: if Scan API shape differs, derive pass/fail from contract after quarantine step
    if not outcomes and sodacl_yaml:
        for name in _parse_sodacl_check_names(sodacl_yaml):
            rule = meta.get(name, {})
            outcomes.append(
                SodaCheckOutcome(
                    name=name,
                    outcome="unknown",
                    severity=rule.get("severity", "error"),
                    dimension=rule.get("dimension", "validity"),
                    scope=rule.get("scope", "row"),
                )
            )
    return outcomes


def _extract_name_from_check(check: Any) -> str | None:
    identity = getattr(check, "identity", None)
    if isinstance(identity, str) and identity:
        return identity
    check_cfg = getattr(check, "check_cfg", None)
    if check_cfg is not None:
        return getattr(check_cfg, "name", None)
    return None


def materialize_quarantine(
    spark: "SparkSession",
    df: "DataFrame",
    contract: dict[str, Any],
    *,
    run_id: str,
) -> tuple["DataFrame", "DataFrame", dict[str, Any]]:
    """
    Split clean/quarantine using hard fail predicates from the contract
    (aligned 1:1 with SodaCL fail conditions). Soft rules never quarantine.
    """
    from pyspark.sql import functions as F

    hard = row_rules(contract, severity="error")
    soft = row_rules(contract, severity="warning")
    if not hard:
        raise RuntimeError(f"No hard row rules in contract — fail loud run_id={run_id}")

    work = df
    hard_fail_flags: list[str] = []
    for rule in hard:
        col = f"_fail_{rule['name']}"
        fail_cond = fail_condition_from_pass_expression(rule["expression"])
        work = work.withColumn(col, F.expr(fail_cond))
        hard_fail_flags.append(col)

    any_hard_fail = F.col(hard_fail_flags[0])
    for col in hard_fail_flags[1:]:
        any_hard_fail = any_hard_fail | F.col(col)

    parts = [
        f"CASE WHEN ({fail_condition_from_pass_expression(r['expression'])}) "
        f"THEN '{r['name']},' ELSE '' END"
        for r in hard
    ]
    work = work.withColumn("dq_failed_rules", F.expr("CONCAT(" + ", ".join(parts) + ")"))
    work = work.withColumn(
        "dq_failed_rules",
        F.regexp_replace(F.col("dq_failed_rules"), ",$", ""),
    )

    dominant_cases = []
    for rule in hard:
        fail_cond = fail_condition_from_pass_expression(rule["expression"])
        dominant_cases.append(
            f"WHEN ({fail_cond}) THEN '{rule['dimension']}'"
        )
    work = work.withColumn(
        "dq_dominant_dimension",
        F.expr("CASE " + " ".join(dominant_cases) + " ELSE NULL END"),
    )
    work = work.withColumn("dq_run_id", F.lit(run_id))
    work = work.withColumn("dq_engine", F.lit("soda-core"))
    work = work.withColumn("dq_quarantined_at", F.current_timestamp())

    quarantine = work.filter(any_hard_fail)
    clean = work.filter(~any_hard_fail).drop(
        "dq_failed_rules",
        "dq_dominant_dimension",
        "dq_run_id",
        "dq_engine",
        "dq_quarantined_at",
        *hard_fail_flags,
    )
    quarantine = quarantine.drop(*hard_fail_flags)

    # One pass over the data counts violations for every row rule, hard and soft.
    # Without per-rule counts the scorecard can only derive a binary from the
    # aggregate quarantine rate, which marks every hard rule failed whenever a
    # single row is quarantined.
    agg_exprs = [F.count(F.lit(1)).alias("_total")]
    for rule in (*hard, *soft):
        fail_cond = fail_condition_from_pass_expression(rule["expression"])
        agg_exprs.append(
            F.sum(F.expr(f"CASE WHEN ({fail_cond}) THEN 1 ELSE 0 END")).alias(
                f"_n_{rule['name']}"
            )
        )
    stats = df.agg(*agg_exprs).collect()[0]
    total = int(stats["_total"] or 0)

    rule_fail_counts: dict[str, int] = {}
    rule_pass_rates: dict[str, float] = {}
    for rule in (*hard, *soft):
        failed = int(stats[f"_n_{rule['name']}"] or 0)
        rule_fail_counts[rule["name"]] = failed
        rule_pass_rates[rule["name"]] = ((total - failed) / total) if total else 0.0

    soft_metrics = {rule["name"]: rule_pass_rates[rule["name"]] for rule in soft}
    for rule in (*hard, *soft):
        logger.info(
            "RULE severity=%s rule=%s dimension=%s failed=%s pass_rate=%.6f run_id=%s",
            rule.get("severity", "error"),
            rule["name"],
            rule["dimension"],
            rule_fail_counts[rule["name"]],
            rule_pass_rates[rule["name"]],
            run_id,
        )

    q_count = quarantine.count()
    c_count = clean.count()
    if total == 0:
        raise RuntimeError(f"FAILED empty input to Soda gate run_id={run_id}")

    summary = {
        "input_rows": total,
        "clean_rows": c_count,
        "quarantine_rows": q_count,
        "quarantine_rate": (q_count / total) if total else 0.0,
        "soft_pass_rates": soft_metrics,
        "rule_fail_counts": rule_fail_counts,
        "rule_pass_rates": rule_pass_rates,
        "engine": "soda-core",
    }
    logger.info(
        "SODA_GATE run_id=%s input=%s clean=%s quarantine=%s",
        run_id,
        total,
        c_count,
        q_count,
    )
    return clean, quarantine, summary


def outcomes_to_validation_rows(
    outcomes: list[SodaCheckOutcome],
    *,
    run_id: str,
    soft_pass_rates: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Build rows for governance.dq_validation_result from Soda outcomes."""
    soft_pass_rates = soft_pass_rates or {}
    captured_at = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    for o in outcomes:
        measured = o.measured
        if measured is None:
            measured = soft_pass_rates.get(o.name)
        if measured is None and o.outcome in ("pass", "fail", "warn"):
            measured = 1.0 if o.outcome == "pass" else 0.0
        # Soft rules report their rate but never block: the gate keeps the rows.
        passed = True if o.severity == "warning" else (o.outcome == "pass")
        rows.append(
            {
                "run_id": run_id,
                "rule": o.name,
                "dimension": o.dimension,
                "scope": o.scope,
                "severity": o.severity,
                "passed": passed,
                "measured": float(measured) if measured is not None else None,
                "threshold": o.threshold,
                "captured_at": captured_at,
            }
        )
    return rows


def apply_soda_gate(
    spark: "SparkSession",
    df: "DataFrame",
    contract: dict[str, Any],
    *,
    run_id: str,
    sodacl_path: str | Path | None = None,
) -> SodaGateResult:
    """
    Full gate: run Soda scan → map check outcomes → materialize multi-rule quarantine.
    Soft (warning) Soda checks never remove rows from clean.
    """
    path = Path(sodacl_path or DEFAULT_SODA_CHECKS)
    if not path.exists():
        write_sodacl_from_contract(contract, path)
        logger.warning("Generated missing SodaCL from contract at %s", path)

    sodacl_yaml = path.read_text(encoding="utf-8")
    exit_code, logs, scan = run_soda_scan(
        spark,
        df,
        sodacl_yaml=sodacl_yaml,
        scan_definition_name=f"taxi_trips_dq_{run_id}",
    )
    outcomes = map_scan_to_outcomes(scan, contract, sodacl_yaml=sodacl_yaml)

    # If Scan did not expose per-check objects, synthesize from quarantine metrics after materialize
    clean, quarantine, summary = materialize_quarantine(
        spark, df, contract, run_id=run_id
    )

    if not outcomes or all(o.outcome == "unknown" for o in outcomes):
        outcomes = _synthesize_outcomes_from_summary(contract, summary)

    # Measurements come from the single-pass counts for every row rule, so the
    # scorecard is identical whether or not the Scan API exposed check objects.
    pass_rates = summary.get("rule_pass_rates") or {}
    fail_counts = summary.get("rule_fail_counts") or {}
    for o in outcomes:
        if o.name not in pass_rates:
            continue
        o.measured = pass_rates[o.name]
        o.threshold = 1.0
        clean_rule = fail_counts[o.name] == 0
        if o.severity == "warning":
            o.outcome = "pass" if clean_rule else "warn"
        else:
            o.outcome = "pass" if clean_rule else "fail"

    summary["soda_exit_code"] = exit_code
    summary["soda_check_outcomes"] = [
        {"name": o.name, "outcome": o.outcome, "severity": o.severity, "dimension": o.dimension}
        for o in outcomes
    ]

    hard_failed = [
        o.name for o in outcomes if o.severity == "error" and o.outcome == "fail"
    ]
    if hard_failed:
        logger.error(
            "SODA hard checks failed=%s run_id=%s rows_quarantine=%s",
            hard_failed,
            run_id,
            summary["quarantine_rows"],
        )

    return SodaGateResult(
        clean=clean,
        quarantine=quarantine,
        summary=summary,
        check_outcomes=outcomes,
        scan_exit_code=exit_code,
        scan_logs=logs,
    )


def _synthesize_outcomes_from_summary(
    contract: dict[str, Any],
    summary: dict[str, Any],
) -> list[SodaCheckOutcome]:
    """When Scan API is opaque, derive outcomes from the per-rule violation counts."""
    outcomes: list[SodaCheckOutcome] = []
    fail_counts = summary.get("rule_fail_counts") or {}
    pass_rates = summary.get("rule_pass_rates") or {}
    for severity, failed_outcome in (("error", "fail"), ("warning", "warn")):
        for rule in row_rules(contract, severity=severity):
            name = rule["name"]
            outcomes.append(
                SodaCheckOutcome(
                    name=name,
                    outcome="pass" if fail_counts.get(name, 0) == 0 else failed_outcome,
                    severity=severity,
                    dimension=rule["dimension"],
                    measured=pass_rates.get(name),
                    threshold=1.0,
                )
            )
    return outcomes
