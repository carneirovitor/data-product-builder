"""Raw → clean + quarantine (multi-rule hard gate) + aggregate DQ + profile."""

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

from src.lib.config import CLEAN_MODEL_PATH, load_config
from src.lib.contract import load_contract
from src.lib.dq_engine import apply_row_gate
from src.lib.governance_engine import (
    append_governance,
    create_governance_views,
    evaluate_aggregates,
    profile_dataframe,
)
from src.lib.metadata import apply_schema_semantics, apply_table_metadata, load_product
from src.lib.soda_runner import DEFAULT_SODA_CHECKS
from src.lib.spark_utils import ensure_schemas, get_spark, write_delta
from src.lib.sql_runner import read_sql

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("build_clean")


def main(argv: list[str] | None = None) -> int:
    config = load_config(argv)
    contract = load_contract(config.contract_path)
    product = load_product(config.product_path)
    spark = get_spark(config, app_name="build_clean")
    ensure_schemas(spark, config)

    canonical = read_sql(spark, CLEAN_MODEL_PATH, config)
    # Soda Core executes the checks; quarantine keeps the multi-rule hard trail
    clean, quarantine, summary = apply_row_gate(
        spark,
        canonical,
        contract,
        run_id=config.run_id,
        sodacl_path=DEFAULT_SODA_CHECKS,
    )

    clean_fqn = config.fqn("clean", "taxi_trips")
    quar_fqn = config.fqn("clean", "taxi_trips_quarantine")
    write_delta(clean, clean_fqn, mode="overwrite", partition_by=["year_month"])
    write_delta(quarantine, quar_fqn, mode="overwrite")

    apply_table_metadata(
        spark,
        config,
        clean_fqn,
        contract=contract,
        product=product,
        apply_comment=False,
    )
    apply_schema_semantics(
        spark, clean_fqn, contract, model_name="taxi_trips", product=product
    )
    apply_table_metadata(
        spark,
        config,
        quar_fqn,
        comment="DQ incident trail — multi-rule quarantine",
        contract=contract,
        product=product,
    )

    agg_df, failed = evaluate_aggregates(
        spark,
        clean,
        quarantine,
        contract,
        run_id=config.run_id,
        gate_summary=summary,
    )
    # Prefer Soda-mapped row outcomes when present (DAMA dimensions from contract)
    soda_rows = summary.get("soda_validation_rows") or []
    if soda_rows:
        from pyspark.sql import Row
        from pyspark.sql import types as T

        soda_schema = T.StructType(
            [
                T.StructField("run_id", T.StringType(), False),
                T.StructField("rule", T.StringType(), False),
                T.StructField("dimension", T.StringType(), False),
                T.StructField("scope", T.StringType(), False),
                T.StructField("severity", T.StringType(), False),
                T.StructField("passed", T.BooleanType(), False),
                T.StructField("measured", T.DoubleType(), True),
                T.StructField("threshold", T.DoubleType(), True),
                T.StructField("captured_at", T.TimestampType(), False),
            ]
        )
        soda_df = spark.createDataFrame(
            [Row(**{k: r.get(k) for k in [
                "run_id", "rule", "dimension", "scope", "severity",
                "passed", "measured", "threshold", "captured_at",
            ]}) for r in soda_rows],
            schema=soda_schema,
        )
        # Drop duplicate soft/hard row rules from aggregate helper if Soda already wrote them
        soda_rule_names = {r["rule"] for r in soda_rows}
        agg_df = agg_df.filter(~F.col("rule").isin(list(soda_rule_names)))
        append_governance(
            soda_df.unionByName(agg_df),
            config.fqn("governance", "dq_validation_result"),
        )
    else:
        append_governance(agg_df, config.fqn("governance", "dq_validation_result"))

    profile = profile_dataframe(
        spark,
        clean,
        contract,
        run_id=config.run_id,
        layer="clean",
        table="taxi_trips",
    )
    append_governance(profile, config.fqn("governance", "data_profile"))
    create_governance_views(spark, config)

    logger.info(
        "CLEAN run_id=%s clean=%s quarantine=%s rate=%.4f",
        config.run_id,
        summary["clean_rows"],
        summary["quarantine_rows"],
        summary["quarantine_rate"],
    )
    if summary["quarantine_rows"] == 0:
        logger.warning(
            "No quarantine rows — unusual for TLC; documented if intentional run_id=%s",
            config.run_id,
        )

    types = clean.select("taxi_type").distinct().toPandas()["taxi_type"].tolist()
    if set(types) != {"yellow", "green"}:
        logger.error("FAILED expected yellow+green in clean got=%s run_id=%s", types, config.run_id)
        return 1

    if failed:
        logger.error(
            "FAILED aggregate error rules=%s run_id=%s rows_quarantine=%s",
            failed,
            config.run_id,
            summary["quarantine_rows"],
        )
        return 1

    logger.info("OK build_clean run_id=%s", config.run_id)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        logger.exception("FAILED build_clean: %s", exc)
        raise SystemExit(1)
