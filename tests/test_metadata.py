"""Intent: contract semantics (comments + classification/PII/business_term tags) land in metastore SQL."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.lib.config import DEFAULT_CONTRACT_PATH, DEFAULT_PRODUCT_PATH
from src.lib.contract import load_contract
from src.lib.metadata import (
    _field_tag_map,
    apply_schema_semantics,
    load_product,
)


@pytest.fixture(scope="module")
def contract():
    return load_contract(DEFAULT_CONTRACT_PATH)


@pytest.fixture(scope="module")
def product():
    return load_product(DEFAULT_PRODUCT_PATH)


def test_apply_schema_semantics_emits_table_and_column_comments(contract, product):
    spark = MagicMock()
    apply_schema_semantics(
        spark, "workspace.consumption.taxi_trips", contract, model_name="taxi_trips", product=product
    )
    statements = [call.args[0] for call in spark.sql.call_args_list]
    assert any(s.startswith("COMMENT ON TABLE workspace.consumption.taxi_trips IS") for s in statements)
    assert any("COMMENT ON COLUMN workspace.consumption.taxi_trips.total_amount IS" in s for s in statements)
    assert any("COMMENT ON COLUMN workspace.consumption.taxi_trips.vendor_id IS" in s for s in statements)
    assert any("does not include cash tips" in s for s in statements)


def test_apply_schema_semantics_emits_classification_and_business_term_tags(contract, product):
    spark = MagicMock()
    apply_schema_semantics(
        spark, "workspace.consumption.taxi_trips", contract, model_name="taxi_trips", product=product
    )
    statements = [call.args[0] for call in spark.sql.call_args_list]
    assert any("SET TAGS" in s and "contains_pii" in s for s in statements)
    assert any(
        "ALTER COLUMN total_amount SET TAGS" in s and "business_term" in s and "trip_total_fare" in s
        for s in statements
    )
    assert any("ALTER COLUMN passenger_count SET TAGS" in s and "pii" in s for s in statements)


def test_field_tag_map_from_contract(contract):
    fields = contract["models"]["taxi_trips"]["fields"]
    tags = _field_tag_map(fields["total_amount"])
    assert tags["classification"] == "public"
    assert tags["pii"] == "false"
    assert tags["business_term"] == "trip_total_fare"


def test_model_field_descriptions_present_in_contract(contract):
    fields = contract["models"]["taxi_trips"]["fields"]
    assert "lpep" in fields["pickup_datetime"]["description"].lower()
    assert "driver-entered" in fields["passenger_count"]["description"].lower()
    vendor_desc = fields["vendor_id"]["description"]
    assert "1 =" in vendor_desc
    assert "7 =" in vendor_desc or "Helix" in vendor_desc
    assert fields["vendor_id"]["pii"] is False
    assert contract["models"]["taxi_trips"]["contains_pii"] is False
