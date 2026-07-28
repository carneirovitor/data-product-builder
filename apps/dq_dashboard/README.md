# DQ Observability Portal (Streamlit)

Portal de **Data Quality & Reliability** para o data product `mobility_taxi_trips`.
Lê as tabelas `governance.*` e `consumption.kpi_*` **ao vivo** via SQL warehouse —
sem dados mockados.

## Telas

| Aba (visão técnica) | Fonte |
|-----|--------|
| Placar de qualidade | `governance.vw_dq_scorecard`, `dq_validation_result` |
| Perfilagem | `governance.data_profile` |
| Quarentena | `governance.vw_incident_quarantine_top_rules` |
| Adequação ao uso | `governance.vw_fitness_summary` |
| Q1 / Q2 | `consumption.kpi_*` |
| Linhagem | contagens por camada + regras críticas falhando |
| Contrato | `contract.yaml` + `product.yaml` empacotados em `contract/` |

O toggle **Visão executiva** não é um verniz sobre a mesma tela: troca as sete abas por
três (*Podemos confiar?*, *Respostas do negócio*, *O que foi combinado*), substitui gráficos
técnicos por cartões de status em linguagem de negócio e esconde as tabelas de detalhe.

Nomes de coluna nunca chegam à tela — `labels.py` centraliza rótulos, formatação de
percentual/moeda e o tratamento de `NaN`. O seletor de execução mostra data e hora, com
o sufixo do ID apenas para desempate.

### Contrato dentro do app

O container do app recebe **somente** `apps/dq_dashboard/` e **não monta UC Volumes**, então
`REPO_ROOT` não existe em runtime. `scripts/deploy.sh` copia `contract.yaml` e `product.yaml`
para `apps/dq_dashboard/contract/` antes do upload (diretório gerado, fora do Git).
Localmente o app continua achando os arquivos subindo a árvore do repositório.

## Local (CLI autenticado)

```bash
cd apps/dq_dashboard
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export CATALOG=workspace
export REPO_ROOT=/caminho/para/data-product-builder
export DATABRICKS_WAREHOUSE_ID=<seu-warehouse-id>

streamlit run app.py
```

## Deploy no Databricks Free Edition

1. Rode o pipeline pelo menos uma vez (`./scripts/deploy.sh`) para popular `governance.*`.
2. Ajuste `DATABRICKS_WAREHOUSE_ID` em `app.yaml` se o warehouse for outro.
3. Deploy do bundle e do app:

```bash
databricks bundle validate -t dev
databricks bundle deploy -t dev
databricks bundle run dq_observability -t dev
```

> **Porta:** o app usa `run.py`, que lê `DATABRICKS_APP_PORT` (geralmente **8000**).
> Não hardcode `8080` — o proxy do Databricks encaminha só para a porta do runtime;
> escutar em outra porta gera *App Not Available* mesmo com status RUNNING.

> Free Edition: mantenha **um** app deployado por vez (cota de apps).  
> Abra pelo workspace: **Compute → Apps → taxi-dq-observability → Open** (mesma conta logada).

### GRANTs para o service principal do app

Substitua `<app-sp>` pelo principal do app (Compute → Apps → seu app → Service principal):

```sql
GRANT USE CATALOG ON CATALOG workspace TO `<app-sp>`;
GRANT USE SCHEMA, SELECT ON SCHEMA workspace.governance TO `<app-sp>`;
GRANT USE SCHEMA, SELECT ON SCHEMA workspace.consumption TO `<app-sp>`;
GRANT USE SCHEMA, SELECT ON SCHEMA workspace.clean TO `<app-sp>`;
GRANT USE SCHEMA, SELECT ON SCHEMA workspace.raw TO `<app-sp>`;
GRANT CAN USE ON WAREHOUSE `<warehouse-name>` TO `<app-sp>`;
```

## Capacidade → UI

| Capacidade de governança / DQ | Onde na UI |
|---|---|
| Dimensões DAMA | Aba DQ Scorecard |
| Scorecards de confiabilidade | Aba DQ Scorecard |
| Data Incident Response | Aba Incident Response |
| Profiling / anomalias | Aba Profiling + regra `volume_sanity` no contrato |
| Metadados, linhagem, classificação | Abas Linhagem + Contrato |
| Linguagem acessível | Toggle Visão executiva (troca as abas, não só o texto) |
| Data Contracts em produção | Aba Contrato |
