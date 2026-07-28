"""Runtime configuration — env vars + argparse helpers. No generic framework."""

from __future__ import annotations

import argparse
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# One folder per data product: contract, checks and the SQL of every layer.
# Adding a product means adding a sibling folder, not editing a job.
PRODUCT_ROOT = REPO_ROOT / "domains" / "mobility" / "taxi_trips"
DEFAULT_CONTRACT_PATH = PRODUCT_ROOT / "contract.yaml"
DEFAULT_PRODUCT_PATH = PRODUCT_ROOT / "product.yaml"
DEFAULT_SODA_CHECKS_PATH = PRODUCT_ROOT / "data_quality" / "checks.yml"

CLEAN_MODEL_PATH = PRODUCT_ROOT / "clean" / "models" / "taxi_trips.sql"
CONSUMPTION_MODEL_PATH = PRODUCT_ROOT / "consumption" / "models" / "taxi_trips.sql"
CONSUMPTION_VIEWS_DIR = PRODUCT_ROOT / "consumption" / "views"
METRICS_DIR = PRODUCT_ROOT / "consumption" / "metrics"
GOVERNANCE_VIEWS_DIR = REPO_ROOT / "platform" / "governance" / "views"


@dataclass(frozen=True)
class Config:
    run_id: str
    catalog: str
    landing_path: str
    contract_path: Path
    product_path: Path
    local_warehouse: str

    @property
    def is_local(self) -> bool:
        return not self.catalog

    def fqn(self, schema: str, table: str) -> str:
        if self.catalog:
            return f"{self.catalog}.{schema}.{table}"
        return f"{schema}.{table}"


def new_run_id() -> str:
    return os.environ.get("RUN_ID") or str(uuid.uuid4())


def load_config(argv: list[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(description="Taxi data product job config")
    parser.add_argument(
        "--catalog",
        default=os.environ.get("CATALOG", ""),
        help="Unity Catalog name (empty for local Spark)",
    )
    parser.add_argument(
        "--landing-path",
        default=os.environ.get("LANDING_PATH", str(REPO_ROOT / "files")),
        help="Landing directory or UC Volume path with parquet files",
    )
    parser.add_argument(
        "--contract",
        default=os.environ.get("CONTRACT_PATH", str(DEFAULT_CONTRACT_PATH)),
    )
    parser.add_argument(
        "--product",
        default=os.environ.get("PRODUCT_PATH", str(DEFAULT_PRODUCT_PATH)),
    )
    parser.add_argument(
        "--warehouse",
        default=os.environ.get("LOCAL_WAREHOUSE", str(REPO_ROOT / ".warehouse")),
        help="Local Spark warehouse dir (ignored on Databricks)",
    )
    parser.add_argument("--run-id", default=None)
    args, _ = parser.parse_known_args(argv)

    run_id = args.run_id or new_run_id()
    return Config(
        run_id=run_id,
        catalog=args.catalog.strip(),
        landing_path=args.landing_path,
        contract_path=Path(args.contract),
        product_path=Path(args.product),
        local_warehouse=args.warehouse,
    )


YEAR_MONTHS = ("2023-01", "2023-02", "2023-03", "2023-04", "2023-05")
CONSUMPTION_CDES = (
    "vendor_id",
    "passenger_count",
    "total_amount",
    "pickup_datetime",
    "dropoff_datetime",
    "taxi_type",
)
