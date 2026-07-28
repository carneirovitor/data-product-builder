"""Materialize the KPI models in consumption/metrics; fail loud on coverage."""

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

from src.lib.config import METRICS_DIR, load_config
from src.lib.contract import load_contract
from src.lib.metadata import (
    apply_semantics_for_objects,
    apply_table_metadata,
    load_product,
)
from src.lib.spark_utils import ensure_schemas, get_spark
from src.lib.sql_runner import create_tables_from_dir

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("run_analysis")


Q1_TABLE = "kpi_yellow_avg_total_amount_monthly"
Q2_TABLE = "kpi_fleet_avg_passenger_count_hourly"


def main(argv: list[str] | None = None) -> int:
    config = load_config(argv)
    contract = load_contract(config.contract_path)
    product = load_product(config.product_path)
    spark = get_spark(config, app_name="run_analysis")
    ensure_schemas(spark, config)

    created = create_tables_from_dir(spark, METRICS_DIR, config, schema="consumption")
    for fqn in created:
        # Props only; the contract owns the table and column comments.
        apply_table_metadata(
            spark,
            config,
            fqn,
            contract=contract,
            product=product,
            apply_comment=False,
        )
    apply_semantics_for_objects(spark, created, contract, product=product)

    q1 = spark.table(config.fqn("consumption", Q1_TABLE)).orderBy("year_month").collect()
    logger.info("Q1 yellow avg total_amount by month:")
    for row in q1:
        logger.info("  %s -> %.4f", row["year_month"], row["avg_total_amount"])

    q2 = spark.table(config.fqn("consumption", Q2_TABLE)).orderBy("pickup_hour").collect()
    logger.info("Q2 May avg passenger_count by hour (fleet yellow+green):")
    for row in q2:
        logger.info("  hour=%s -> %.4f", row["pickup_hour"], row["avg_passenger_count"])

    if len(q1) != 5:
        logger.error(
            "FAILED Q1 expected 5 months got=%s run_id=%s", len(q1), config.run_id
        )
        return 1
    if len(q2) < 20:
        logger.error(
            "FAILED Q2 expected >=20 hours got=%s run_id=%s", len(q2), config.run_id
        )
        return 1

    logger.info(
        "OK run_analysis run_id=%s metrics=%s q1_months=%s q2_hours=%s",
        config.run_id,
        len(created),
        len(q1),
        len(q2),
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        logger.exception("FAILED run_analysis: %s", exc)
        raise SystemExit(1)
