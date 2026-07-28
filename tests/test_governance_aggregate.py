"""Intent: aggregate scorecard dims and quarantine_rate metrics evaluate correctly."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.lib.config import DEFAULT_CONTRACT_PATH
from src.lib.contract import load_contract

pytest.importorskip("pyspark", reason="PySpark not installed")

try:
    from pyspark.sql import SparkSession
except Exception as exc:  # pragma: no cover
    pytest.skip(f"PySpark unavailable: {exc}", allow_module_level=True)


@pytest.fixture(scope="module")
def spark():
    try:
        session = (
            SparkSession.builder.master("local[1]")
            .appName("test_governance_aggregate")
            .config("spark.ui.enabled", "false")
            .config("spark.sql.shuffle.partitions", "1")
            .getOrCreate()
        )
        session.sparkContext.setLogLevel("ERROR")
    except Exception as exc:
        pytest.skip(f"JVM/Spark not available: {exc}")
    yield session
    session.stop()


@pytest.fixture(scope="module")
def contract():
    return load_contract(DEFAULT_CONTRACT_PATH)


def test_month_coverage_passes_when_five_months_present(spark, contract):
    from src.lib.governance_engine import evaluate_aggregates

    rows = []
    for i, ym in enumerate(["2023-01", "2023-02", "2023-03", "2023-04", "2023-05"]):
        rows.append(
            (
                1,
                1.0,
                10.0,
                datetime(2023, i + 1, 1, 10, 0),
                datetime(2023, i + 1, 1, 10, 30),
                "yellow",
                ym,
            )
        )
    clean = spark.createDataFrame(
        rows,
        [
            "vendor_id",
            "passenger_count",
            "total_amount",
            "pickup_datetime",
            "dropoff_datetime",
            "taxi_type",
            "year_month",
        ],
    )
    quar = spark.createDataFrame([], clean.schema)
    result, failed = evaluate_aggregates(
        spark, clean, quar, contract, run_id="agg-1", gate_summary={}
    )
    month_rule = [r for r in result.collect() if r["rule"] == "month_coverage"][0]
    assert month_rule["passed"] is True
    assert month_rule["dimension"] == "completeness"
    assert "month_coverage" not in failed


def test_scorecard_includes_dama_dimensions(spark, contract):
    from src.lib.governance_engine import evaluate_aggregates

    clean = spark.createDataFrame(
        [
            (1, 1.0, 10.0, datetime(2023, 1, 1, 10, 0), datetime(2023, 1, 1, 10, 30), "yellow", "2023-01"),
            (1, 1.0, 10.0, datetime(2023, 2, 1, 10, 0), datetime(2023, 2, 1, 10, 30), "yellow", "2023-02"),
            (1, 1.0, 10.0, datetime(2023, 3, 1, 10, 0), datetime(2023, 3, 1, 10, 30), "yellow", "2023-03"),
            (1, 1.0, 10.0, datetime(2023, 4, 1, 10, 0), datetime(2023, 4, 1, 10, 30), "yellow", "2023-04"),
            (1, 1.0, 10.0, datetime(2023, 5, 1, 10, 0), datetime(2023, 5, 1, 10, 30), "yellow", "2023-05"),
        ],
        [
            "vendor_id",
            "passenger_count",
            "total_amount",
            "pickup_datetime",
            "dropoff_datetime",
            "taxi_type",
            "year_month",
        ],
    )
    quar = spark.createDataFrame([], clean.schema)
    result, _ = evaluate_aggregates(
        spark,
        clean,
        quar,
        contract,
        run_id="agg-2",
        gate_summary={"soft_pass_rates": {"passenger_count_range": 0.8}},
    )
    dims = {r["dimension"] for r in result.collect()}
    assert "completeness" in dims
    assert "uniqueness" in dims or "accuracy" in dims
    assert any(r["rule"] == "passenger_count_range" for r in result.collect())
    assert not any(r["dimension"] == "timeliness" for r in result.collect())
