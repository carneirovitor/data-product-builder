"""Execute .sql model files — the object name and layer come from the path.

Every file holds a bare SELECT. The catalog is injected at runtime via
``${catalog}.`` so the same file runs on Unity Catalog and on local Spark,
where ``config.catalog`` is empty and the prefix collapses to nothing.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyspark.sql import DataFrame, SparkSession

logger = logging.getLogger(__name__)


def render_sql(path: str | Path, config) -> str:
    """Read a model file and resolve ${catalog}. / ${run_id} from the runtime config."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"SQL model not found: {path}")
    prefix = f"{config.catalog}." if config.catalog else ""
    sql = (
        path.read_text(encoding="utf-8")
        .replace("${catalog}.", prefix)
        .replace("${run_id}", config.run_id)
    )
    leftover = sorted(set(re.findall(r"\$\{[^}]*\}", sql)))
    if leftover:
        raise ValueError(f"Unresolved placeholders {leftover} in {path}")
    return sql.strip().rstrip(";")


def read_sql(spark: "SparkSession", path: str | Path, config) -> "DataFrame":
    """Run a model file and hand back the DataFrame without materializing it."""
    sql = render_sql(path, config)
    logger.info("SQL read model=%s", Path(path).name)
    return spark.sql(sql)


def create_table(
    spark: "SparkSession",
    path: str | Path,
    config,
    fqn: str,
    *,
    partition_by: list[str] | None = None,
) -> str:
    """Materialize a model file as a Delta table."""
    select = render_sql(path, config)
    partition = (
        f"PARTITIONED BY ({', '.join(partition_by)})" if partition_by else ""
    )
    spark.sql(
        f"CREATE OR REPLACE TABLE {fqn} USING DELTA {partition} AS\n{select}"
    )
    logger.info("SQL table=%s model=%s", fqn, Path(path).name)
    return fqn


def create_view(spark: "SparkSession", path: str | Path, config, fqn: str) -> str:
    select = render_sql(path, config)
    spark.sql(f"CREATE OR REPLACE VIEW {fqn} AS\n{select}")
    logger.info("SQL view=%s model=%s", fqn, Path(path).name)
    return fqn


def create_views_from_dir(
    spark: "SparkSession",
    directory: str | Path,
    config,
    *,
    schema: str,
) -> list[str]:
    """Create one view per .sql file; the file name is the view name."""
    directory = Path(directory)
    files = sorted(directory.glob("*.sql"))
    if not files:
        raise FileNotFoundError(f"No .sql views under {directory}")
    return [
        create_view(spark, f, config, config.fqn(schema, f.stem)) for f in files
    ]


def create_tables_from_dir(
    spark: "SparkSession",
    directory: str | Path,
    config,
    *,
    schema: str,
) -> list[str]:
    """Create one table per .sql file; the file name is the table name."""
    directory = Path(directory)
    files = sorted(directory.glob("*.sql"))
    if not files:
        raise FileNotFoundError(f"No .sql models under {directory}")
    return [
        create_table(spark, f, config, config.fqn(schema, f.stem)) for f in files
    ]
