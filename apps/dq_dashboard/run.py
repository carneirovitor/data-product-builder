#!/usr/bin/env python3
"""Launch Streamlit on the port Databricks Apps assigns (DATABRICKS_APP_PORT)."""

from __future__ import annotations

import os
import subprocess
import sys


def main() -> int:
    port = os.environ.get("DATABRICKS_APP_PORT", os.environ.get("STREAMLIT_SERVER_PORT", "8000"))
    os.environ.setdefault("STREAMLIT_SERVER_ADDRESS", "0.0.0.0")
    os.environ.setdefault("STREAMLIT_SERVER_HEADLESS", "true")
    os.environ.setdefault("STREAMLIT_SERVER_ENABLE_CORS", "false")
    os.environ.setdefault("STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION", "false")

    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "app.py",
        "--server.port",
        str(port),
        "--server.address",
        "0.0.0.0",
        "--server.headless",
        "true",
    ]
    print(f"Starting Streamlit on 0.0.0.0:{port}", flush=True)
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
