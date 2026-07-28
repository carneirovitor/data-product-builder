"""Streamlit sections for the DQ observability portal."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from contract_data import (
    contract_source,
    load_contract,
    load_product,
    quarantine_rate_cap,
    rule_catalog,
)
from db import fqn, safe_query, sql_literal
from labels import (
    DIMENSION_LABELS,
    DIMENSION_PLAIN,
    FITNESS_PLAIN,
    SEVERITY_EFFECT,
    humanize,
    safe_rate,
)

GREEN = "#22c55e"
AMBER = "#f59e0b"
RED = "#ef4444"
GRID = "#334155"

CHART_LAYOUT = dict(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(size=13),
    margin=dict(t=60, b=60, l=60, r=30),
)


def _html(markup: str) -> None:
    """Emit raw HTML.

    Markdown treats any line indented by four spaces as a code block, so the
    source indentation has to be stripped or the markup renders as literal text.
    """
    lines = [line.strip() for line in markup.strip().splitlines()]
    st.markdown("\n".join(line for line in lines if line), unsafe_allow_html=True)


def inject_css() -> None:
    _html(
        """
        <style>
        .block-container { padding-top: 1.5rem; max-width: 1250px; }
        div[data-testid="stMetric"] {
            background: #1e293b; padding: 0.9rem 1.1rem; border-radius: 0.6rem;
            border: 1px solid #334155;
        }
        div[data-testid="stMetricLabel"] { color: #94a3b8; }
        .status-card {
            padding: 1rem 1.2rem; border-radius: 0.6rem; margin-bottom: 0.6rem;
            border-left: 5px solid; background: #1e293b;
        }
        .status-ok { border-color: #22c55e; }
        .status-warn { border-color: #f59e0b; }
        .status-bad { border-color: #ef4444; }
        .status-title { font-weight: 600; font-size: 1.02rem; }
        .status-sub { color: #94a3b8; font-size: 0.9rem; margin-top: 0.15rem; }

        .ln-flow {
            display: flex; align-items: center; gap: 0.5rem;
            flex-wrap: wrap; margin: 0.5rem 0 1rem 0;
        }
        .ln-stage { display: flex; flex-direction: column; gap: 0.5rem; flex: 1 1 200px; }
        .ln-stage-label {
            color: #94a3b8; font-size: 0.75rem; text-transform: uppercase;
            letter-spacing: 0.06em; margin-bottom: 0.1rem;
        }
        .ln-node {
            background: #1e293b; border: 1px solid #334155; border-left-width: 5px;
            border-radius: 0.5rem; padding: 0.7rem 0.85rem;
        }
        .ln-title {
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            font-size: 0.82rem; color: #e2e8f0; word-break: break-all;
        }
        .ln-rows { font-size: 1.05rem; font-weight: 600; color: #f8fafc; margin-top: 0.2rem; }
        .ln-note { font-size: 0.78rem; color: #94a3b8; margin-top: 0.2rem; }
        .ln-arrow { color: #64748b; font-size: 1.6rem; flex: 0 0 auto; padding: 0 0.1rem; }

        .sc-hero {
            display: flex; gap: 1rem; flex-wrap: wrap; margin: 0.4rem 0 1rem 0;
        }
        .sc-hero-score {
            flex: 0 0 180px; background: #1e293b; border: 1px solid #334155;
            border-radius: 0.7rem; padding: 1.1rem 1rem; text-align: center;
        }
        .sc-hero-score .sc-label {
            color: #94a3b8; font-size: 0.75rem; text-transform: uppercase;
            letter-spacing: 0.06em;
        }
        .sc-hero-score .sc-value {
            font-size: 2.6rem; font-weight: 700; line-height: 1.15; margin: 0.25rem 0;
        }
        .sc-hero-score .sc-sub { color: #94a3b8; font-size: 0.85rem; }
        .sc-hero-kpis { flex: 1 1 280px; display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 0.6rem; }
        .sc-kpi {
            background: #1e293b; border: 1px solid #334155; border-radius: 0.55rem;
            padding: 0.75rem 0.9rem;
        }
        .sc-kpi .k-label { color: #94a3b8; font-size: 0.78rem; }
        .sc-kpi .k-value { font-size: 1.25rem; font-weight: 650; margin-top: 0.15rem; }
        .sc-kpi .k-sub { color: #64748b; font-size: 0.75rem; margin-top: 0.1rem; }

        .sc-grid {
            display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
            gap: 0.65rem; margin: 0.5rem 0 1rem 0;
        }
        .sc-dim {
            background: #1e293b; border: 1px solid #334155; border-top: 4px solid;
            border-radius: 0.55rem; padding: 0.85rem 0.9rem;
        }
        .sc-dim .d-name { font-weight: 600; font-size: 0.95rem; }
        .sc-dim .d-score { font-size: 1.7rem; font-weight: 700; margin: 0.2rem 0; }
        .sc-dim .d-meta { color: #94a3b8; font-size: 0.78rem; }
        </style>
        """
    )


def _level_for_rate(rate: float) -> str:
    if rate >= 0.95:
        return "ok"
    if rate >= 0.80:
        return "warn"
    return "bad"


def _color_for_level(level: str) -> str:
    return {"ok": GREEN, "warn": AMBER, "bad": RED}[level]


def _status_card(title: str, subtitle: str, level: str = "ok") -> None:
    icon = {"ok": "✅", "warn": "⚠️", "bad": "❌"}[level]
    _html(
        f"""
        <div class="status-card status-{level}">
        <div class="status-title">{icon} {title}</div>
        <div class="status-sub">{subtitle}</div>
        </div>
        """
    )


def _rate_color(rate: float) -> str:
    if rate >= 0.95:
        return GREEN
    if rate >= 0.80:
        return AMBER
    return RED


def _empty(message: str) -> None:
    st.info(message)


# --------------------------------------------------------------------------- #
# 1. Scorecard
# --------------------------------------------------------------------------- #
def render_scorecard(run_id: str, executive: bool) -> None:
    rid = sql_literal(run_id)
    cap = quarantine_rate_cap()

    df, err = safe_query(
        f"""
        SELECT dimension, rules_evaluated, rules_passed, pass_rate, quarantine_rate, uniqueness_metric
        FROM {fqn('governance', 'vw_dq_scorecard')}
        WHERE run_id = '{rid}'
        ORDER BY dimension
        """,
        "Sem placar de qualidade para esta execução.",
    )
    if err:
        st.warning(err)
        return
    if df.empty:
        _empty("Sem placar de qualidade para esta execução.")
        return

    rules_df, _ = safe_query(
        f"""
        SELECT rule, dimension, severity, scope, passed, measured, threshold
        FROM {fqn('governance', 'dq_validation_result')}
        WHERE run_id = '{rid}'
        ORDER BY CASE WHEN severity = 'error' THEN 0 ELSE 1 END, dimension, rule
        """,
        "",
    )

    avg_pass = safe_rate(df["pass_rate"].mean())
    q_rate = safe_rate(df["quarantine_rate"].dropna().max() if "quarantine_rate" in df else 0)
    uniq_series = (
        df["uniqueness_metric"].dropna()
        if "uniqueness_metric" in df
        else pd.Series(dtype=float)
    )
    has_uniq = not uniq_series.empty
    uniq = safe_rate(uniq_series.max()) if has_uniq else None
    within_cap = q_rate <= cap
    total_rules = int(df["rules_evaluated"].sum())
    total_passed = int(df["rules_passed"].sum())
    overall_level = _level_for_rate(avg_pass) if within_cap else "bad"
    overall_color = _color_for_level(overall_level)

    hard = rules_df[rules_df["severity"] == "error"] if not rules_df.empty else pd.DataFrame()
    soft = rules_df[rules_df["severity"] == "warning"] if not rules_df.empty else pd.DataFrame()
    hard_fail = int((~hard["passed"].astype(bool)).sum()) if not hard.empty else 0
    soft_fail = int((~soft["passed"].astype(bool)).sum()) if not soft.empty else 0

    if executive:
        _status_card(
            "Os dados estão confiáveis para análise"
            if avg_pass >= 0.95 and within_cap and hard_fail == 0
            else "Os dados exigem atenção antes do uso",
            f"Nota de confiabilidade {avg_pass * 100:.0f}% · {total_passed} de {total_rules} verificações aprovadas.",
            overall_level,
        )
        _status_card(
            f"{q_rate * 100:.2f}% das corridas foram isoladas",
            (
                f"Abaixo do limite combinado de {cap * 100:.0f}%."
                if within_cap
                else f"Acima do limite combinado de {cap * 100:.0f}% — investigar antes de publicar."
            ),
            "ok" if within_cap else "bad",
        )
        st.markdown("#### Placar por dimensão")
        for _, row in df.iterrows():
            rate = safe_rate(row["pass_rate"])
            _status_card(
                f"{DIMENSION_LABELS.get(row['dimension'], row['dimension'])} · {rate * 100:.0f}%",
                DIMENSION_PLAIN.get(row["dimension"], ""),
                _level_for_rate(rate),
            )
        return

    # ---- technical: real scorecard layout -------------------------------- #
    _html(
        f"""
        <div class="sc-hero">
        <div class="sc-hero-score">
        <div class="sc-label">Nota de confiabilidade</div>
        <div class="sc-value" style="color:{overall_color}">{avg_pass * 100:.0f}%</div>
        <div class="sc-sub">{total_passed}/{total_rules} regras · {len(df)} dimensões</div>
        </div>
        <div class="sc-hero-kpis">
        <div class="sc-kpi">
        <div class="k-label">Quarentena</div>
        <div class="k-value" style="color:{GREEN if within_cap else RED}">{q_rate * 100:.2f}%</div>
        <div class="k-sub">limite {cap * 100:.0f}%</div>
        </div>
        <div class="sc-kpi">
        <div class="k-label">Regras críticas</div>
        <div class="k-value" style="color:{GREEN if hard_fail == 0 else RED}">{hard_fail} falha(s)</div>
        <div class="k-sub">{len(hard)} avaliadas · movem para quarentena</div>
        </div>
        <div class="sc-kpi">
        <div class="k-label">Regras leves</div>
        <div class="k-value" style="color:{GREEN if soft_fail == 0 else AMBER}">{soft_fail} alerta(s)</div>
        <div class="k-sub">{len(soft)} avaliadas · só no placar</div>
        </div>
        <div class="sc-kpi">
        <div class="k-label">Duplicidade medida</div>
        <div class="k-value">{f"{uniq * 100:.3f}%" if uniq is not None else "—"}</div>
        <div class="k-sub">taxa de duplicatas na frota</div>
        </div>
        </div>
        </div>
        """
    )

    dim_cards = []
    for dim in [
        "completeness",
        "accuracy",
        "consistency",
        "validity",
        "uniqueness",
    ]:
        row = df[df["dimension"] == dim]
        if row.empty:
            continue
        r = row.iloc[0]
        rate = safe_rate(r["pass_rate"])
        level = _level_for_rate(rate)
        color = _color_for_level(level)
        dim_cards.append(
            f"""
            <div class="sc-dim" style="border-top-color:{color}">
            <div class="d-name">{DIMENSION_LABELS.get(dim, dim)}</div>
            <div class="d-score" style="color:{color}">{rate * 100:.0f}%</div>
            <div class="d-meta">{int(r['rules_passed'])}/{int(r['rules_evaluated'])} regras</div>
            </div>
            """
        )
    if dim_cards:
        st.markdown("#### Dimensões DAMA")
        _html(f'<div class="sc-grid">{"".join(dim_cards)}</div>')

    # Radial / polar overview — more "scorecard" than a plain bar.
    fig = go.Figure(
        go.Scatterpolar(
            r=[safe_rate(r) * 100 for r in df["pass_rate"]],
            theta=[DIMENSION_LABELS.get(d, d) for d in df["dimension"]],
            fill="toself",
            fillcolor="rgba(56, 189, 248, 0.25)",
            line=dict(color="#38bdf8", width=2),
            marker=dict(size=7, color=[_rate_color(safe_rate(r)) for r in df["pass_rate"]]),
            hovertemplate="%{theta}: %{r:.1f}%<extra></extra>",
        )
    )
    fig.update_layout(
        title="Radar do placar por dimensão",
        polar=dict(
            bgcolor="rgba(0,0,0,0)",
            radialaxis=dict(
                visible=True,
                range=[0, 100],
                ticksuffix="%",
                gridcolor=GRID,
                linecolor=GRID,
            ),
            angularaxis=dict(gridcolor=GRID, linecolor=GRID),
        ),
        height=420,
        showlegend=False,
        **CHART_LAYOUT,
    )
    st.plotly_chart(fig, use_container_width=True)

    if not rules_df.empty:
        st.markdown("#### Detalhamento das regras")
        shown = rules_df.copy()
        shown["effect"] = shown["severity"].map(lambda s: SEVERITY_EFFECT.get(s, "—"))
        # Format measured as percent when threshold looks like a rate.
        st.dataframe(
            humanize(
                shown,
                columns=[
                    "rule",
                    "dimension",
                    "severity",
                    "scope",
                    "passed",
                    "measured",
                    "threshold",
                    "effect",
                ],
            ),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            "Críticas movem a corrida para quarentena. Leves pontuam o placar sem descartar a linha — "
            "senão as médias deixariam de representar a frota."
        )


# --------------------------------------------------------------------------- #
# 2. Profiling
# --------------------------------------------------------------------------- #
def render_profiling(run_id: str, executive: bool) -> None:
    rid = sql_literal(run_id)

    profile, err = safe_query(
        f"""
        SELECT layer, table_name, column_name, metric, metric_value
        FROM {fqn('governance', 'data_profile')}
        WHERE run_id = '{rid}'
        ORDER BY layer, table_name, column_name, metric
        """,
        "Sem perfilagem para esta execução.",
    )
    if err:
        st.warning(err)
        return
    if profile.empty:
        _empty("Sem perfilagem para esta execução.")
        return

    rows = profile[(profile["column_name"] == "*") & (profile["metric"] == "row_count")].copy()
    nulls = profile[profile["metric"] == "null_rate"].copy()
    numeric = profile[profile["metric"].isin(["min", "max", "avg"])].copy()

    if not rows.empty:
        cols = st.columns(len(rows))
        for col, (_, r) in zip(cols, rows.iterrows()):
            col.metric(
                f"{str(r['layer']).capitalize()} · linhas",
                f"{int(r['metric_value']):,}".replace(",", "."),
            )

    if executive:
        worst = nulls.sort_values("metric_value", ascending=False).head(5)
        st.markdown("#### Campos com mais lacunas")
        for _, r in worst.iterrows():
            rate = safe_rate(r["metric_value"])
            level = "ok" if rate < 0.05 else ("warn" if rate < 0.4 else "bad")
            _status_card(
                f"{r['column_name']} — {rate * 100:.1f}% sem valor",
                f"Camada {r['layer']}",
                level,
            )
        st.caption(
            "Lacunas em passageiros são esperadas: a operadora nem sempre informa o dado "
            "em corridas pagas em dinheiro, e optamos por manter essas corridas na base."
        )
        return

    # ---- Completeness (null_rate) ---------------------------------------- #
    st.markdown("#### Completude — valores ausentes")
    if not nulls.empty:
        chart = nulls.copy()
        chart["pct"] = chart["metric_value"].apply(lambda v: safe_rate(v) * 100)
        fig = px.bar(
            chart,
            x="column_name",
            y="pct",
            color="layer",
            barmode="group",
            title="Percentual de ausentes por coluna e camada",
            labels={"pct": "Ausentes (%)", "column_name": "Coluna", "layer": "Camada"},
            color_discrete_sequence=["#38bdf8", "#818cf8", "#c084fc"],
        )
        fig.update_layout(height=400, yaxis=dict(gridcolor=GRID), **CHART_LAYOUT)
        fig.update_xaxes(tickangle=-25)
        st.plotly_chart(fig, use_container_width=True)

    # ---- Numeric distribution (min / avg / max) -------------------------- #
    st.markdown("#### Distribuição numérica — mínimo, média e máximo")
    if numeric.empty:
        st.info("Sem métricas min/avg/max nesta execução.")
    else:
        # Prefer clean layer for the distribution chart (canonical typed model).
        prefer = numeric[numeric["layer"] == "clean"]
        plot_src = prefer if not prefer.empty else numeric
        wide = (
            plot_src.pivot_table(
                index="column_name",
                columns="metric",
                values="metric_value",
                aggfunc="first",
            )
            .reset_index()
            .rename_axis(None, axis=1)
        )
        for needed in ("min", "avg", "max"):
            if needed not in wide.columns:
                wide[needed] = float("nan")

        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                name="Mínimo",
                x=wide["column_name"],
                y=wide["min"],
                marker_color="#64748b",
                hovertemplate="%{x} mín: %{y:,.2f}<extra></extra>",
            )
        )
        fig.add_trace(
            go.Bar(
                name="Média",
                x=wide["column_name"],
                y=wide["avg"],
                marker_color="#38bdf8",
                hovertemplate="%{x} média: %{y:,.2f}<extra></extra>",
            )
        )
        fig.add_trace(
            go.Bar(
                name="Máximo",
                x=wide["column_name"],
                y=wide["max"],
                marker_color="#818cf8",
                hovertemplate="%{x} máx: %{y:,.2f}<extra></extra>",
            )
        )
        fig.update_layout(
            barmode="group",
            title="Camada clean — min / média / máx por coluna numérica",
            height=400,
            yaxis=dict(gridcolor=GRID, title="Valor"),
            xaxis=dict(title=None),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            **CHART_LAYOUT,
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "Ex.: `total_amount` mínimo negativo espelha ajustes/reembolsos TLC — "
            "por isso a regra correspondente é leve, não crítica."
        )

    # ---- Full profile matrix --------------------------------------------- #
    st.markdown("#### Matriz de perfilagem")
    cols_only = profile[profile["column_name"] != "*"].copy()
    if cols_only.empty:
        return

    matrix = (
        cols_only.pivot_table(
            index=["layer", "table_name", "column_name"],
            columns="metric",
            values="metric_value",
            aggfunc="first",
        )
        .reset_index()
        .rename_axis(None, axis=1)
    )
    # Stable column order matching the contract metrics declaration.
    ordered = ["layer", "table_name", "column_name", "null_rate", "min", "avg", "max"]
    present = [c for c in ordered if c in matrix.columns]
    matrix = matrix[present]

    display = matrix.copy()
    if "null_rate" in display.columns:
        display["null_rate"] = display["null_rate"].apply(
            lambda v: "—" if pd.isna(v) else f"{float(v) * 100:.2f}%"
        )
    for num_col in ("min", "avg", "max"):
        if num_col in display.columns:
            display[num_col] = display[num_col].apply(
                lambda v: "—" if pd.isna(v) else f"{float(v):,.4g}"
            )

    display = display.rename(
        columns={
            "layer": "Camada",
            "table_name": "Tabela",
            "column_name": "Coluna",
            "null_rate": "Ausentes",
            "min": "Mínimo",
            "avg": "Média",
            "max": "Máximo",
        }
    )
    st.dataframe(display, use_container_width=True, hide_index=True)
    st.caption(
        "Métricas declaradas no contrato (`row_count`, `null_rate`, `min`, `max`, `avg`) "
        "nas camadas raw → clean → consumption."
    )


# --------------------------------------------------------------------------- #
# 3. Quarantine — triage, aging, samples
# --------------------------------------------------------------------------- #
def render_incidents(run_id: str, executive: bool) -> None:
    rid = sql_literal(run_id)
    catalog = rule_catalog()

    age_df, age_err = safe_query(
        f"""
        SELECT
          COUNT(*) AS quarantined_rows,
          MIN(p.captured_at) AS quarantined_since,
          MIN(DATEDIFF(CURRENT_DATE(), DATE(p.captured_at))) AS min_days,
          MAX(DATEDIFF(CURRENT_DATE(), DATE(p.captured_at))) AS max_days,
          AVG(DATEDIFF(CURRENT_DATE(), DATE(p.captured_at))) AS avg_days
        FROM {fqn('clean', 'taxi_trips_quarantine')} q
        INNER JOIN (
          SELECT run_id, MAX(captured_at) AS captured_at
          FROM {fqn('governance', 'data_profile')}
          GROUP BY run_id
        ) p ON q.dq_run_id = p.run_id
        WHERE q.dq_run_id = '{rid}'
        """,
        "Nenhuma corrida foi isolada nesta execução.",
    )

    rules_df, rules_err = safe_query(
        f"""
        SELECT rule, incident_count
        FROM {fqn('governance', 'vw_incident_quarantine_top_rules')}
        WHERE run_id = '{rid}'
        ORDER BY incident_count DESC
        LIMIT 20
        """,
        "",
    )

    samples, samples_err = safe_query(
        f"""
        WITH base AS (
          SELECT
            q.vendor_id,
            q.passenger_count,
            q.total_amount,
            q.pickup_datetime,
            q.dropoff_datetime,
            q.taxi_type,
            q.year_month,
            q.dq_failed_rules,
            q.dq_dominant_dimension,
            p.captured_at AS quarantined_at,
            DATEDIFF(CURRENT_DATE(), DATE(p.captured_at)) AS days_in_quarantine,
            ROW_NUMBER() OVER (
              PARTITION BY COALESCE(q.dq_dominant_dimension, 'unknown')
              ORDER BY RAND()
            ) AS rn
          FROM {fqn('clean', 'taxi_trips_quarantine')} q
          INNER JOIN (
            SELECT run_id, MAX(captured_at) AS captured_at
            FROM {fqn('governance', 'data_profile')}
            GROUP BY run_id
          ) p ON q.dq_run_id = p.run_id
          WHERE q.dq_run_id = '{rid}'
        )
        SELECT
          vendor_id,
          passenger_count,
          total_amount,
          pickup_datetime,
          dropoff_datetime,
          taxi_type,
          year_month,
          dq_failed_rules,
          dq_dominant_dimension,
          quarantined_at,
          days_in_quarantine
        FROM base
        WHERE rn <= 5
        ORDER BY days_in_quarantine DESC, dq_dominant_dimension, total_amount
        """,
        "",
    )

    buckets, _ = safe_query(
        f"""
        SELECT
          CASE
            WHEN days_in_quarantine = 0 THEN 'Hoje'
            WHEN days_in_quarantine BETWEEN 1 AND 3 THEN '1–3 dias'
            WHEN days_in_quarantine BETWEEN 4 AND 7 THEN '4–7 dias'
            ELSE '8+ dias'
          END AS age_bucket,
          COUNT(*) AS rows
        FROM (
          SELECT DATEDIFF(CURRENT_DATE(), DATE(p.captured_at)) AS days_in_quarantine
          FROM {fqn('clean', 'taxi_trips_quarantine')} q
          INNER JOIN (
            SELECT run_id, MAX(captured_at) AS captured_at
            FROM {fqn('governance', 'data_profile')}
            GROUP BY run_id
          ) p ON q.dq_run_id = p.run_id
          WHERE q.dq_run_id = '{rid}'
        )
        GROUP BY 1
        ORDER BY
          CASE
            WHEN age_bucket = 'Hoje' THEN 1
            WHEN age_bucket = '1–3 dias' THEN 2
            WHEN age_bucket = '4–7 dias' THEN 3
            ELSE 4
          END
        """,
        "",
    )

    if age_err and (rules_df is None or rules_df.empty):
        st.warning(age_err)
        return

    n = int(age_df.iloc[0]["quarantined_rows"]) if not age_df.empty else 0
    if n == 0 and (rules_df is None or rules_df.empty):
        _empty("Nenhuma corrida foi isolada nesta execução — nada a investigar.")
        return

    max_days = int(age_df.iloc[0]["max_days"] or 0) if not age_df.empty else 0
    avg_days = float(age_df.iloc[0]["avg_days"] or 0) if not age_df.empty else 0.0
    since = age_df.iloc[0]["quarantined_since"] if not age_df.empty else None

    if not rules_df.empty:
        rules_df = rules_df.copy()
        rules_df["dimension"] = rules_df["rule"].map(
            lambda r: catalog.get(r, {}).get("dimension", "—")
        )
        rules_df["severity"] = rules_df["rule"].map(
            lambda r: catalog.get(r, {}).get("severity", "—")
        )

    if executive:
        _status_card(
            f"{n:,}".replace(",", ".") + " corridas isoladas",
            (
                f"Isoladas há {max_days} dia(s) · média {avg_days:.1f} dia(s) em quarentena."
                if since is not None
                else "Cada corrida saiu da base analítica por violar uma regra crítica."
            ),
            "warn" if n else "ok",
        )
        if not rules_df.empty:
            st.markdown("#### Principais motivos")
            for _, r in rules_df.head(5).iterrows():
                desc = catalog.get(r["rule"], {}).get("description") or r["rule"]
                _status_card(
                    f"{int(r['incident_count']):,}".replace(",", ".") + " corridas",
                    str(desc).strip().split("\n")[0][:180],
                    "warn",
                )
        return

    # ---- technical ------------------------------------------------------- #
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Linhas em quarentena", f"{n:,}".replace(",", "."))
    c2.metric("Dias em quarentena (máx)", max_days)
    c3.metric("Dias em quarentena (média)", f"{avg_days:.1f}")
    c4.metric(
        "Isolada desde",
        pd.to_datetime(since).strftime("%d/%m/%Y %H:%M") if since is not None else "—",
    )

    if not buckets.empty:
        fig_age = px.bar(
            buckets,
            x="age_bucket",
            y="rows",
            title="Envelhecimento da quarentena",
            labels={"age_bucket": "Idade", "rows": "Linhas"},
            color_discrete_sequence=["#f59e0b"],
        )
        fig_age.update_layout(height=320, yaxis=dict(gridcolor=GRID), **CHART_LAYOUT)
        st.plotly_chart(fig_age, use_container_width=True)

    if not rules_df.empty:
        st.markdown("#### Motivos (regras críticas)")
        fig = px.bar(
            rules_df,
            x="incident_count",
            y="rule",
            orientation="h",
            color="dimension",
            title="Regras que mais enviaram corridas para quarentena",
            labels={
                "incident_count": "Linhas afetadas",
                "rule": "Regra",
                "dimension": "Dimensão",
            },
        )
        fig.update_layout(
            height=max(300, 36 * len(rules_df)),
            xaxis=dict(gridcolor=GRID),
            yaxis=dict(autorange="reversed"),
            **CHART_LAYOUT,
        )
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(
            humanize(
                rules_df, columns=["rule", "dimension", "severity", "incident_count"]
            ),
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("#### Amostra de corridas isoladas")
    st.caption(
        "Até 5 exemplos por dimensão dominante, sorteados nesta execução — "
        "para inspeção sem varrer a tabela inteira."
    )
    if samples_err:
        st.warning(samples_err)
    elif samples.empty:
        _empty("Sem amostra disponível para esta execução.")
    else:
        shown = samples.copy()
        shown["dq_dominant_dimension"] = shown["dq_dominant_dimension"].map(
            lambda d: DIMENSION_LABELS.get(d, d) if pd.notna(d) else "—"
        )
        if "quarantined_at" in shown.columns:
            shown["quarantined_at"] = pd.to_datetime(shown["quarantined_at"]).dt.strftime(
                "%d/%m/%Y %H:%M"
            )
        for col in ("pickup_datetime", "dropoff_datetime"):
            if col in shown.columns:
                shown[col] = pd.to_datetime(shown[col]).dt.strftime("%d/%m/%Y %H:%M")
        if "total_amount" in shown.columns:
            shown["total_amount"] = shown["total_amount"].apply(
                lambda v: "—" if pd.isna(v) else f"US$ {float(v):,.2f}"
            )
        if "passenger_count" in shown.columns:
            shown["passenger_count"] = shown["passenger_count"].apply(
                lambda v: "—" if pd.isna(v) else f"{float(v):g}"
            )

        display = shown.rename(
            columns={
                "vendor_id": "Fornecedor",
                "passenger_count": "Passageiros",
                "total_amount": "Valor total",
                "pickup_datetime": "Embarque",
                "dropoff_datetime": "Desembarque",
                "taxi_type": "Frota",
                "year_month": "Mês",
                "dq_failed_rules": "Regras violadas",
                "dq_dominant_dimension": "Dimensão dominante",
                "quarantined_at": "Isolada em",
                "days_in_quarantine": "Dias em quarentena",
            }
        )
        st.dataframe(display, use_container_width=True, hide_index=True)

    st.caption(
        "A idade usa o instante em que a execução gravou a quarentena "
        "(`governance.data_profile.captured_at`). Próximas execuções também gravam "
        "`dq_quarantined_at` na própria linha."
    )


# --------------------------------------------------------------------------- #
# 4. Fitness for use
# --------------------------------------------------------------------------- #
def render_fitness(run_id: str, executive: bool) -> None:
    rid = sql_literal(run_id)

    df, err = safe_query(
        f"""
        SELECT use_case, rule, passed, measured, expected
        FROM {fqn('governance', 'vw_fitness_summary')}
        WHERE run_id = '{rid}'
        ORDER BY use_case, rule
        """,
        "Sem verificação de adequação ao uso para esta execução.",
    )
    if err:
        st.warning(err)
        return
    if df.empty:
        _empty("Sem verificação de adequação ao uso para esta execução.")
        return

    approved = int(df["passed"].sum())
    if executive:
        _status_card(
            f"{approved} de {len(df)} análises estão liberadas",
            "Cada item confirma que os dados publicados respondem à pergunta de negócio.",
            "ok" if approved == len(df) else "bad",
        )
        for _, row in df.iterrows():
            _status_card(
                FITNESS_PLAIN.get(row["rule"], str(row["use_case"])),
                "Verificado nesta execução",
                "ok" if bool(row["passed"]) else "bad",
            )
        return

    c1, c2 = st.columns(2)
    c1.metric("Verificações aprovadas", f"{approved}/{len(df)}")
    c2.metric("Casos de uso cobertos", df["use_case"].nunique())

    for _, row in df.iterrows():
        ok = bool(row["passed"])
        _status_card(
            f"{row['use_case']} · {row['rule']}",
            f"medido {row['measured']} · esperado {row['expected']}",
            "ok" if ok else "bad",
        )


# --------------------------------------------------------------------------- #
# 5. Business answers
# --------------------------------------------------------------------------- #
def render_q1_q2(run_id: str, executive: bool) -> None:
    rid = sql_literal(run_id)

    q1, err1 = safe_query(
        f"""
        SELECT year_month, avg_total_amount, trip_count
        FROM {fqn('consumption', 'kpi_yellow_avg_total_amount_monthly')}
        WHERE run_id = '{rid}'
        ORDER BY year_month
        """,
        "Q1 ainda não calculado nesta execução.",
    )
    q2, err2 = safe_query(
        f"""
        SELECT pickup_hour, avg_passenger_count, trip_count, null_passenger_count
        FROM {fqn('consumption', 'kpi_fleet_avg_passenger_count_hourly')}
        WHERE run_id = '{rid}'
        ORDER BY pickup_hour
        """,
        "Q2 ainda não calculado nesta execução.",
    )

    st.markdown("#### Q1 — valor médio por mês (táxis amarelos)")
    if err1 or q1.empty:
        _empty(err1 or "Q1 ainda não calculado nesta execução.")
    else:
        overall = q1["avg_total_amount"].mean()
        best = q1.loc[q1["avg_total_amount"].idxmax()]
        c1, c2 = st.columns(2)
        c1.metric("Média do período", f"US$ {overall:,.2f}")
        c2.metric("Mês mais alto", f"{best['year_month']} · US$ {best['avg_total_amount']:,.2f}")

        fig = px.line(
            q1,
            x="year_month",
            y="avg_total_amount",
            markers=True,
            labels={"year_month": "Mês", "avg_total_amount": "Valor médio (US$)"},
        )
        fig.update_traces(line_color="#38bdf8", line_width=3)
        fig.update_layout(height=340, yaxis=dict(gridcolor=GRID), **CHART_LAYOUT)
        st.plotly_chart(fig, use_container_width=True)
        if not executive:
            st.dataframe(
                humanize(q1, columns=["year_month", "avg_total_amount", "trip_count"]),
                use_container_width=True,
                hide_index=True,
            )

    st.markdown("#### Q2 — passageiros por hora do dia (maio, frota completa)")
    if err2 or q2.empty:
        _empty(err2 or "Q2 ainda não calculado nesta execução.")
    else:
        peak = q2.loc[q2["avg_passenger_count"].idxmax()]
        low = q2.loc[q2["avg_passenger_count"].idxmin()]
        c1, c2 = st.columns(2)
        c1.metric("Hora mais cheia", f"{int(peak['pickup_hour'])}h · {peak['avg_passenger_count']:.2f}")
        c2.metric("Hora mais vazia", f"{int(low['pickup_hour'])}h · {low['avg_passenger_count']:.2f}")

        fig = px.bar(
            q2,
            x="pickup_hour",
            y="avg_passenger_count",
            labels={"pickup_hour": "Hora do dia", "avg_passenger_count": "Passageiros (média)"},
        )
        fig.update_traces(marker_color="#818cf8")
        fig.update_layout(
            height=340,
            xaxis=dict(dtick=1),
            yaxis=dict(gridcolor=GRID),
            **CHART_LAYOUT,
        )
        st.plotly_chart(fig, use_container_width=True)
        if not executive:
            st.dataframe(
                humanize(
                    q2,
                    columns=[
                        "pickup_hour",
                        "avg_passenger_count",
                        "trip_count",
                        "null_passenger_count",
                    ],
                ),
                use_container_width=True,
                hide_index=True,
            )

    st.caption(
        "Os dois números vêm da camada já aprovada na qualidade e carregam a execução "
        "que os produziu, então cada métrica volta à sua evidência."
    )


# --------------------------------------------------------------------------- #
# 6. Lineage
# --------------------------------------------------------------------------- #
def render_lineage(run_id: str) -> None:
    rid = sql_literal(run_id)

    nodes = [
        ("raw.yellow_tripdata", f"SELECT COUNT(*) AS n FROM {fqn('raw', 'yellow_tripdata')}"),
        ("raw.green_tripdata", f"SELECT COUNT(*) AS n FROM {fqn('raw', 'green_tripdata')}"),
        ("clean.taxi_trips", f"SELECT COUNT(*) AS n FROM {fqn('clean', 'taxi_trips')}"),
        (
            "clean.taxi_trips_quarantine",
            f"SELECT COUNT(*) AS n FROM {fqn('clean', 'taxi_trips_quarantine')} "
            f"WHERE dq_run_id = '{rid}'",
        ),
        ("consumption.taxi_trips", f"SELECT COUNT(*) AS n FROM {fqn('consumption', 'taxi_trips')}"),
    ]

    counts: dict[str, int | None] = {}
    for name, sql in nodes:
        df, err = safe_query(sql, "")
        counts[name] = int(df.iloc[0]["n"]) if not err and not df.empty else None

    def fmt(name: str) -> str:
        v = counts.get(name)
        return f"{v:,}".replace(",", ".") if v is not None else "—"

    def node(title: str, rows: str, accent: str, note: str = "") -> str:
        sub = f'<div class="ln-note">{note}</div>' if note else ""
        return (
            f'<div class="ln-node" style="border-color:{accent}">'
            f'<div class="ln-title">{title}</div>'
            f'<div class="ln-rows">{rows}</div>{sub}</div>'
        )

    arrow = '<div class="ln-arrow">&#10230;</div>'

    # Rendered as plain HTML: st.graphviz_chart depends on a client-side renderer
    # that does not load reliably behind the Databricks Apps proxy.
    html = f"""
    <div class="ln-flow">
      <div class="ln-stage">
        <div class="ln-stage-label">Origem</div>
        {node("raw.yellow_tripdata", fmt("raw.yellow_tripdata") + " linhas", "#38bdf8")}
        {node("raw.green_tripdata", fmt("raw.green_tripdata") + " linhas", "#38bdf8")}
      </div>
      {arrow}
      <div class="ln-stage">
        <div class="ln-stage-label">Padronização + portão de qualidade</div>
        {node("clean.taxi_trips", fmt("clean.taxi_trips") + " linhas", "#22c55e", "aprovadas nas regras críticas")}
        {node("clean.taxi_trips_quarantine", fmt("clean.taxi_trips_quarantine") + " linhas", "#ef4444", "reprovadas — param aqui")}
      </div>
      {arrow}
      <div class="ln-stage">
        <div class="ln-stage-label">Consumo</div>
        {node("consumption.taxi_trips", fmt("consumption.taxi_trips") + " linhas", "#818cf8", "só o caminho aprovado segue")}
      </div>
      {arrow}
      <div class="ln-stage">
        <div class="ln-stage-label">Indicadores</div>
        {node("KPIs Q1 e Q2", "valor médio e passageiros/hora", "#c084fc")}
      </div>
    </div>
    """
    _html(html)
    st.caption(
        "As tabelas `governance.*` registram placar, perfilagem e adequação ao uso "
        "de cada etapa, com o mesmo identificador de execução."
    )

    fails, _ = safe_query(
        f"""
        SELECT COUNT(*) AS n
        FROM {fqn('governance', 'dq_validation_result')}
        WHERE run_id = '{rid}' AND severity = 'error' AND passed = false AND scope = 'row'
        """,
        "",
    )
    hard_fails = int(fails.iloc[0]["n"]) if not fails.empty else 0

    c1, c2 = st.columns(2)
    c1.metric("Regras críticas reprovadas", hard_fails)
    c2.metric(
        "Corridas contidas na quarentena",
        f"{counts.get('clean.taxi_trips_quarantine') or 0:,}".replace(",", "."),
    )
    st.caption(
        "A quarentena é o ponto de contenção: uma falha de qualidade para aqui e não "
        "chega à camada de consumo nem aos indicadores."
    )


# --------------------------------------------------------------------------- #
# 7. Contract / catalog
# --------------------------------------------------------------------------- #
def render_catalog() -> None:
    contract = load_contract()
    product = load_product()

    if not contract:
        st.error(
            "Contrato não encontrado no pacote do app. Rode `./scripts/deploy.sh`, "
            "que copia `contract.yaml` e `product.yaml` para `apps/dq_dashboard/contract/` "
            "antes do upload — o container do app não enxerga o Volume."
        )
        return

    info = contract.get("info") or {}
    sla = product.get("sla") or {}

    c1, c2, c3 = st.columns(3)
    c1.metric("Domínio", str(product.get("domain") or info.get("domain") or "—"))
    c2.metric("Responsável", str(product.get("owner") or info.get("owner") or "—"))
    c3.metric("Período coberto", str(sla.get("coverage_window") or "—"))

    st.markdown("#### Colunas entregues ao consumidor")
    st.dataframe(
        pd.DataFrame(
            [
                {"Coluna publicada": "vendor_id", "Nome de origem (TLC)": "VendorID", "Significado": "Fornecedor do taxímetro"},
                {"Coluna publicada": "passenger_count", "Nome de origem (TLC)": "passenger_count", "Significado": "Passageiros na corrida"},
                {"Coluna publicada": "total_amount", "Nome de origem (TLC)": "total_amount", "Significado": "Valor total cobrado"},
                {"Coluna publicada": "pickup_datetime", "Nome de origem (TLC)": "tpep_pickup_datetime", "Significado": "Início da corrida"},
                {"Coluna publicada": "dropoff_datetime", "Nome de origem (TLC)": "tpep_dropoff_datetime", "Significado": "Fim da corrida"},
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(
        "A view `consumption.vw_taxi_trips_tlc` republica as mesmas linhas sob os nomes "
        "originais do TLC esperados pelos consumidores."
    )

    st.markdown("#### Regras de qualidade combinadas")
    rules = contract.get("quality") or []
    if rules:
        rd = pd.DataFrame(rules)
        rd["effect"] = rd["severity"].map(lambda s: SEVERITY_EFFECT.get(s, "—"))
        st.dataframe(
            humanize(rd, columns=["name", "dimension", "severity", "scope", "effect"]),
            use_container_width=True,
            hide_index=True,
        )

    outputs = product.get("outputs") or []
    if outputs:
        st.markdown("#### Objetos publicados")
        st.dataframe(
            humanize(pd.DataFrame(outputs), columns=["fqn", "grain", "description"]),
            use_container_width=True,
            hide_index=True,
        )

    src = contract_source()
    if src:
        st.caption(f"Contrato lido de `{src}`")
