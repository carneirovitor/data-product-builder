"""Intent: fitness_for_use fails loud when Q1 months or Q2 hours insufficient."""

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
            .appName("test_fitness")
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


def test_fitness_passes_when_q1_five_months_and_q2_ge_20_hours(spark, contract):
    from src.lib.governance_engine import evaluate_fitness

    rows = []
    for m in range(1, 6):
        rows.append(
            (1, 1.0, 10.0, datetime(2023, m, 1, 8, 0), datetime(2023, m, 1, 8, 30), "yellow", f"2023-0{m}")
        )
    for hour in range(20):
        rows.append(
            (
                1,
                2.0,
                11.0,
                datetime(2023, 5, 2, hour, 0),
                datetime(2023, 5, 2, hour, 20),
                "green",
                "2023-05",
            )
        )
    df = spark.createDataFrame(
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
    result, failed = evaluate_fitness(spark, df, contract, run_id="fit-ok")
    assert failed == []
    assert all(r["passed"] for r in result.collect())


def test_fitness_fails_loud_when_q2_hours_below_threshold(spark, contract):
    from src.lib.governance_engine import evaluate_fitness

    rows = []
    for m in range(1, 6):
        rows.append(
            (1, 1.0, 10.0, datetime(2023, m, 1, 8, 0), datetime(2023, m, 1, 8, 30), "yellow", f"2023-0{m}")
        )
    # Only 3 hours in May — below threshold 20
    for hour in range(3):
        rows.append(
            (
                1,
                2.0,
                11.0,
                datetime(2023, 5, 2, hour, 0),
                datetime(2023, 5, 2, hour, 20),
                "yellow",
                "2023-05",
            )
        )
    df = spark.createDataFrame(
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
    result, failed = evaluate_fitness(spark, df, contract, run_id="fit-bad")
    assert "q2_hours_coverage" in failed
    q2 = [r for r in result.collect() if r["rule"] == "q2_hours_coverage"][0]
    assert q2["passed"] is False
    assert q2["measured"] == 3.0
