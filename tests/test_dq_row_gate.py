"""Intent: hard rules quarantine; soft passenger_count does NOT remove from clean.

Uses soda_runner.materialize_quarantine (Soda fail predicates) so tests run without
a full Soda scan when JVM is available; full apply_row_gate needs soda-core.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.lib.config import DEFAULT_CONTRACT_PATH, DEFAULT_SODA_CHECKS_PATH
from src.lib.contract import load_contract

pyspark = pytest.importorskip("pyspark", reason="PySpark not installed")

try:
    from pyspark.sql import SparkSession
except Exception as exc:  # pragma: no cover
    pytest.skip(f"PySpark unavailable: {exc}", allow_module_level=True)


@pytest.fixture(scope="module")
def spark():
    try:
        session = (
            SparkSession.builder.master("local[1]")
            .appName("test_dq_row_gate")
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


def _base_rows(spark):
    from datetime import datetime

    data = [
        (1, 2.0, 12.5, datetime(2023, 5, 1, 10, 0), datetime(2023, 5, 1, 10, 30), "yellow", "2023-05"),
        (1, None, 10.0, datetime(2023, 5, 1, 11, 0), datetime(2023, 5, 1, 11, 20), "yellow", "2023-05"),
        (2, 0.0, 9.0, datetime(2023, 5, 1, 12, 0), datetime(2023, 5, 1, 12, 15), "green", "2023-05"),
        (1, 1.0, -5.0, datetime(2023, 5, 1, 13, 0), datetime(2023, 5, 1, 13, 10), "yellow", "2023-05"),
        (1, 1.0, 8.0, datetime(2023, 5, 1, 14, 0), datetime(2023, 5, 1, 13, 0), "yellow", "2023-05"),
        (None, 1.0, 8.0, datetime(2023, 5, 1, 15, 0), datetime(2023, 5, 1, 15, 10), "yellow", "2023-05"),
        (1, 1.0, -1.0, datetime(2023, 5, 1, 16, 0), datetime(2023, 5, 1, 16, 10), "pink", "2023-05"),
    ]
    return spark.createDataFrame(
        data,
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


def test_soft_passenger_count_does_not_quarantine_because_protects_q2(spark, contract):
    from src.lib.soda_runner import materialize_quarantine

    df = _base_rows(spark)
    clean, quarantine, summary = materialize_quarantine(
        spark, df, contract, run_id="test-soft"
    )
    soft_in_clean = clean.filter(
        (clean.passenger_count.isNull()) | (clean.passenger_count == 0)
    ).count()
    assert soft_in_clean == 2
    assert summary["clean_rows"] >= 3
    assert summary["engine"] == "soda-core"


def test_soft_negative_amount_stays_in_clean_because_tlc_adjustments(spark, contract):
    from src.lib.soda_runner import materialize_quarantine

    df = _base_rows(spark)
    clean, quarantine, _ = materialize_quarantine(
        spark, df, contract, run_id="test-soft-amount"
    )
    negative_in_clean = clean.filter(clean.total_amount < 0).count()
    assert negative_in_clean >= 1
    bad = quarantine.filter(quarantine.total_amount < 0)
    assert bad.count() == 0


def test_multi_rule_quarantine_lists_all_failed_rules(spark, contract):
    from src.lib.soda_runner import materialize_quarantine

    df = _base_rows(spark)
    _, quarantine, _ = materialize_quarantine(spark, df, contract, run_id="test-multi")
    pink = [r for r in quarantine.collect() if r["taxi_type"] == "pink"]
    assert len(pink) == 1
    failed = pink[0]["dq_failed_rules"]
    assert "taxi_type_valid" in failed
    assert "total_amount_non_negative" not in failed


def test_apply_row_gate_uses_soda_scan_when_available(spark, contract):
    """Mock Soda Scan so gate path is covered without soda-core installed."""
    fake_scan = MagicMock()
    fake_scan._checks = []

    with patch(
        "src.lib.soda_runner.run_soda_scan",
        return_value=(0, "ok", fake_scan),
    ):
        from src.lib.dq_engine import apply_row_gate

        df = _base_rows(spark)
        clean, quarantine, summary = apply_row_gate(
            spark, df, contract, run_id="test-mocked-soda"
        )
    assert summary.get("engine") == "soda-core"
    assert clean.count() + quarantine.count() == df.count()
    assert "soda_validation_rows" in summary