#!/usr/bin/env bash
# Sync the SQL/YAML/Python the jobs read at runtime, then deploy and run.
#
# The bundle only ships databricks.yml and the entrypoint notebook; everything
# the jobs import or execute lives on a UC Volume, so a deploy without this sync
# runs the previous revision of the code.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

TARGET="${TARGET:-dev}"
CODE_VOLUME="${CODE_VOLUME:-dbfs:/Volumes/workspace/default/taxi_code}"

echo "==> Syncing code to $CODE_VOLUME"
for dir in domains platform src; do
  databricks fs cp -r --overwrite "$dir" "$CODE_VOLUME/$dir"
done

# The app container gets only its own folder — no UC Volume mount — so the
# contract travels with the app source instead of being read from repo_root.
APP_CONTRACT_DIR="apps/dq_dashboard/contract"
echo "==> Bundling contract into $APP_CONTRACT_DIR"
mkdir -p "$APP_CONTRACT_DIR"
cp domains/mobility/taxi_trips/contract.yaml "$APP_CONTRACT_DIR/"
cp domains/mobility/taxi_trips/product.yaml "$APP_CONTRACT_DIR/"

echo "==> Deploying bundle (target=$TARGET)"
databricks bundle deploy -t "$TARGET"

if [[ "${1:-}" == "--no-run" ]]; then
  echo "==> Skipping run (--no-run)"
  exit 0
fi

echo "==> Running pipeline"
databricks bundle run taxi_data_product -t "$TARGET"
