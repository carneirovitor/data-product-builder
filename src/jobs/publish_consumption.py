"""Clean → consumption (5 CDEs + taxi_type + year_month) + fitness + profile."""

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

from src.lib.config import (
    CONSUMPTION_MODEL_PATH,
    CONSUMPTION_VIEWS_DIR,
    load_config,
)
from src.lib.contract import load_contract
from src.lib.governance_engine import (
    append_governance,
    create_governance_views,
    evaluate_fitness,
    profile_dataframe,
)
from src.lib.metadata import (
    apply_schema_semantics,
    apply_semantics_for_objects,
    apply_table_metadata,
    load_product,
)
from src.lib.spark_utils import ensure_schemas, get_spark
from src.lib.sql_runner import create_table, create_views_from_dir

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("publish_consumption")


def main(argv: list[str] | None = None) -> int:
    config = load_config(argv)
    contract = load_contract(config.contract_path)
    product = load_product(config.product_path)
    spark = get_spark(config, app_name="publish_consumption")
    ensure_schemas(spark, config)

    fqn = config.fqn("consumption", "taxi_trips")
    create_table(
        spark, CONSUMPTION_MODEL_PATH, config, fqn, partition_by=["year_month"]
    )
    consumption = spark.table(fqn)

    # Props first (no short comment); contract owns table/column comments + tags.
    apply_table_metadata(
        spark,
        config,
        fqn,
        contract=contract,
        product=product,
        apply_comment=False,
    )
    apply_schema_semantics(
        spark, fqn, contract, model_name="taxi_trips", product=product
    )

    # vw_taxi_trips_tlc republishes the CDEs under the original TLC names
    views = create_views_from_dir(
        spark, CONSUMPTION_VIEWS_DIR, config, schema="consumption"
    )
    apply_semantics_for_objects(spark, views, contract, product=product)

    count = consumption.count()
    logger.info("CONSUMPTION run_id=%s rows=%s", config.run_id, count)
    if count == 0:
        logger.error("FAILED empty consumption run_id=%s", config.run_id)
        return 1

    fitness_df, failed = evaluate_fitness(
        spark, consumption, contract, run_id=config.run_id
    )
    append_governance(fitness_df, config.fqn("governance", "fitness_for_use_result"))

    profile = profile_dataframe(
        spark,
        consumption,
        contract,
        run_id=config.run_id,
        layer="consumption",
        table="taxi_trips",
    )
    append_governance(profile, config.fqn("governance", "data_profile"))
    create_governance_views(spark, config)

    if failed:
        logger.error("FAILED fitness rules=%s run_id=%s", failed, config.run_id)
        return 1

    logger.info("OK publish_consumption run_id=%s", config.run_id)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        logger.exception("FAILED publish_consumption: %s", exc)
        raise SystemExit(1)
