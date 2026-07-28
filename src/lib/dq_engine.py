"""DQ gate facade — Soda Core is the execution engine (see soda_runner)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.lib.soda_runner import (
    DEFAULT_SODA_CHECKS,
    apply_soda_gate,
    outcomes_to_validation_rows,
)

if TYPE_CHECKING:
    from pyspark.sql import DataFrame, SparkSession

logger = logging.getLogger(__name__)


def apply_row_gate(
    spark: "SparkSession",
    df: "DataFrame",
    contract: dict[str, Any],
    *,
    run_id: str,
    sodacl_path: str | Path | None = None,
) -> tuple["DataFrame", "DataFrame", dict[str, Any]]:
    """
    Run Soda scan + materialize clean/quarantine.

    Hard (severity=error / Soda fail): multi-rule quarantine trail.
    Soft (severity=warning / Soda warn): scorecard only — never removes from clean.
    """
    result = apply_soda_gate(
        spark,
        df,
        contract,
        run_id=run_id,
        sodacl_path=sodacl_path or DEFAULT_SODA_CHECKS,
    )
    summary = dict(result.summary)
    summary["soda_exit_code"] = result.scan_exit_code
    summary["soda_validation_rows"] = outcomes_to_validation_rows(
        result.check_outcomes,
        run_id=run_id,
        soft_pass_rates=summary.get("soft_pass_rates") or {},
    )
    logger.info(
        "DQ_ENGINE engine=soda-core run_id=%s clean=%s quarantine=%s soda_exit=%s",
        run_id,
        summary["clean_rows"],
        summary["quarantine_rows"],
        result.scan_exit_code,
    )
    return result.clean, result.quarantine, summary
