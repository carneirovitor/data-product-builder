-- Fitness for use: does the consumption layer still answer the business questions?
SELECT
  run_id,
  use_case,
  rule,
  passed,
  measured,
  expected,
  captured_at
FROM ${catalog}.governance.fitness_for_use_result
