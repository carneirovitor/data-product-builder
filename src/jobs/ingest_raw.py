"""Landing Volume/files → raw Delta (yellow + green) + profile raw."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

def _repo_root() -> Path:
    if "--repo-root" in sys.argv:
        i = sys.argv.index("--repo-root")
        if i + 1 < len(sys.argv):
            return Path(sys.argv[i + 1]).resolve()
    try:
        return Path(__file__).resolve().parents[2]
    except NameError:
        # Databricks serverless spark_python_task execs without __file__.
        candidates = []
        if sys.argv and sys.argv[0]:
            argv0 = Path(sys.argv[0]).resolve()
            if len(argv0.parents) >= 2:
                candidates.append(argv0.parents[2])
        here = Path.cwd().resolve()
        candidates.extend([here, *here.parents])
        return next(
            (p for p in candidates if (p / "src" / "lib").is_dir()),
            here,
        )

REPO_ROOT = _repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pyspark.sql import functions as F

from src.lib.config import CLEAN_MODEL_PATH, YEAR_MONTHS, load_config
from src.lib.contract import load_contract
from src.lib.governance_engine import append_governance, profile_dataframe
from src.lib.spark_utils import ensure_schemas, get_spark, write_delta
from src.lib.sql_runner import read_sql

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("ingest_raw")


_DRIFT_TO_DOUBLE = (
    "passenger_count",
    "RatecodeID",
    "congestion_surcharge",
    "airport_fee",
)
_DRIFT_TO_LONG = (
    "VendorID",
    "PULocationID",
    "DOLocationID",
    "payment_type",
    "trip_type",
)


def _normalize_tlc_dtypes(df):
    """Cast known TLC monthly drift columns so unionByName succeeds."""
    for col_name in _DRIFT_TO_DOUBLE:
        if col_name in df.columns:
            df = df.withColumn(col_name, F.col(col_name).cast("double"))
    for col_name in _DRIFT_TO_LONG:
        if col_name in df.columns:
            df = df.withColumn(col_name, F.col(col_name).cast("bigint"))
    return df


def _read_taxi_type(spark, landing: str, taxi_type: str):
    """Read Jan–May parquet month-by-month; tolerate TLC dtype drift."""
    frames = []
    for ym in YEAR_MONTHS:
        path = f"{landing.rstrip('/')}/{taxi_type}_tripdata_{ym}.parquet"
        logger.info("Reading %s", path)
        # Capture path before dtype casts — withColumn projects drop _metadata.
        # lit(path) is UC-safe (no input_file_name / unresolved _metadata).
        month_df = spark.read.parquet(path).withColumn("source_file", F.lit(path))
        month_df = _normalize_tlc_dtypes(month_df)
        frames.append(month_df)
    df = frames[0]
    for other in frames[1:]:
        df = df.unionByName(other, allowMissingColumns=True)
    df = df.withColumn("ingest_ts", F.current_timestamp())
    df = df.withColumn("taxi_type_hint", F.lit(taxi_type))
    return df


def main(argv: list[str] | None = None) -> int:
    config = load_config(argv)
    contract = load_contract(config.contract_path)
    spark = get_spark(config, app_name="ingest_raw")
    ensure_schemas(spark, config)

    yellow = _read_taxi_type(spark, config.landing_path, "yellow")
    green = _read_taxi_type(spark, config.landing_path, "green")

    y_fqn = config.fqn("raw", "yellow_tripdata")
    g_fqn = config.fqn("raw", "green_tripdata")
    write_delta(yellow, y_fqn, mode="overwrite")
    write_delta(green, g_fqn, mode="overwrite")

    y_count = spark.table(y_fqn).count()
    g_count = spark.table(g_fqn).count()
    logger.info(
        "INGEST run_id=%s yellow_rows=%s green_rows=%s months=%s",
        config.run_id,
        y_count,
        g_count,
        list(YEAR_MONTHS),
    )
    if y_count == 0 or g_count == 0:
        logger.error("FAILED empty raw table run_id=%s", config.run_id)
        return 1

    # Profile the raw layer through the canonical model, so the numbers describe the
    # same harmonization the gate will see instead of a third copy of the mapping.
    combined = read_sql(spark, CLEAN_MODEL_PATH, config)
    try:
        profile = profile_dataframe(
            spark,
            combined,
            contract,
            run_id=config.run_id,
            layer="raw",
            table="taxi_trips_projected",
        )
        append_governance(profile, config.fqn("governance", "data_profile"))
    except Exception as exc:
        # Raw tables already written; numeric profile collect can flake on serverless.
        logger.exception("WARN raw profile skipped run_id=%s: %s", config.run_id, exc)
    logger.info("OK ingest_raw run_id=%s", config.run_id)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        logger.exception("FAILED ingest_raw: %s", exc)
        raise SystemExit(1)
