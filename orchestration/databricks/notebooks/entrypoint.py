# Databricks notebook source
# Single entrypoint for every task of the taxi_data_product job.
# Serverless FUSE is unreliable for imports under /Workspace, so job scripts are
# executed from the UC Volume named by the repo_root widget.
import subprocess
import sys

subprocess.check_call(
    [sys.executable, "-m", "pip", "install", "-q", "soda-core-spark-df==3.5.6", "--no-deps"]
)

import runpy

dbutils.widgets.text("job", "")
dbutils.widgets.text("repo_root", "/Volumes/workspace/default/taxi_code")
dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("run_id", "")
dbutils.widgets.text("landing_path", "/Volumes/workspace/default/taxi_landing")

job = dbutils.widgets.get("job")
repo_root = dbutils.widgets.get("repo_root")
catalog = dbutils.widgets.get("catalog")
run_id = dbutils.widgets.get("run_id")
landing_path = dbutils.widgets.get("landing_path")

if not job:
    raise ValueError("FAILED entrypoint requires a 'job' widget naming src/jobs/<job>.py")

argv = ["--repo-root", repo_root, "--catalog", catalog]
if run_id:
    argv += ["--run-id", run_id]
if job == "ingest_raw":
    argv += ["--landing-path", landing_path]

script = f"{repo_root}/src/jobs/{job}.py"
print(f"ENTRYPOINT job={job} run_id={run_id} script={script}")

sys.argv = [script] + argv
try:
    runpy.run_path(script, run_name="__main__")
except SystemExit as exc:
    code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    if code != 0:
        raise
