"""Intent: SQL models stay portable across catalogs and never ship a stale placeholder."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.lib.config import (
    CLEAN_MODEL_PATH,
    CONSUMPTION_MODEL_PATH,
    GOVERNANCE_VIEWS_DIR,
    METRICS_DIR,
    Config,
)
from src.lib.sql_runner import render_sql


def _config(catalog: str) -> Config:
    return Config(
        run_id="r1",
        catalog=catalog,
        landing_path="/tmp",
        contract_path=Path("/tmp/contract.yaml"),
        product_path=Path("/tmp/product.yaml"),
        local_warehouse="/tmp/warehouse",
    )


def _all_models() -> list[Path]:
    return [
        CLEAN_MODEL_PATH,
        CONSUMPTION_MODEL_PATH,
        *sorted(METRICS_DIR.glob("*.sql")),
        *sorted(GOVERNANCE_VIEWS_DIR.glob("*.sql")),
    ]


@pytest.mark.parametrize("model", _all_models(), ids=lambda p: p.stem)
def test_every_model_resolves_on_unity_catalog(model):
    sql = render_sql(model, _config("workspace"))
    assert "${" not in sql
    assert "workspace." in sql


@pytest.mark.parametrize("model", _all_models(), ids=lambda p: p.stem)
def test_every_model_resolves_locally_where_catalog_is_empty(model):
    sql = render_sql(model, _config(""))
    assert "${" not in sql
    # The prefix collapses instead of leaving a dangling dot before the schema
    assert ".raw." not in sql and ".clean." not in sql


def test_unresolved_placeholder_fails_loud_because_it_reaches_spark_as_syntax_error(tmp_path):
    model = tmp_path / "broken.sql"
    model.write_text("SELECT id FROM ${catalog}.raw.t WHERE d = '${missing}'")

    with pytest.raises(ValueError, match=r"\$\{missing\}"):
        render_sql(model, _config("workspace"))
