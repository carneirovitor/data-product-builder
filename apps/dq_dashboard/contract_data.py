"""Load contract and product YAML.

The app container only receives the files under apps/dq_dashboard/ — it does not
mount UC Volumes, so REPO_ROOT is unusable once deployed. scripts/deploy.sh copies
the two YAML files into contract/ before the bundle upload; the REPO_ROOT lookup
stays as the local-development path.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

BUNDLED_DIR = Path(__file__).resolve().parent / "contract"


def _candidate_paths(filename: str) -> list[Path]:
    paths = [BUNDLED_DIR / filename]

    env_root = os.environ.get("REPO_ROOT", "").strip()
    if env_root:
        paths.append(Path(env_root) / "domains" / "mobility" / "taxi_trips" / filename)

    here = Path(__file__).resolve()
    for parent in here.parents:
        paths.append(parent / "domains" / "mobility" / "taxi_trips" / filename)

    return paths


def _load_yaml(filename: str) -> tuple[dict[str, Any], str | None]:
    for path in _candidate_paths(filename):
        try:
            if path.is_file():
                with path.open(encoding="utf-8") as fh:
                    return (yaml.safe_load(fh) or {}), str(path)
        except OSError:
            continue
    return {}, None


@lru_cache(maxsize=1)
def load_contract() -> dict[str, Any]:
    data, _ = _load_yaml("contract.yaml")
    return data


@lru_cache(maxsize=1)
def load_product() -> dict[str, Any]:
    data, _ = _load_yaml("product.yaml")
    return data.get("product") or data


@lru_cache(maxsize=1)
def contract_source() -> str | None:
    _, path = _load_yaml("contract.yaml")
    return path


def rule_catalog() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for rule in load_contract().get("quality") or []:
        name = rule.get("name")
        if name:
            out[name] = rule
    return out


def quarantine_rate_cap() -> float:
    for rule in load_contract().get("quality") or []:
        if rule.get("name") == "quarantine_rate_cap":
            return float(rule.get("threshold") or 0.05)
    return 0.05
