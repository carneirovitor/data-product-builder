"""Profiling, aggregate DQ, fitness-for-use, scorecard persistence — one engine."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from src.lib.config import CONSUMPTION_CDES, GOVERNANCE_VIEWS_DIR, YEAR_MONTHS
from src.lib.contract import aggregate_rules, fitness_rules, profiling_spec
from src.lib.sql_runner import create_views_from_dir

if TYPE_CHECKING:
    from pyspark.sql import DataFrame, SparkSession

logger = logging.getLogger(__name__)


def _now_ts():
    return datetime.now(timezone.utc)


def profile_dataframe(
    spark: "SparkSession",
    df: "DataFrame",
    contract: dict[str, Any],
    *,
    run_id: str,
    layer: str,
    table: str,
    partition_key: str | None = None,
) -> "DataFrame":
    """Native Spark profiling for contract-declared columns/metrics only."""
    from pyspark.sql import Row
    from pyspark.sql import functions as F
    from pyspark.sql import types as T

    spec = profiling_spec(contract)
    columns = [c for c in (spec.get("columns") or []) if c in df.columns]
    metrics = set(spec.get("metrics") or ["row_count", "null_rate", "min", "max", "avg"])
    captured_at = _now_ts()
    rows: list[Row] = []

    row_count = df.count()
    if "row_count" in metrics:
        rows.append(
            Row(
                run_id=run_id,
                layer=layer,
                table_name=table,
                column_name="*",
                metric="row_count",
                metric_value=float(row_count),
                partition_key=partition_key,
                captured_at=captured_at,
            )
        )

    for col in columns:
        if "null_rate" in metrics:
            nulls = df.filter(F.col(col).isNull()).count()
            rate = (nulls / row_count) if row_count else 0.0
            rows.append(
                Row(
                    run_id=run_id,
                    layer=layer,
                    table_name=table,
                    column_name=col,
                    metric="null_rate",
                    metric_value=float(rate),
                    partition_key=partition_key,
                    captured_at=captured_at,
                )
            )
        # min/max/avg only for numeric-ish; timestamps get min/max via cast string skip avg
        dtype = dict(df.dtypes).get(col, "")
        if dtype in ("int", "bigint", "double", "float", "long", "short"):
            try:
                # take() is more reliable than collect() on some serverless runtimes
                taken = (
                    df.agg(
                        F.min(col).alias("mn"),
                        F.max(col).alias("mx"),
                        F.avg(col).alias("av"),
                    ).take(1)
                )
                if not taken:
                    continue
                agg = taken[0]
            except Exception as exc:
                logger.warning(
                    "Skipping numeric profile for %s.%s: %s", table, col, exc
                )
                continue
            if "min" in metrics and agg["mn"] is not None:
                rows.append(
                    Row(
                        run_id=run_id,
                        layer=layer,
                        table_name=table,
                        column_name=col,
                        metric="min",
                        metric_value=float(agg["mn"]),
                        partition_key=partition_key,
                        captured_at=captured_at,
                    )
                )
            if "max" in metrics and agg["mx"] is not None:
                rows.append(
                    Row(
                        run_id=run_id,
                        layer=layer,
                        table_name=table,
                        column_name=col,
                        metric="max",
                        metric_value=float(agg["mx"]),
                        partition_key=partition_key,
                        captured_at=captured_at,
                    )
                )
            if "avg" in metrics and agg["av"] is not None:
                rows.append(
                    Row(
                        run_id=run_id,
                        layer=layer,
                        table_name=table,
                        column_name=col,
                        metric="avg",
                        metric_value=float(agg["av"]),
                        partition_key=partition_key,
                        captured_at=captured_at,
                    )
                )

    schema = T.StructType(
        [
            T.StructField("run_id", T.StringType(), False),
            T.StructField("layer", T.StringType(), False),
            T.StructField("table_name", T.StringType(), False),
            T.StructField("column_name", T.StringType(), False),
            T.StructField("metric", T.StringType(), False),
            T.StructField("metric_value", T.DoubleType(), True),
            T.StructField("partition_key", T.StringType(), True),
            T.StructField("captured_at", T.TimestampType(), False),
        ]
    )
    out = spark.createDataFrame(rows, schema=schema)
    logger.info(
        "PROFILE layer=%s table=%s metrics=%s run_id=%s",
        layer,
        table,
        len(rows),
        run_id,
    )
    return out


def _compare(measured: float, threshold: float, comparator: str) -> bool:
    if comparator in ("gte", ">="):
        return measured >= threshold
    if comparator in ("lte", "<="):
        return measured <= threshold
    if comparator in ("eq", "=="):
        return measured == threshold
    if comparator in ("gt", ">"):
        return measured > threshold
    if comparator in ("lt", "<"):
        return measured < threshold
    raise ValueError(f"Unknown comparator: {comparator}")


def evaluate_aggregates(
    spark: "SparkSession",
    clean_df: "DataFrame",
    quarantine_df: "DataFrame",
    contract: dict[str, Any],
    *,
    run_id: str,
    gate_summary: dict[str, Any] | None = None,
) -> tuple["DataFrame", list[str]]:
    """Evaluate aggregate quality rules; return results DF and list of failed error rules."""
    from pyspark.sql import Row
    from pyspark.sql import functions as F
    from pyspark.sql import types as T

    captured_at = _now_ts()
    results: list[Row] = []
    failed_errors: list[str] = []
    gate_summary = gate_summary or {}

    clean_count = clean_df.count()
    q_count = quarantine_df.count()
    total = clean_count + q_count
    quarantine_rate = (q_count / total) if total else 0.0

    distinct_months = 0
    if "year_month" in clean_df.columns and clean_count:
        distinct_months = clean_df.select("year_month").distinct().count()

    duplicate_rate = 0.0
    key_cols = [
        c
        for c in (
            "taxi_type",
            "vendor_id",
            "pickup_datetime",
            "dropoff_datetime",
            "total_amount",
        )
        if c in clean_df.columns
    ]
    if key_cols and clean_count:
        distinct_keys = clean_df.select(*key_cols).distinct().count()
        duplicate_rate = 1.0 - (distinct_keys / clean_count)

    volume_anomaly_ratio = 1.0
    if "year_month" in clean_df.columns and clean_count:
        try:
            monthly_pdf = (
                clean_df.groupBy("year_month")
                .count()
                .orderBy("year_month")
                .toPandas()
            )
            counts = monthly_pdf["count"].tolist() if len(monthly_pdf) else []
            if counts:
                sorted_c = sorted(counts)
                median = sorted_c[len(sorted_c) // 2]
                if median > 0:
                    volume_anomaly_ratio = min(counts) / median
        except Exception as exc:
            logger.warning("volume anomaly metric skipped: %s", exc)

    metric_values = {
        "distinct_year_month": float(distinct_months),
        "quarantine_rate": float(quarantine_rate),
        "duplicate_rate": float(duplicate_rate),
        "volume_anomaly_ratio": float(volume_anomaly_ratio),
    }

    for rule in aggregate_rules(contract):
        metric = rule.get("metric")
        measured = metric_values.get(metric)
        if measured is None:
            logger.warning("Unknown aggregate metric=%s rule=%s", metric, rule["name"])
            continue
        threshold = float(rule.get("threshold"))
        comparator = rule.get("comparator", "gte")
        passed = _compare(measured, threshold, comparator)
        severity = rule.get("severity", "warning")
        results.append(
            Row(
                run_id=run_id,
                rule=rule["name"],
                dimension=rule["dimension"],
                scope="aggregate",
                severity=severity,
                passed=passed,
                measured=float(measured),
                threshold=threshold,
                captured_at=captured_at,
            )
        )
        if not passed and severity == "error":
            failed_errors.append(rule["name"])
            logger.error(
                "FAILED rule=%s dimension=%s run_id=%s measured=%s threshold=%s",
                rule["name"],
                rule["dimension"],
                run_id,
                measured,
                threshold,
            )
        else:
            logger.info(
                "AGG rule=%s passed=%s measured=%s threshold=%s run_id=%s",
                rule["name"],
                passed,
                measured,
                threshold,
                run_id,
            )

    # Persist soft row pass rates as validation rows if provided
    for name, rate in (gate_summary.get("soft_pass_rates") or {}).items():
        soft_rule = next(
            (
                r
                for r in (contract.get("quality") or [])
                if r.get("name") == name
            ),
            None,
        )
        dim = soft_rule["dimension"] if soft_rule else "validity"
        results.append(
            Row(
                run_id=run_id,
                rule=name,
                dimension=dim,
                scope="row",
                severity="warning",
                passed=True,
                measured=float(rate),
                threshold=None,
                captured_at=captured_at,
            )
        )

    # Hard row quarantine rate as informational accuracy row
    results.append(
        Row(
            run_id=run_id,
            rule="hard_quarantine_rate",
            dimension="accuracy",
            scope="aggregate",
            severity="warning",
            passed=True,
            measured=float(quarantine_rate),
            threshold=None,
            captured_at=captured_at,
        )
    )

    schema = T.StructType(
        [
            T.StructField("run_id", T.StringType(), False),
            T.StructField("rule", T.StringType(), False),
            T.StructField("dimension", T.StringType(), False),
            T.StructField("scope", T.StringType(), False),
            T.StructField("severity", T.StringType(), False),
            T.StructField("passed", T.BooleanType(), False),
            T.StructField("measured", T.DoubleType(), True),
            T.StructField("threshold", T.DoubleType(), True),
            T.StructField("captured_at", T.TimestampType(), False),
        ]
    )
    return spark.createDataFrame(results, schema=schema), failed_errors


def evaluate_fitness(
    spark: "SparkSession",
    consumption_df: "DataFrame",
    contract: dict[str, Any],
    *,
    run_id: str,
) -> tuple["DataFrame", list[str]]:
    """Fitness for use against consumption layer for Q1/Q2 readiness."""
    from pyspark.sql import Row
    from pyspark.sql import functions as F
    from pyspark.sql import types as T

    captured_at = _now_ts()
    results: list[Row] = []
    failed: list[str] = []

    # Q1: yellow avg by month — distinct months with yellow
    q1_months = 0
    if "taxi_type" in consumption_df.columns and "year_month" in consumption_df.columns:
        q1_months = (
            consumption_df.filter(F.col("taxi_type") == "yellow")
            .select("year_month")
            .distinct()
            .count()
        )

    # Q2: May hours with any trip (fleet)
    q2_hours = 0
    if "pickup_datetime" in consumption_df.columns:
        may = consumption_df.filter(
            (F.col("year_month") == "2023-05")
            if "year_month" in consumption_df.columns
            else F.month("pickup_datetime") == 5
        )
        q2_hours = (
            may.select(F.hour("pickup_datetime").alias("hr"))
            .distinct()
            .count()
        )

    cde_ok = 1.0 if all(c in consumption_df.columns for c in CONSUMPTION_CDES) else 0.0

    measured_map = {
        "q1_month_count": float(q1_months),
        "q2_hour_count": float(q2_hours),
        "cde_columns_present": float(cde_ok),
    }

    for rule in fitness_rules(contract):
        metric = rule["metric"]
        measured = measured_map.get(metric, 0.0)
        threshold = float(rule["threshold"])
        comparator = rule.get("comparator", "gte")
        passed = _compare(measured, threshold, comparator)
        severity = rule.get("severity", "error")
        results.append(
            Row(
                run_id=run_id,
                use_case=rule.get("use_case", rule["name"]),
                rule=rule["name"],
                passed=passed,
                measured=float(measured),
                expected=threshold,
                captured_at=captured_at,
            )
        )
        if not passed and severity == "error":
            failed.append(rule["name"])
            logger.error(
                "FAILED fitness rule=%s use_case=%s run_id=%s measured=%s expected=%s",
                rule["name"],
                rule.get("use_case"),
                run_id,
                measured,
                threshold,
            )
        else:
            logger.info(
                "FITNESS rule=%s passed=%s measured=%s run_id=%s",
                rule["name"],
                passed,
                measured,
                run_id,
            )

    schema = T.StructType(
        [
            T.StructField("run_id", T.StringType(), False),
            T.StructField("use_case", T.StringType(), False),
            T.StructField("rule", T.StringType(), False),
            T.StructField("passed", T.BooleanType(), False),
            T.StructField("measured", T.DoubleType(), True),
            T.StructField("expected", T.DoubleType(), True),
            T.StructField("captured_at", T.TimestampType(), False),
        ]
    )
    return spark.createDataFrame(results, schema=schema), failed


def append_governance(df: "DataFrame", fqn: str) -> None:
    df.write.format("delta").mode("append").option("mergeSchema", "true").saveAsTable(fqn)


def create_governance_views(spark: "SparkSession", config) -> None:
    """Scorecard / monitor views, defined in platform/governance/views/*.sql."""
    # fitness_for_use_result is only written by publish_consumption, so build_clean
    # needs the empty shell to exist before vw_fitness_summary can reference it.
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {config.fqn('governance', 'fitness_for_use_result')} (
          run_id STRING,
          use_case STRING,
          rule STRING,
          passed BOOLEAN,
          measured DOUBLE,
          expected DOUBLE,
          captured_at TIMESTAMP
        ) USING DELTA
        """
    )

    created = create_views_from_dir(
        spark, GOVERNANCE_VIEWS_DIR, config, schema="governance"
    )
    logger.info("GOVERNANCE views=%s", len(created))
