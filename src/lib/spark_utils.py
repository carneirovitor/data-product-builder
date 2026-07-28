"""Spark session helpers and Delta write utilities."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.lib.config import Config

if TYPE_CHECKING:
    from pyspark.sql import DataFrame, SparkSession

logger = logging.getLogger(__name__)


def _safe_set_log_level(spark: "SparkSession", level: str = "WARN") -> None:
    """Best-effort; serverless Unity Catalog whitelist blocks SparkContext.setLogLevel."""
    try:
        spark.sparkContext.setLogLevel(level)
    except Exception:
        logger.debug("setLogLevel(%s) not available on this runtime", level, exc_info=True)


def get_spark(config: Config, app_name: str = "taxi_data_product") -> "SparkSession":
    from pyspark.sql import SparkSession

    # Serverless spark_python_task / notebooks already have a live session; creating
    # another via builder.getOrCreate() raises RemoteSparkSession conflict.
    active = SparkSession.getActiveSession()
    if active is not None:
        try:
            active.conf.set("spark.sql.session.timeZone", "UTC")
            active.conf.set("spark.sql.sources.partitionOverwriteMode", "dynamic")
        except Exception:
            logger.debug("Could not set session conf on active SparkSession", exc_info=True)
        _safe_set_log_level(active)
        return active

    builder = (
        SparkSession.builder.appName(app_name)
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.sources.partitionOverwriteMode", "dynamic")
    )

    # Local: enable Delta if package is on classpath; Databricks already has it.
    if config.is_local:
        builder = (
            builder.master("local[*]")
            .config("spark.sql.warehouse.dir", config.local_warehouse)
            .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
            .config(
                "spark.sql.catalog.spark_catalog",
                "org.apache.spark.sql.delta.catalog.DeltaCatalog",
            )
        )

    spark = builder.getOrCreate()
    _safe_set_log_level(spark)
    return spark


def ensure_schemas(spark: "SparkSession", config: Config) -> None:
    schemas = ("raw", "clean", "consumption", "governance")
    for schema in schemas:
        if config.catalog:
            spark.sql(f"CREATE SCHEMA IF NOT EXISTS {config.catalog}.{schema}")
        else:
            spark.sql(f"CREATE SCHEMA IF NOT EXISTS {schema}")


def write_delta(
    df: "DataFrame",
    fqn: str,
    *,
    mode: str = "overwrite",
    partition_by: list[str] | None = None,
) -> None:
    writer = df.write.format("delta").mode(mode)
    if partition_by:
        # overwriteSchema is incompatible with dynamic partition overwrite.
        writer = (
            writer.option("partitionOverwriteMode", "static")
            .option("overwriteSchema", "true")
            .partitionBy(*partition_by)
        )
    else:
        writer = writer.option("overwriteSchema", "true")
    writer.saveAsTable(fqn)
    try:
        n = df.count()
    except Exception:
        n = -1
    logger.info("Wrote Delta table %s mode=%s rows=%s", fqn, mode, n)
