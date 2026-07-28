# Corridas de táxi em NY — com qualidade e governança de verdade

**Idioma:** [English](README.md) · **Português**

Olá. Este repo foi criado para demonstrar como podemos traduzir frameworks de **Governança de Dados** na linguagem de **Engenharia de Dados**.

O exemplo prático é um **data product** de corridas de táxi NYC: os números das [perguntas de negócio](files/business_questions.pt.md) só são confiáveis se a gente souber **o que entrou**, **o que foi rejeitado**, **por quê**, e **se o produto ainda serve para a pergunta**.

Se você tem pouco tempo, leia nesta ordem:

1. [As respostas às perguntas de negócio](#as-respostas-às-perguntas-de-negócio) — os números
2. [Como pensamos na qualidade dos dados](#como-pensamos-na-qualidade-dos-dados) — a decisão mais importante
3. [Por que o repositório é assim](#por-que-o-repositório-é-assim) — racional (mesh, governança como código, escala)
4. [O que foi construído](#o-que-foi-construído) — panorama em uma tela
5. [Como rodar](#como-rodar) — se quiser reproduzir
6. [O que eu deliberadamente não fiz](#o-que-eu-deliberadamente-não-fiz) — limites honestos

O detalhe técnico (arquivos, jobs, contrato) está no final, em [Anexo técnico](#anexo-técnico).

---

## As respostas às perguntas de negócio

Escopo: táxis **yellow + green**, janeiro a maio de 2023 (~16,5 milhões de corridas na camada de consumo; 908 isoladas em quarentena no último run).

### Pergunta 1 — média de `total_amount` por mês (yellow)

| Mês      | Média     | Corridas |
| -------- | --------- | -------- |
| Jan/2023 | US$ 27,02 | 3,07 mi  |
| Fev/2023 | US$ 26,90 | 2,91 mi  |
| Mar/2023 | US$ 27,80 | 3,40 mi  |
| Abr/2023 | US$ 28,27 | 3,29 mi  |
| Mai/2023 | US$ 28,96 | 3,51 mi  |

A média mensal sobe ao longo do período (cerca de **US$ 27,8** se olharmos a média das médias). O valor vem da frota yellow já aprovada nas regras críticas de qualidade.

### Pergunta 2 — média de `passenger_count` por hora (maio, frota toda)

Em maio, a ocupação média ao longo do dia fica perto de **1,36 passageiros**. A madrugada é um pouco mais cheia (1,44 por volta das 2h); o começo da manhã é o vale (1,24 por volta das 6h).

Uma observação importante: muita corrida vem sem `passenger_count` preenchido (pagamento em dinheiro, por exemplo). Se a gente **jogasse fora** essas linhas, a média deixaria de representar a frota. Por isso essa regra é leve — aparece no placar, mas não remove a corrida. Detalhe na próxima seção.

**Onde consultar no lake**

```sql
SELECT * FROM workspace.consumption.kpi_yellow_avg_total_amount_monthly;
SELECT * FROM workspace.consumption.kpi_fleet_avg_passenger_count_hourly;
```

SQL que gera esses números: [`domains/mobility/taxi_trips/consumption/metrics/`](domains/mobility/taxi_trips/consumption/metrics/).

---

## Como pensamos na qualidade dos dados
O objetivo aqui é garantir a confiança nas respostas das perguntas de negócio.

- Regras **críticas** (timestamps nulos, desembarque antes do embarque, mês fora da janela…) → a corrida vai para **quarentena** e não entra na análise.
- Regras **leves** (`passenger_count` fora de 1–6, `total_amount` negativo) → entram no **placar**, mas a linha segue. Negativos no TLC costumam ser ajuste/reembolso; passageiro ausente é ruído conhecido da fonte — não um erro de pipeline.

Esse trade-off está escrito no [contrato](domains/mobility/taxi_trips/contract.yaml) como política e espelhado no SodaCL.

As dimensões que usamos (completude, acurácia, consistência, validade, unicidade) seguem a lógica DAMA. **Temporalidade/frescor** não entra neste produto: o recorte é batch histórico Jan–Mai/2023, sem SLA de streaming — cobertura dos cinco meses é **completude da janela**, não “dado chegou a tempo”. O scorecard por dimensão vive em `governance.vw_dq_scorecard`.

Também checamos **adequação ao uso**: os cinco meses da Q1 existem? Maio tem cobertura horária para a Q2? A camada de consumo entrega as colunas combinadas? Isso fica em `governance.fitness_for_use_result`.

---

## Por que o repositório é assim

O racional foi traduzir ideias de **data mesh** e de **governança federada** — que na empresa costumam viver em PDF, comitê e RACI — para algo que o pipeline **executa**.

### Inspiração em data mesh

- **Domínio dono do produto.** Mobility é responsável por `taxi_trips`: schema, regras, severidade e o SQL que materializa cada camada. Não é um "data-team" centralizando todas políticas, responsabilidades e decisões.

- **Produto com interface clara.** O consumidor recebe `consumption.*` (e a view com os nomes TLC originais). Quarentena e scorecard são para operação de confiabilidade e contexto.
- **Self-serve com plataforma fina.** Jobs genéricos (`sql_runner`, `soda_runner`, `governance_engine`) não conhecem a regra de negócio do táxi — leem o contrato e os `.sql` do domínio. A plataforma habilita; o domínio decide.

### Governança federada — como código (computacional)

Governança central no papel define política e torce para alguém cumprir. Aqui a mesma intenção vira artefato versionado:

| No mundo “papel”                                 | Aqui                                                                     |
| ------------------------------------------------ | ------------------------------------------------------------------------ |
| Dicionário / política em portais corporativos    | [`contract.yaml`](domains/mobility/taxi_trips/contract.yaml) (DCS 0.9.3) |
| Checklist de qualidade em planilhas              | SodaCL + gate no `build_clean` (hard/soft)                               |
| Steward “responsável” em planilhas e outros docs | Owner no contrato/produto + PR que muda a regra                          |
| Comitê descobre incidente depois                 | Quarentena com trilha `dq_failed_rules` no mesmo run                     |
| “Será que ainda serve para a pergunta?”          | `fitness_for_use` amarrado a Q1/Q2                                       |

Mudou a política → diff no Git. O job falha alto se a regra crítica quebra. Isso é **governança computacional**: a regra não só documenta — ela **roda**.

### O que torna isso escalável

O desenho do repo permite crescer sem reescrever o motor:

1. **Novo KPI** → um arquivo em `consumption/metrics/*.sql` (+ entrada no contrato). O job `run_analysis` materializa o que estiver na pasta.
2. **Novo data product** → pasta irmã sob `domains/<domínio>/…` com contrato, checks e models. Os jobs de plataforma continuam os mesmos.
3. **Nova regra de qualidade** → declaração no contrato + check Soda espelhado. Severidade decide se isola linha ou só pontua o placar.
4. **Mesma topologia, outro orquestrador** → [`orchestration/pipeline.yaml`](orchestration/pipeline.yaml) descreve o grafo; o Databricks Bundle é quem materializa e dispara o job hoje.

Em resumo: escala por **convenção e declaração**, não por copiar notebook. O custo de um produto a mais é pasta + YAML + SQL, não um pipeline novo inventado do zero.

---

## O que foi construído

```text
Arquivos TLC (landing)
        ↓
   raw (imutável)          ← ingestão PySpark
        ↓
   clean  ──→  quarentena  ← portão de qualidade (Soda + contrato)
        ↓
   consumption             ← SQL para o consumidor + KPIs Q1/Q2
        ↓
   governance              ← placar, perfilagem, fitness, incidentes
```

As cinco colunas TLC esperadas pelos consumidores estão em:

```sql
SELECT VendorID, passenger_count, total_amount,
       tpep_pickup_datetime, tpep_dropoff_datetime
FROM workspace.consumption.vw_taxi_trips_tlc;
```

Por baixo, o modelo canônico usa nomes em snake_case (`vendor_id`, `pickup_datetime`…). Yellow e green chegam com prefixos diferentes (`tpep_*` / `lpep_*`); unificar em `tpep_*` mentiria sobre metade da frota. A view TLC republica os nomes de origem **sem duplicar** a tabela.

Há também um Streamlit no Databricks (`apps/dq_dashboard/`) com scorecard, profiling, amostra da quarentena, respostas Q1/Q2 e o contrato. Detalhes em [`report.md`](report.md).

---

## Como rodar

**No Databricks Free Edition** (Community Edition foi descontinuada):

```bash
# 1) Sobe yellow/green Jan–Mai para o Volume de landing (uma vez)
# 2) Sincroniza código, faz deploy e executa o job
./scripts/deploy.sh
```

Isso materializa `raw` / `clean` / `consumption` / `governance` e as tabelas de KPI.

Portal de observabilidade (opcional na demo):

```bash
databricks apps deploy taxi-dq-observability
# Abrir em Compute → Apps → taxi-dq-observability
```

**Local** (contrato + testes sem precisar do lake):

```bash
pip install -r requirements-dev.txt
python src/jobs/validate_contract.py
pytest tests/ -q
```

Passo a passo completo (Volume, permissões do app): [Anexo técnico](#anexo-técnico).

---

## O que eu deliberadamente não fiz

- **Não usei Great Expectations / PyDeequ no runtime.** Requisitos de DQ vivem no contrato de dados; a execução das checks de linha é Soda Core, leve no serverless.
- **O Streamlit é apenas cereja do bolo**, de forma alguma o core da solução. O core é contrato → quality gate → consumo → KPIs auditáveis por `run_id`.
- **FHV / FHVHV ficaram de fora.** O escopo do produto é táxi (yellow/green); misturar app de frota bagunçaria as perguntas de preço e ocupação.
- **Quarentena é reescrita a cada execução** do clean. “Há quantos dias isolada?” mede a idade daquela execução, não um histórico infinito de incidentes.

---

## Mapa rápido do repositório

| Se você quer…                          | Abra…                                                                                                                                        |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| Perguntas de negócio                   | [`files/business_questions.pt.md`](files/business_questions.pt.md) · [`EN`](files/business_questions.md)                                      |
| A política (schema, regras, ownership) | [`domains/mobility/taxi_trips/contract.yaml`](domains/mobility/taxi_trips/contract.yaml)                                                     |
| As checks executáveis                  | [`domains/mobility/taxi_trips/data_quality/checks.yml`](domains/mobility/taxi_trips/data_quality/checks.yml)                                 |
| SQL da Q1 / Q2                         | [`domains/mobility/taxi_trips/consumption/metrics/`](domains/mobility/taxi_trips/consumption/metrics/)                                       |
| View com nomes TLC originais           | [`domains/mobility/taxi_trips/consumption/views/vw_taxi_trips_tlc.sql`](domains/mobility/taxi_trips/consumption/views/vw_taxi_trips_tlc.sql) |
| Notebook de verificação (SQL read-only)| [`notebooks/verify_business_questions.py`](notebooks/verify_business_questions.py)                                                           |
| Jobs do pipeline                       | [`src/jobs/`](src/jobs/)                                                                                                                     |
| Portal DQ                              | [`apps/dq_dashboard/`](apps/dq_dashboard/) · [`report.md`](report.md)                                                                        |

---

## Anexo técnico

### Camadas e objetos

| Camada      | Objeto principal                                            | Como nasce                   |
| ----------- | ----------------------------------------------------------- | ---------------------------- |
| raw         | `yellow_tripdata`, `green_tripdata`                         | PySpark (`ingest_raw`)       |
| clean       | `taxi_trips` + `taxi_trips_quarantine`                      | SQL canônico + gate Soda     |
| consumption | `taxi_trips`, `vw_taxi_trips_tlc`, `kpi_*`                  | SQL models / metrics / views |
| governance  | `data_profile`, `dq_validation_result`, `fitness_*`, `vw_*` | profiling + views SQL        |

Cada arquivo em `*/models/*.sql` ou `*/metrics/*.sql` **é** o objeto: o job só resolve `${catalog}` / `${run_id}` e materializa. Adicionar um KPI = adicionar um `.sql`.

### Especificação baseada nas dimensões de DQ

Fonte: [`contract.yaml`](domains/mobility/taxi_trips/contract.yaml).

| Regra                               | Dimensão     | Severidade | Efeito      |
| ----------------------------------- | ------------ | ---------- | ----------- |
| `vendor_id` not null                | completude   | error      | Quarentena  |
| `total_amount` not null             | completude   | error      | Quarentena  |
| `pickup_datetime` not null          | completude   | error      | Quarentena  |
| `dropoff_datetime` not null         | completude   | error      | Quarentena  |
| `year_month` na janela Jan–Mai/2023 | completude   | error      | Quarentena  |
| `dropoff` ≥ `pickup`                | consistência | error      | Quarentena  |
| `taxi_type` ∈ {yellow, green}       | validade     | error      | Quarentena  |
| Cobertura agregada dos 5 meses      | completude   | error      | Falha o job |
| `passenger_count` entre 1 e 6       | validade     | warning    | Só placar   |
| `total_amount` ≥ 0                  | acurácia     | warning    | Só placar   |
| `vendor_id` ∈ {1, 2}                | validade     | warning    | Só placar   |
| Taxa de quarentena < 5%             | acurácia     | warning    | Só placar   |
| Taxa de duplicata aproximada        | unicidade    | warning    | Só placar   |
| Volume mensal vs mediana            | completude   | warning    | Só placar   |

### Metadados no Unity Catalog

Depois de publicar, descrições e tags do contrato vão para a metastore (Comments + Tags). Confira no Catalog Explorer em `workspace.consumption.taxi_trips`, ou:

```sql
SELECT column_name, comment
FROM workspace.information_schema.columns
WHERE table_schema = 'consumption' AND table_name = 'taxi_trips';
```

### Orquestração

- Topologia: [`orchestration/pipeline.yaml`](orchestration/pipeline.yaml)
- Databricks: [`databricks.yml`](databricks.yml) — job `taxi_data_product`

Fluxo: `ingest_raw` → `build_clean` → `publish_consumption` → `run_analysis`.

### Execução local completa

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export PYTHONPATH=.

python src/jobs/validate_contract.py
pytest tests/ -q

python src/jobs/ingest_raw.py --landing-path files
python src/jobs/build_clean.py
python src/jobs/publish_consumption.py
python src/jobs/run_analysis.py
```

### Databricks — upload + deploy

Volume de landing padrão: `/Volumes/workspace/default/taxi_landing`.

```bash
for f in files/{yellow,green}_tripdata_2023-0{1,2,3,4,5}.parquet; do
  databricks fs cp "$f" "dbfs:/Volumes/workspace/default/taxi_landing/$(basename "$f")" --overwrite
done

./scripts/deploy.sh
```

O script sincroniza `domains/`, `platform/` e `src/` no Volume de código (os jobs leem daí no serverless), faz o deploy do bundle e dispara o pipeline. Use `--no-run` se quiser só sincronizar/deployar.

Observabilidade: portal Streamlit em [`apps/dq_dashboard/`](apps/dq_dashboard/) — ver [`report.md`](report.md).

### Padrão do contrato

Usamos como base o [Data Contract Specification 0.9.3](https://datacontract.com/).
