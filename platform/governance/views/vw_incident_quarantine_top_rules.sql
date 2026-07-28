-- Incident triage: which rules sent rows to quarantine, and how many.
-- dq_failed_rules is a comma-separated trail, so one row can feed several rules.
SELECT
  dq_run_id AS run_id,
  TRIM(rule) AS rule,
  COUNT(*) AS incident_count
FROM ${catalog}.clean.taxi_trips_quarantine
LATERAL VIEW EXPLODE(SPLIT(dq_failed_rules, ',')) t AS rule
WHERE dq_failed_rules IS NOT NULL AND TRIM(rule) <> ''
GROUP BY dq_run_id, TRIM(rule)
