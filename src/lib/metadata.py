"""Ownership + semantics metadata — comments, TBLPROPERTIES, UC tags from contract/product."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from pyspark.sql import SparkSession

from src.lib.config import Config

logger = logging.getLogger(__name__)

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TAG_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _escape_sql_literal(text: str) -> str:
    return str(text).replace("'", "''")


def _normalize_comment(text: str) -> str:
    """Fold YAML multiline descriptions into a single-line SQL comment."""
    return re.sub(r"\s+", " ", str(text)).strip()


def load_product(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data.get("product") or data


def _field_tag_map(field_def: dict[str, Any]) -> dict[str, str]:
    """Build UC tag key→value from contract field classification / pii / business_term / tags."""
    tags: dict[str, str] = {}
    if field_def.get("classification") is not None:
        tags["classification"] = str(field_def["classification"]).lower()
    if "pii" in field_def:
        tags["pii"] = str(field_def["pii"]).lower()
    if field_def.get("business_term"):
        tags["business_term"] = str(field_def["business_term"])
    raw_tags = field_def.get("tags") or []
    if isinstance(raw_tags, list):
        for item in raw_tags:
            if isinstance(item, str) and item:
                # allow "key:value" or bare key → true
                if ":" in item:
                    key, _, val = item.partition(":")
                    key, val = key.strip(), val.strip()
                    if key:
                        tags[key] = val or "true"
                else:
                    tags[item.strip()] = "true"
    return {k: v for k, v in tags.items() if _TAG_KEY.match(k)}


def _table_tag_map(
    contract: dict[str, Any] | None,
    product: dict[str, Any] | None,
    model: dict[str, Any] | None,
) -> dict[str, str]:
    tags: dict[str, str] = {}
    domain = (product or {}).get("domain") or (contract or {}).get("info", {}).get("domain")
    if domain:
        tags["domain"] = str(domain)
    if model and model.get("classification"):
        tags["classification"] = str(model["classification"]).lower()
    if model and "contains_pii" in model:
        tags["contains_pii"] = str(model["contains_pii"]).lower()
    elif model and "pii" in model:
        tags["contains_pii"] = str(model["pii"]).lower()

    product_tags = (product or {}).get("tags") or []
    if isinstance(product_tags, list):
        for item in product_tags:
            if isinstance(item, dict):
                for k, v in item.items():
                    if _TAG_KEY.match(str(k)):
                        tags[str(k)] = str(v).lower() if isinstance(v, bool) else str(v)
            elif isinstance(item, str) and item:
                if ":" in item:
                    key, _, val = item.partition(":")
                    key, val = key.strip(), val.strip()
                    if _TAG_KEY.match(key):
                        tags[key] = val or "true"
                elif _TAG_KEY.match(item.replace("-", "_")):
                    tags[item.replace("-", "_")] = "true"
    return tags


def _set_table_tags(spark: "SparkSession", fqn: str, tags: dict[str, str]) -> None:
    if not tags:
        return
    pairs = ", ".join(f"'{_escape_sql_literal(k)}' = '{_escape_sql_literal(v)}'" for k, v in tags.items())
    sql = f"ALTER TABLE {fqn} SET TAGS ({pairs})"
    try:
        spark.sql(sql)
        logger.info("UC table tags applied on %s: %s", fqn, list(tags))
    except Exception as exc:  # noqa: BLE001 — UC tag support varies by edition
        logger.warning("SET TAGS failed on %s (%s); mirroring to TBLPROPERTIES tag.*", fqn, exc)
        for key, value in tags.items():
            prop = f"tag.{key}".replace("'", "")
            safe = _escape_sql_literal(value)
            spark.sql(f"ALTER TABLE {fqn} SET TBLPROPERTIES ('{prop}' = '{safe}')")


def _set_column_tags(
    spark: "SparkSession", fqn: str, col_name: str, tags: dict[str, str]
) -> None:
    if not tags:
        return
    pairs = ", ".join(f"'{_escape_sql_literal(k)}' = '{_escape_sql_literal(v)}'" for k, v in tags.items())
    sql = f"ALTER TABLE {fqn} ALTER COLUMN {col_name} SET TAGS ({pairs})"
    try:
        spark.sql(sql)
        logger.debug("UC column tags on %s.%s: %s", fqn, col_name, tags)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "COLUMN SET TAGS failed on %s.%s (%s); mirroring to TBLPROPERTIES",
            fqn,
            col_name,
            exc,
        )
        for key, value in tags.items():
            prop = f"column.{col_name}.{key}".replace("'", "")
            safe = _escape_sql_literal(value)
            spark.sql(f"ALTER TABLE {fqn} SET TBLPROPERTIES ('{prop}' = '{safe}')")


def apply_schema_semantics(
    spark: "SparkSession",
    fqn: str,
    contract: dict[str, Any],
    *,
    model_name: str = "taxi_trips",
    product: dict[str, Any] | None = None,
) -> None:
    """Apply contract descriptions as comments + classification/PII/business_term as UC tags."""
    models = contract.get("models") or {}
    model = models.get(model_name) or {}
    fields = model.get("fields") or {}

    table_desc = model.get("description")
    if table_desc:
        safe = _escape_sql_literal(_normalize_comment(table_desc))
        spark.sql(f"COMMENT ON TABLE {fqn} IS '{safe}'")
        logger.info("Schema semantics: table comment on %s", fqn)

    table_tags = _table_tag_map(contract, product, model)
    _set_table_tags(spark, fqn, table_tags)

    for col_name, field_def in fields.items():
        if not isinstance(field_def, dict):
            continue
        if not _IDENT.match(col_name):
            logger.warning("Skipping column metadata — invalid identifier %s", col_name)
            continue

        desc = field_def.get("description")
        if desc:
            safe = _escape_sql_literal(_normalize_comment(desc))
            spark.sql(f"COMMENT ON COLUMN {fqn}.{col_name} IS '{safe}'")
            logger.info("Schema semantics: column comment on %s.%s", fqn, col_name)

        col_tags = _field_tag_map(field_def)
        _set_column_tags(spark, fqn, col_name, col_tags)


def apply_semantics_for_objects(
    spark: "SparkSession",
    fqns: list[str],
    contract: dict[str, Any],
    *,
    product: dict[str, Any] | None = None,
) -> list[str]:
    """Apply contract semantics to each object whose name matches a contract model.

    The object name is the model name, so a new .sql file only needs a matching
    ``models:`` entry to inherit comments and tags. Anything published without a
    model is logged rather than skipped silently — an undeclared output is a
    governance gap, not a detail.
    """
    models = contract.get("models") or {}
    applied: list[str] = []
    for fqn in fqns:
        model_name = fqn.rsplit(".", 1)[-1]
        if model_name not in models:
            logger.warning(
                "No contract model for %s — published without semantics", fqn
            )
            continue
        apply_schema_semantics(
            spark, fqn, contract, model_name=model_name, product=product
        )
        applied.append(fqn)
    return applied


def apply_table_metadata(
    spark: "SparkSession",
    config: Config,
    fqn: str,
    *,
    comment: str | None = None,
    contract: dict[str, Any] | None = None,
    product: dict[str, Any] | None = None,
    apply_comment: bool = True,
) -> None:
    """Ownership TBLPROPERTIES; optional short table comment (prefer contract via apply_schema_semantics)."""
    props = {
        "dp.owner": (product or {}).get("owner")
        or (contract or {}).get("info", {}).get("owner")
        or "governance_team",
        "dp.domain": (product or {}).get("domain") or "mobility",
        "dp.contract_id": (contract or {}).get("id") or "",
        "dp.product_id": (product or {}).get("id") or "",
        "dp.run_id": config.run_id,
    }
    if apply_comment and comment:
        spark.sql(f"COMMENT ON TABLE {fqn} IS '{_escape_sql_literal(_normalize_comment(comment))}'")
    for key, value in props.items():
        safe = str(value).replace("'", "")
        spark.sql(f"ALTER TABLE {fqn} SET TBLPROPERTIES ('{key}' = '{safe}')")
    logger.info("Metadata applied to %s owner=%s run_id=%s", fqn, props["dp.owner"], config.run_id)
