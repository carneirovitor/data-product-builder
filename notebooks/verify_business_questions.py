# Databricks notebook source
# MAGIC %md
# MAGIC # Verify business questions + quality
# MAGIC
# MAGIC This notebook **reads** the governed data product. It does **not** recompute KPIs or re-run the quality gate.
# MAGIC
# MAGIC Source of truth:
# MAGIC - Pipeline job (`./scripts/deploy.sh` / `taxi_data_product`)
# MAGIC - Contract: `domains/mobility/taxi_trips/contract.yaml`
# MAGIC - KPI SQL: `domains/mobility/taxi_trips/consumption/metrics/`
# MAGIC
# MAGIC Prerequisite: at least one successful pipeline run so `consumption.*` and `governance.*` are populated.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
catalog = dbutils.widgets.get("catalog").strip() or "workspace"
spark.sql(f"USE CATALOG {catalog}")
print(f"Using catalog={catalog}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Latest run

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE TEMP VIEW _latest_run AS
# MAGIC SELECT run_id
# MAGIC FROM governance.dq_validation_result
# MAGIC GROUP BY run_id
# MAGIC ORDER BY MAX(captured_at) DESC
# MAGIC LIMIT 1;
# MAGIC
# MAGIC SELECT * FROM _latest_run;

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Layer counts (same run)

# COMMAND ----------

# MAGIC %sql
# MAGIC WITH r AS (SELECT run_id FROM _latest_run)
# MAGIC SELECT 'consumption.taxi_trips' AS object, COUNT(*) AS row_count
# MAGIC FROM consumption.taxi_trips
# MAGIC UNION ALL
# MAGIC SELECT 'clean.taxi_trips_quarantine', COUNT(*)
# MAGIC FROM clean.taxi_trips_quarantine q
# MAGIC CROSS JOIN r
# MAGIC WHERE q.dq_run_id = r.run_id
# MAGIC UNION ALL
# MAGIC SELECT 'consumption.kpi_yellow_avg_total_amount_monthly', COUNT(*)
# MAGIC FROM consumption.kpi_yellow_avg_total_amount_monthly k
# MAGIC CROSS JOIN r
# MAGIC WHERE k.run_id = r.run_id
# MAGIC UNION ALL
# MAGIC SELECT 'consumption.kpi_fleet_avg_passenger_count_hourly', COUNT(*)
# MAGIC FROM consumption.kpi_fleet_avg_passenger_count_hourly k
# MAGIC CROSS JOIN r
# MAGIC WHERE k.run_id = r.run_id;

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Q1 — average `total_amount` per month (yellow)
# MAGIC
# MAGIC Materialized answer (do not re-aggregate from raw here).

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT
# MAGIC   k.year_month,
# MAGIC   ROUND(k.avg_total_amount, 2) AS avg_total_amount,
# MAGIC   k.trip_count,
# MAGIC   k.run_id,
# MAGIC   k.computed_at
# MAGIC FROM consumption.kpi_yellow_avg_total_amount_monthly k
# MAGIC JOIN _latest_run r ON k.run_id = r.run_id
# MAGIC ORDER BY k.year_month;

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Q2 — average `passenger_count` by hour (May, full fleet)

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT
# MAGIC   k.pickup_hour,
# MAGIC   ROUND(k.avg_passenger_count, 4) AS avg_passenger_count,
# MAGIC   k.trip_count,
# MAGIC   k.null_passenger_count,
# MAGIC   ROUND(100.0 * k.null_passenger_count / NULLIF(k.trip_count, 0), 2) AS null_pct,
# MAGIC   k.run_id
# MAGIC FROM consumption.kpi_fleet_avg_passenger_count_hourly k
# MAGIC JOIN _latest_run r ON k.run_id = r.run_id
# MAGIC ORDER BY k.pickup_hour;

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. DQ scorecard (DAMA dimensions)

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT
# MAGIC   s.dimension,
# MAGIC   s.rules_evaluated,
# MAGIC   s.rules_passed,
# MAGIC   ROUND(s.pass_rate, 4) AS pass_rate,
# MAGIC   ROUND(s.quarantine_rate, 6) AS quarantine_rate,
# MAGIC   s.run_id
# MAGIC FROM governance.vw_dq_scorecard s
# MAGIC JOIN _latest_run r ON s.run_id = r.run_id
# MAGIC ORDER BY s.dimension;

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Failed / softed rules on the scorecard

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT
# MAGIC   d.dimension,
# MAGIC   d.rule,
# MAGIC   d.severity,
# MAGIC   d.passed,
# MAGIC   d.measured,
# MAGIC   d.threshold
# MAGIC FROM governance.dq_validation_result d
# MAGIC JOIN _latest_run r ON d.run_id = r.run_id
# MAGIC WHERE d.passed = false
# MAGIC ORDER BY CASE WHEN d.severity = 'error' THEN 0 ELSE 1 END, d.dimension, d.rule;

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Quarantine — rate and top rules

# COMMAND ----------

# MAGIC %sql
# MAGIC WITH r AS (SELECT run_id FROM _latest_run),
# MAGIC clean_n AS (
# MAGIC   SELECT COUNT(*) AS n FROM consumption.taxi_trips
# MAGIC ),
# MAGIC quar_n AS (
# MAGIC   SELECT COUNT(*) AS n
# MAGIC   FROM clean.taxi_trips_quarantine q
# MAGIC   CROSS JOIN r
# MAGIC   WHERE q.dq_run_id = r.run_id
# MAGIC )
# MAGIC SELECT
# MAGIC   clean_n.n AS consumption_rows,
# MAGIC   quar_n.n AS quarantine_rows,
# MAGIC   ROUND(100.0 * quar_n.n / NULLIF(clean_n.n + quar_n.n, 0), 4) AS quarantine_pct
# MAGIC FROM clean_n CROSS JOIN quar_n;

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT
# MAGIC   t.rule,
# MAGIC   t.incident_count,
# MAGIC   t.run_id
# MAGIC FROM governance.vw_incident_quarantine_top_rules t
# MAGIC JOIN _latest_run r ON t.run_id = r.run_id
# MAGIC ORDER BY t.incident_count DESC
# MAGIC LIMIT 20;

# COMMAND ----------

# MAGIC %md
# MAGIC ## 8. Quarantine sample (incident trail)

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT
# MAGIC   q.taxi_type,
# MAGIC   q.vendor_id,
# MAGIC   q.pickup_datetime,
# MAGIC   q.dropoff_datetime,
# MAGIC   q.passenger_count,
# MAGIC   q.total_amount,
# MAGIC   q.dq_failed_rules,
# MAGIC   q.dq_run_id
# MAGIC FROM clean.taxi_trips_quarantine q
# MAGIC JOIN _latest_run r ON q.dq_run_id = r.run_id
# MAGIC LIMIT 25;

# COMMAND ----------

# MAGIC %md
# MAGIC ## 9. Fitness for use (still answers Q1/Q2?)

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT
# MAGIC   f.use_case,
# MAGIC   f.rule,
# MAGIC   f.passed,
# MAGIC   f.measured,
# MAGIC   f.expected,
# MAGIC   f.run_id
# MAGIC FROM governance.vw_fitness_summary f
# MAGIC JOIN _latest_run r ON f.run_id = r.run_id
# MAGIC ORDER BY f.use_case, f.rule;

# COMMAND ----------

# MAGIC %md
# MAGIC ## 10. TLC consumer interface (contracted column names)

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT
# MAGIC   VendorID,
# MAGIC   passenger_count,
# MAGIC   total_amount,
# MAGIC   tpep_pickup_datetime,
# MAGIC   tpep_dropoff_datetime
# MAGIC FROM consumption.vw_taxi_trips_tlc
# MAGIC LIMIT 10;
