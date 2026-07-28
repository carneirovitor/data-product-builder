-- Q2: average passenger_count per pickup hour for the whole fleet
-- (yellow + green) in May 2023.
-- passenger_count is a soft rule, so out-of-range and null values are kept;
-- AVG ignores nulls, and null_passenger_count exposes how much it ignored.
SELECT
  HOUR(pickup_datetime) AS pickup_hour,
  AVG(passenger_count) AS avg_passenger_count,
  COUNT(*) AS trip_count,
  SUM(CASE WHEN passenger_count IS NULL THEN 1 ELSE 0 END) AS null_passenger_count,
  '${run_id}' AS run_id,
  current_timestamp() AS computed_at
FROM ${catalog}.consumption.taxi_trips
WHERE year_month = '2023-05'
GROUP BY HOUR(pickup_datetime)
