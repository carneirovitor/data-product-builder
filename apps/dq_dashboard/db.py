"""SQL warehouse access for the DQ observability app."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

import pandas as pd
import streamlit as st

CATALOG = os.environ.get("CATALOG", "workspace").strip() or "workspace"


def _warehouse_http_path() -> str:
    explicit = os.environ.get("SQL_WAREHOUSE_HTTP_PATH", "").strip()
    if explicit:
        return explicit
    wh_id = os.environ.get("DATABRICKS_WAREHOUSE_ID", "").strip()
    if wh_id:
        return f"/sql/1.0/warehouses/{wh_id}"
    raise RuntimeError(
        "Defina SQL_WAREHOUSE_HTTP_PATH ou DATABRICKS_WAREHOUSE_ID no ambiente do app."
    )


@st.cache_resource
def get_connection():
    from databricks import sql
    from databricks.sdk.core import Config

    cfg = Config()
    host = (cfg.host or os.environ.get("DATABRICKS_HOST", "")).replace("https://", "").rstrip("/")
    if not host:
        raise RuntimeError("Host Databricks não encontrado — faça login via CLI ou defina DATABRICKS_HOST.")
    return sql.connect(
        server_hostname=host,
        http_path=_warehouse_http_path(),
        credentials_provider=lambda: cfg.authenticate,
    )


@st.cache_data(ttl=60, show_spinner=False)
def query(sql_text: str) -> pd.DataFrame:
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(sql_text)
        arrow = cur.fetchall_arrow()
        if arrow is None or arrow.num_rows == 0:
            return pd.DataFrame()
        return arrow.to_pandas()


def fqn(schema: str, table: str) -> str:
    return f"{CATALOG}.{schema}.{table}"


def sql_literal(value: str) -> str:
    return str(value).replace("'", "''")


def list_runs() -> pd.DataFrame:
    sql = f"""
    SELECT run_id, MAX(captured_at) AS last_captured
    FROM {fqn('governance', 'data_profile')}
    GROUP BY run_id
    ORDER BY last_captured DESC
    """
    try:
        return query(sql)
    except Exception:
        return pd.DataFrame(columns=["run_id", "last_captured"])


def safe_query(sql_text: str, empty_message: str) -> tuple[pd.DataFrame, str | None]:
    try:
        df = query(sql_text)
        if df.empty:
            return df, empty_message
        return df, None
    except Exception as exc:
        return pd.DataFrame(), str(exc)
