# Portal de Data Quality & Observability

Interface gráfica do data product: qualidade e confiabilidade dos dados em primeiro plano; o catálogo é pano de fundo.

**Implementação:** [`apps/dq_dashboard/`](apps/dq_dashboard/) — Databricks App (Streamlit) lendo
tabelas `governance.*` e `consumption.kpi_*` ao vivo via SQL warehouse.

> Números Q1/Q2 e limitações conscientes: seção das perguntas de negócio no
> [`README.md`](README.md). Este arquivo cobre só a UI.

---

## Capacidade → tela

| Capacidade de governança / DQ | Onde aparece na UI |
|---|---|
| Dimensões DAMA | Aba **Placar de qualidade** (nota + grid + radar) |
| Scorecards de confiabilidade | Mesma aba (pass rate, quarentena, hard vs soft) |
| Data Incident Response | Aba **Quarentena** (motivos + amostra + dias isolada) |
| Profiling e anomalias | Aba **Perfilagem** (`null_rate`, min/avg/max, matriz) + `volume_sanity` no contrato |
| Metadados / contrato | Aba **Contrato** (YAML empacotado em `apps/dq_dashboard/contract/`) |
| Traduzir complexidade | Toggle **Visão executiva** |
| Linhagem (narrativa) | Aba **Linhagem** — topologia do produto + `COUNT(*)` reais (não é UC Lineage) |

---

## Arquitetura da UI

```text
Sidebar: execução (data + sufixo do ID) + toggle visão executiva
    │
    ├─ Placar de qualidade  ← vw_dq_scorecard, dq_validation_result
    ├─ Perfilagem           ← data_profile (row_count, null_rate, min, max, avg)
    ├─ Quarentena           ← vw_incident_* + sample de clean.taxi_trips_quarantine
    ├─ Adequação ao uso     ← vw_fitness_summary
    ├─ Q1 / Q2              ← consumption.kpi_*
    ├─ Linhagem             ← COUNT(*) por camada + hard fails no run
    └─ Contrato             ← contract.yaml + product.yaml (bundle do app)
```

**Decisões de negócio visíveis na UI** (não escondidas):

- `passenger_count` fora de 1–6 → **soft** (não quarentena) — Q2 representa a frota hard-approved
- `total_amount` negativo → **soft** — Q1 inclui ajustes TLC
- Limite de quarentena **5%** (`quarantine_rate_cap`) no placar

---

## Como executar

### Pré-requisito

Pipeline rodado ao menos uma vez (`./scripts/deploy.sh`) para popular `governance.*` e `kpi_*`.

### Deploy do App

`scripts/deploy.sh` copia o contrato para `apps/dq_dashboard/contract/` (o container do app
**não** monta UC Volumes). Depois:

```bash
databricks bundle deploy -t dev
databricks apps deploy taxi-dq-observability \
  --source-code-path /Workspace/Users/<you>/.bundle/taxi_data_product/dev/files/apps/dq_dashboard
```

Abra pelo workspace: **Compute → Apps → taxi-dq-observability**.

### GRANTs (service principal do app)

```sql
GRANT USE CATALOG ON CATALOG workspace TO `<app-sp-application-id>`;
GRANT USE SCHEMA, SELECT ON SCHEMA workspace.governance TO `<app-sp-application-id>`;
GRANT USE SCHEMA, SELECT ON SCHEMA workspace.consumption TO `<app-sp-application-id>`;
GRANT USE SCHEMA, SELECT ON SCHEMA workspace.clean TO `<app-sp-application-id>`;
GRANT USE SCHEMA, SELECT ON SCHEMA workspace.raw TO `<app-sp-application-id>`;
```

Mais `CAN_USE` no SQL warehouse (via UI ou permissions API).

---

## Roteiro de demo (5 min)

1. Arquitetura raw → clean/quarantine → consumption (30s).
2. Contrato: hard vs soft e por quê (60s).
3. Placar + Quarentena com amostra (60s).
4. Q1/Q2 na aba (60s).
5. Fitness (30s).
6. Limitações: linhagem UI ≠ UC; App é observabilidade, não o core (30s).
