-- Profiling of the most recent run, per layer / table / column.
-- Ordered by captured_at rather than MAX(run_id): run_id is an opaque
-- identifier and must not carry ordering semantics.
SELECT
  p.run_id,
  p.layer,
  p.table_name,
  p.column_name,
  p.metric,
  p.metric_value,
  p.partition_key,
  p.captured_at
FROM ${catalog}.governance.data_profile AS p
WHERE p.run_id = (
  SELECT run_id
  FROM ${catalog}.governance.data_profile
  ORDER BY captured_at DESC
  LIMIT 1
)
