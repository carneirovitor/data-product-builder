"""Mobility Taxi Trips — portal de observabilidade de Data Quality (Streamlit)."""

from __future__ import annotations

import os
import traceback

import streamlit as st

st.set_page_config(
    page_title="Taxi Trips — Data Quality",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

try:
    from db import CATALOG, list_runs
    from labels import run_option_label
    from ui_sections import (
        inject_css,
        render_catalog,
        render_fitness,
        render_incidents,
        render_lineage,
        render_profiling,
        render_q1_q2,
        render_scorecard,
    )
except Exception:
    st.error("Falha ao carregar módulos do app.")
    st.code(traceback.format_exc())
    st.stop()

inject_css()

with st.sidebar:
    st.header("Controles")
    executive = st.toggle(
        "Visão executiva",
        value=False,
        help="Troca gráficos e nomes técnicos por um resumo em linguagem de negócio",
    )

    try:
        runs = list_runs()
    except Exception as exc:
        st.error(f"Erro ao listar execuções: {exc}")
        runs = None

    run_id = ""
    run_label = ""
    if runs is None or runs.empty:
        st.warning(
            "Nenhuma execução em `governance.data_profile`, ou sem permissão no warehouse. "
            "Rode `./scripts/deploy.sh` e confira os GRANTs do service principal do app."
        )
        run_id = st.text_input("Execução (ID manual)", value=os.environ.get("DEFAULT_RUN_ID", ""))
    else:
        # Runs are opaque job IDs — index by position so the label can lead with the date.
        options = list(range(len(runs)))
        labels = {
            i: run_option_label(runs.iloc[i]["run_id"], runs.iloc[i]["last_captured"])
            for i in options
        }
        picked = st.selectbox(
            "Execução do pipeline",
            options,
            format_func=lambda i: labels[i],
            help="Ordenadas da mais recente para a mais antiga",
        )
        run_id = str(runs.iloc[picked]["run_id"])
        run_label = labels[picked]

    st.caption("A primeira consulta pode demorar (warehouse serverless acorda sob demanda).")
    wh = os.environ.get("DATABRICKS_WAREHOUSE_ID") or os.environ.get("SQL_WAREHOUSE_HTTP_PATH", "—")
    st.caption(f"Warehouse: `{wh}`")

if not run_id:
    st.stop()

if executive:
    st.title("Táxis de Nova York — confiança dos dados")
    st.markdown(
        f"Resultado da execução de **{run_label or run_id}**. "
        "Cada número abaixo passou pelas regras de qualidade combinadas com o time de negócio."
    )
    tabs = st.tabs(["Podemos confiar?", "Respostas do negócio", "O que foi combinado"])
    with tabs[0]:
        render_scorecard(run_id, True)
        st.divider()
        render_fitness(run_id, True)
        st.divider()
        render_incidents(run_id, True)
    with tabs[1]:
        render_q1_q2(run_id, True)
    with tabs[2]:
        render_catalog()
else:
    st.title("Mobility Taxi Trips")
    st.markdown(
        f"**Portal de Data Quality & Reliability** · catálogo `{CATALOG}` · "
        f"execução de {run_label or run_id}"
    )
    tabs = st.tabs(
        [
            "Placar de qualidade",
            "Perfilagem",
            "Quarentena",
            "Adequação ao uso",
            "Q1 / Q2",
            "Linhagem",
            "Contrato",
        ]
    )
    with tabs[0]:
        render_scorecard(run_id, False)
    with tabs[1]:
        render_profiling(run_id, False)
    with tabs[2]:
        render_incidents(run_id, False)
    with tabs[3]:
        render_fitness(run_id, False)
    with tabs[4]:
        render_q1_q2(run_id, False)
    with tabs[5]:
        render_lineage(run_id)
    with tabs[6]:
        render_catalog()
