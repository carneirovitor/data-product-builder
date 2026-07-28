-- Reliability scorecard: pass rate per DAMA dimension for each run.
SELECT
  run_id,
  dimension,
  COUNT(*) AS rules_evaluated,
  SUM(CASE WHEN passed THEN 1 ELSE 0 END) AS rules_passed,
  AVG(CASE WHEN passed THEN 1.0 ELSE 0.0 END) AS pass_rate,
  MAX(CASE WHEN rule = 'hard_quarantine_rate' THEN measured END) AS quarantine_rate,
  MAX(CASE WHEN rule = 'uniqueness_rate' THEN measured END) AS uniqueness_metric
FROM ${catalog}.governance.dq_validation_result
GROUP BY run_id, dimension
