"""Validate Data Contract Specification 0.9.3 structure — no Spark required."""

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

from src.lib.config import load_config
from src.lib.contract import assert_contract_valid, load_contract

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("validate_contract")


def main(argv: list[str] | None = None) -> int:
    config = load_config(argv)
    logger.info("Validating contract path=%s run_id=%s", config.contract_path, config.run_id)
    contract = load_contract(config.contract_path)
    assert_contract_valid(contract)
    logger.info(
        "OK contract_id=%s version=%s hard/soft rules validated run_id=%s",
        contract.get("id"),
        contract.get("info", {}).get("version"),
        config.run_id,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        logger.error("FAILED validate_contract: %s", exc)
        raise SystemExit(1)
