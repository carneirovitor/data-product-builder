-- Q1: average total_amount per month, yellow taxis only.
-- Reads the consumption layer, so every row already cleared the hard gate.
-- total_amount_non_negative is a soft rule: TLC refunds and adjustments stay in,
-- because dropping them would bias the average this metric exists to report.
SELECT
  year_month,
  AVG(total_amount) AS avg_total_amount,
  COUNT(*) AS trip_count,
  '${run_id}' AS run_id,
  current_timestamp() AS computed_at
FROM ${catalog}.consumption.taxi_trips
WHERE taxi_type = 'yellow'
GROUP BY year_month
