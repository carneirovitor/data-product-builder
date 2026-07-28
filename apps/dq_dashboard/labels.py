"""Human-readable labels — the UI never shows a raw column name."""

from __future__ import annotations

import pandas as pd

COLUMN_LABELS: dict[str, str] = {
    "run_id": "Execução",
    "dimension": "Dimensão",
    "rules_evaluated": "Regras avaliadas",
    "rules_passed": "Regras aprovadas",
    "pass_rate": "Aprovação",
    "quarantine_rate": "Quarentena",
    "uniqueness_metric": "Duplicidade",
    "rule": "Regra",
    "severity": "Severidade",
    "scope": "Escopo",
    "passed": "Situação",
    "measured": "Medido",
    "threshold": "Limite",
    "expected": "Esperado",
    "layer": "Camada",
    "table_name": "Tabela",
    "column_name": "Coluna",
    "metric": "Métrica",
    "metric_value": "Valor",
    "partition_key": "Partição",
    "captured_at": "Capturado em",
    "computed_at": "Calculado em",
    "incident_count": "Linhas afetadas",
    "use_case": "Caso de uso",
    "year_month": "Mês",
    "avg_total_amount": "Valor médio (US$)",
    "trip_count": "Corridas",
    "pickup_hour": "Hora do dia",
    "avg_passenger_count": "Passageiros (média)",
    "null_passenger_count": "Sem passageiro informado",
    "days_in_quarantine": "Dias em quarentena",
    "quarantined_at": "Isolada em",
    "quarantined_rows": "Linhas em quarentena",
    "age_bucket": "Idade",
    "dq_failed_rules": "Regras violadas",
    "dq_dominant_dimension": "Dimensão dominante",
    "taxi_type": "Frota",
    "vendor_id": "Fornecedor",
    "passenger_count": "Passageiros",
    "total_amount": "Valor total",
    "pickup_datetime": "Embarque",
    "dropoff_datetime": "Desembarque",
    "node": "Objeto",
    "rows": "Linhas",
    "fqn": "Objeto",
    "grain": "Granularidade",
    "description": "Descrição",
    "name": "Regra",
    "status": "Situação",
    "effect": "Efeito",
    "label": "Coluna",
}

DIMENSION_LABELS = {
    "completeness": "Completude",
    "accuracy": "Acurácia",
    "consistency": "Consistência",
    "validity": "Validade",
    "timeliness": "Atualidade",
    "uniqueness": "Unicidade",
}

DIMENSION_PLAIN = {
    "completeness": "Os campos e o recorte temporal esperados estão cobertos",
    "accuracy": "Os valores refletem o que foi cobrado, incluindo ajustes",
    "consistency": "As datas fazem sentido entre si (desembarque após embarque)",
    "validity": "Os valores respeitam as listas e faixas combinadas",
    "timeliness": "Os dados chegaram dentro do prazo combinado (SLA de frescor)",
    "uniqueness": "Duplicidade de corridas está sob controle",
}

SEVERITY_LABELS = {"error": "Crítica", "warning": "Leve"}

SCOPE_LABELS = {"row": "Linha", "aggregate": "Agregado"}

SEVERITY_EFFECT = {
    "error": "Remove a corrida (quarentena)",
    "warning": "Só registra no placar",
}

FITNESS_PLAIN = {
    "q1_months_present": "Há cinco meses completos de corridas amarelas para a média mensal.",
    "q2_hours_coverage": "Maio tem horas suficientes com movimento para a média por hora.",
    "consumption_schema_cdes": "A camada de consumo entrega todas as colunas combinadas.",
}

PERCENT_COLUMNS = {"pass_rate", "quarantine_rate", "uniqueness_metric"}
MONEY_COLUMNS = {"avg_total_amount"}


def label(column: str) -> str:
    return COLUMN_LABELS.get(column, column.replace("_", " ").capitalize())


def humanize(df: pd.DataFrame, *, columns: list[str] | None = None) -> pd.DataFrame:
    """Rename columns to labels and format rates, money and booleans for display."""
    if df is None or df.empty:
        return pd.DataFrame()

    out = df.copy()
    if columns:
        keep = [c for c in columns if c in out.columns]
        out = out[keep]

    for col in out.columns:
        if col in PERCENT_COLUMNS:
            out[col] = out[col].apply(
                lambda v: "—" if pd.isna(v) else f"{float(v) * 100:.1f}%"
            )
        elif col in MONEY_COLUMNS:
            out[col] = out[col].apply(
                lambda v: "—" if pd.isna(v) else f"US$ {float(v):,.2f}"
            )
        elif col == "dimension":
            out[col] = out[col].map(lambda d: DIMENSION_LABELS.get(d, d))
        elif col == "severity":
            out[col] = out[col].map(lambda s: SEVERITY_LABELS.get(s, s))
        elif col == "scope":
            out[col] = out[col].map(lambda s: SCOPE_LABELS.get(s, s))
        elif col == "passed":
            out[col] = out[col].map(lambda p: "Aprovado" if bool(p) else "Reprovado")
        elif col in {"trip_count", "rows", "incident_count", "null_passenger_count"}:
            out[col] = out[col].apply(
                lambda v: "—" if pd.isna(v) else f"{int(v):,}".replace(",", ".")
            )

    return out.rename(columns={c: label(c) for c in out.columns})


def safe_rate(value) -> float:
    """NaN-safe rate — `nan or 0` returns nan, which then renders as 'nan%'."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if pd.isna(v) else v


def run_option_label(run_id: str, captured) -> str:
    """Runs are opaque IDs; lead with the timestamp so a human can pick one."""
    if captured is None or pd.isna(captured):
        return str(run_id)
    ts = pd.to_datetime(captured)
    return f"{ts:%d/%m/%Y %H:%M} · {str(run_id)[-8:]}"
