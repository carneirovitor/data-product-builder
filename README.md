# NYC taxi trips — real data quality and governance

**Language:** **English** · [Português](README.pt.md)

Hi. This repo shows how to translate **Data Governance** frameworks into the language of **Data Engineering**.

The working example is an NYC taxi **data product**: the [business questions](files/business_questions.md) are only trustworthy if we know **what landed**, **what was rejected**, **why**, and **whether the product still answers the question**.

Short on time? Read in this order:

1. [Answers to the business questions](#answers-to-the-business-questions) — the numbers
2. [How we think about data quality](#how-we-think-about-data-quality) — the most important decision
3. [Why the repository looks like this](#why-the-repository-looks-like-this) — rationale (mesh, governance as code, scale)
4. [What was built](#what-was-built) — one-screen overview
5. [How to run](#how-to-run) — if you want to reproduce
6. [What I deliberately did not do](#what-i-deliberately-did-not-do) — honest limits

Technical detail (files, jobs, contract) is at the end, in [Technical appendix](#technical-appendix).

---

## Answers to the business questions

Scope: **yellow + green** taxis, January–May 2023 (~16.5M trips in consumption; 908 quarantined in the latest run).

### Question 1 — average `total_amount` per month (yellow)

| Month    | Average   | Trips   |
| -------- | --------- | ------- |
| Jan/2023 | US$ 27.02 | 3.07M   |
| Feb/2023 | US$ 26.90 | 2.91M   |
| Mar/2023 | US$ 27.80 | 3.40M   |
| Apr/2023 | US$ 28.27 | 3.29M   |
| May/2023 | US$ 28.96 | 3.51M   |

The monthly average rises over the window (about **US$ 27.8** as the mean of monthly means). Figures come from the yellow fleet after hard quality rules.

### Question 2 — average `passenger_count` by hour (May, full fleet)

In May, average occupancy across the day sits near **1.36 passengers**. Late night is a bit fuller (~1.44 around 2am); early morning is the trough (~1.24 around 6am).

Important: many trips arrive without `passenger_count` (cash payments, for example). If we **dropped** those rows, the average would stop representing the fleet. So that rule is soft — it shows on the scorecard but does not remove the trip. Detail in the next section.

**Where to query in the lake**

```sql
SELECT * FROM workspace.consumption.kpi_yellow_avg_total_amount_monthly;
SELECT * FROM workspace.consumption.kpi_fleet_avg_passenger_count_hourly;
```

SQL that produces these numbers: [`domains/mobility/taxi_trips/consumption/metrics/`](domains/mobility/taxi_trips/consumption/metrics/).

---

## How we think about data quality

The goal here is to keep trust in the answers to the business questions.

- **Hard** rules (null timestamps, dropoff before pickup, month outside the window…) → the trip goes to **quarantine** and does not enter analysis.
- **Soft** rules (`passenger_count` outside 1–6, negative `total_amount`) → they hit the **scorecard**, but the row stays. TLC negatives are often adjustments/refunds; missing passenger count is known source noise — not a pipeline bug.

That trade-off is written in the [contract](domains/mobility/taxi_trips/contract.yaml) as policy and mirrored in SodaCL.

The dimensions we use (completeness, accuracy, consistency, validity, uniqueness) follow DAMA thinking. **Timeliness/freshness** is out of scope for this product: the slice is a historical Jan–May/2023 batch with no streaming SLA — covering the five months is **window completeness**, not “data arrived on time”. The per-dimension scorecard lives in `governance.vw_dq_scorecard`.

We also check **fitness for use**: do Q1’s five months exist? Does May have hourly coverage for Q2? Does consumption expose the contracted columns? That lives in `governance.fitness_for_use_result`.

---

## Why the repository looks like this

The rationale was translating **data mesh** and **federated governance** — which in companies often live as PDFs, committees, and RACI charts — into something the pipeline **executes**.

### Data mesh inspiration

- **Domain owns the product.** Mobility owns `taxi_trips`: schema, rules, severity, and the SQL that materializes each layer. It is not a central “data team” owning every policy, accountability, and decision.
- **Clear product interface.** Consumers get `consumption.*` (plus the view with original TLC names). Quarantine and the scorecard support reliability operations and context.
- **Self-serve with a thin platform.** Generic jobs (`sql_runner`, `soda_runner`, `governance_engine`) do not know taxi business rules — they read the contract and the domain `.sql` files. The platform enables; the domain decides.

### Federated governance — as code (computational)

Paper-central governance defines policy and hopes someone complies. Here the same intent becomes a versioned artifact:

| In the “paper” world                              | Here                                                                     |
| ------------------------------------------------- | ------------------------------------------------------------------------ |
| Dictionary / policy in corporate portals          | [`contract.yaml`](domains/mobility/taxi_trips/contract.yaml) (DCS 0.9.3) |
| Quality checklists in spreadsheets                | SodaCL + gate in `build_clean` (hard/soft)                               |
| Steward “accountable” in sheets and other docs    | Owner on contract/product + PR that changes the rule                     |
| Committee discovers the incident later            | Quarantine with `dq_failed_rules` trail on the same run                  |
| “Does it still answer the question?”              | `fitness_for_use` tied to Q1/Q2                                          |

Policy change → Git diff. The job fails loud if a hard rule breaks. That is **computational governance**: the rule does not only document — it **runs**.

### What makes this scalable

The repo design grows without rewriting the engine:

1. **New KPI** → a file under `consumption/metrics/*.sql` (+ contract entry). `run_analysis` materializes whatever is in the folder.
2. **New data product** → a sibling folder under `domains/<domain>/…` with contract, checks, and models. Platform jobs stay the same.
3. **New quality rule** → declare it in the contract + mirrored Soda check. Severity decides quarantine vs scorecard-only.
4. **Same topology, different orchestrator** → [`orchestration/pipeline.yaml`](orchestration/pipeline.yaml) describes the graph; the Databricks Bundle materializes and triggers the job today.

In short: scale by **convention and declaration**, not by cloning notebooks. The cost of one more product is folder + YAML + SQL, not a pipeline invented from scratch.

---

## What was built

```text
TLC files (landing)
        ↓
   raw (immutable)         ← PySpark ingest
        ↓
   clean  ──→  quarantine  ← quality gate (Soda + contract)
        ↓
   consumption             ← consumer SQL + Q1/Q2 KPIs
        ↓
   governance              ← scorecard, profiling, fitness, incidents
```

The five TLC columns consumers expect are here:

```sql
SELECT VendorID, passenger_count, total_amount,
       tpep_pickup_datetime, tpep_dropoff_datetime
FROM workspace.consumption.vw_taxi_trips_tlc;
```

Underneath, the canonical model uses snake_case (`vendor_id`, `pickup_datetime`…). Yellow and green arrive with different prefixes (`tpep_*` / `lpep_*`); unifying on `tpep_*` would lie about half the fleet. The TLC view republishes source names **without duplicating** the table.

There is also a Streamlit app on Databricks (`apps/dq_dashboard/`) with scorecard, profiling, quarantine sample, Q1/Q2 answers, and the contract. UI notes in [`report.md`](report.md).

---

## How to run

**On Databricks Free Edition** (Community Edition is retired):

```bash
# 1) Upload yellow/green Jan–May to the landing Volume (once)
# 2) Sync code, deploy, and run the job
./scripts/deploy.sh
```

This materializes `raw` / `clean` / `consumption` / `governance` and the KPI tables.

Observability portal (optional for demos):

```bash
databricks apps deploy taxi-dq-observability
# Open under Compute → Apps → taxi-dq-observability
```

**Local** (contract + tests without the lake):

```bash
pip install -r requirements-dev.txt
python src/jobs/validate_contract.py
pytest tests/ -q
```

Full walkthrough (Volume, app grants): [Technical appendix](#technical-appendix).

---

## What I deliberately did not do

- **No Great Expectations / PyDeequ at runtime.** DQ requirements live in the data contract; row checks run via Soda Core, light on serverless.
- **Streamlit is icing**, not the core. Core is contract → quality gate → consumption → KPIs auditable by `run_id`.
- **FHV / FHVHV are out.** Product scope is taxi (yellow/green); mixing ride-hail fleets would muddy price and occupancy questions.
- **Quarantine is rewritten each clean run.** “Days isolated” measures age for that run, not an infinite incident history.

---

## Quick repository map

| If you want…                           | Open…                                                                                                                                        |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| Business questions                     | [`files/business_questions.md`](files/business_questions.md) · [`PT`](files/business_questions.pt.md)                                        |
| Policy (schema, rules, ownership)      | [`domains/mobility/taxi_trips/contract.yaml`](domains/mobility/taxi_trips/contract.yaml)                                                     |
| Executable checks                      | [`domains/mobility/taxi_trips/data_quality/checks.yml`](domains/mobility/taxi_trips/data_quality/checks.yml)                                 |
| Q1 / Q2 SQL                            | [`domains/mobility/taxi_trips/consumption/metrics/`](domains/mobility/taxi_trips/consumption/metrics/)                                       |
| View with original TLC names           | [`domains/mobility/taxi_trips/consumption/views/vw_taxi_trips_tlc.sql`](domains/mobility/taxi_trips/consumption/views/vw_taxi_trips_tlc.sql) |
| Verification notebook (read-only SQL)  | [`notebooks/verify_business_questions.py`](notebooks/verify_business_questions.py)                                                           |
| Pipeline jobs                          | [`src/jobs/`](src/jobs/)                                                                                                                     |
| DQ portal                              | [`apps/dq_dashboard/`](apps/dq_dashboard/) · [`report.md`](report.md)                                                                        |

---

## Technical appendix

### Layers and objects

| Layer       | Main object                                                 | How it is born               |
| ----------- | ----------------------------------------------------------- | ---------------------------- |
| raw         | `yellow_tripdata`, `green_tripdata`                         | PySpark (`ingest_raw`)       |
| clean       | `taxi_trips` + `taxi_trips_quarantine`                      | Canonical SQL + Soda gate    |
| consumption | `taxi_trips`, `vw_taxi_trips_tlc`, `kpi_*`                  | SQL models / metrics / views |
| governance  | `data_profile`, `dq_validation_result`, `fitness_*`, `vw_*` | profiling + SQL views        |

Each file under `*/models/*.sql` or `*/metrics/*.sql` **is** the object: the job only resolves `${catalog}` / `${run_id}` and materializes. Adding a KPI = adding a `.sql`.

### Spec by DQ dimensions

Source: [`contract.yaml`](domains/mobility/taxi_trips/contract.yaml).

| Rule                                | Dimension    | Severity | Effect           |
| ----------------------------------- | ------------ | -------- | ---------------- |
| `vendor_id` not null                | completeness | error    | Quarantine       |
| `total_amount` not null             | completeness | error    | Quarantine       |
| `pickup_datetime` not null          | completeness | error    | Quarantine       |
| `dropoff_datetime` not null         | completeness | error    | Quarantine       |
| `year_month` in Jan–May/2023 window | completeness | error    | Quarantine       |
| `dropoff` ≥ `pickup`                | consistency  | error    | Quarantine       |
| `taxi_type` ∈ {yellow, green}       | validity     | error    | Quarantine       |
| Aggregate coverage of 5 months      | completeness | error    | Fail the job     |
| `passenger_count` between 1 and 6   | validity     | warning  | Scorecard only   |
| `total_amount` ≥ 0                  | accuracy     | warning  | Scorecard only   |
| `vendor_id` ∈ {1, 2}                | validity     | warning  | Scorecard only   |
| Quarantine rate < 5%                | accuracy     | warning  | Scorecard only   |
| Approximate duplicate rate          | uniqueness   | warning  | Scorecard only   |
| Monthly volume vs median            | completeness | warning  | Scorecard only   |

### Metadata in Unity Catalog

After publish, contract descriptions and tags go to the metastore (Comments + Tags). Check Catalog Explorer on `workspace.consumption.taxi_trips`, or:

```sql
SELECT column_name, comment
FROM workspace.information_schema.columns
WHERE table_schema = 'consumption' AND table_name = 'taxi_trips';
```

### Orchestration

- Topology: [`orchestration/pipeline.yaml`](orchestration/pipeline.yaml)
- Databricks: [`databricks.yml`](databricks.yml) — job `taxi_data_product`

Flow: `ingest_raw` → `build_clean` → `publish_consumption` → `run_analysis`.

### Full local run

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

Default landing Volume: `/Volumes/workspace/default/taxi_landing`.

```bash
for f in files/{yellow,green}_tripdata_2023-0{1,2,3,4,5}.parquet; do
  databricks fs cp "$f" "dbfs:/Volumes/workspace/default/taxi_landing/$(basename "$f")" --overwrite
done

./scripts/deploy.sh
```

The script syncs `domains/`, `platform/`, and `src/` to the code Volume (serverless jobs read from there), deploys the bundle, and triggers the pipeline. Use `--no-run` to sync/deploy only.

Observability: Streamlit portal in [`apps/dq_dashboard/`](apps/dq_dashboard/) — see [`report.md`](report.md).

### Contract standard

We base the policy on the [Data Contract Specification 0.9.3](https://datacontract.com/).
