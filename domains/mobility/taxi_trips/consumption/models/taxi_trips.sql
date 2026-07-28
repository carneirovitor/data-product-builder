-- Consumer-facing table: the five CDEs the contract publishes, plus the taxi
-- type and the partition key. Nothing else is exposed, so the interface stays
-- stable while the clean layer is free to carry operational columns.
SELECT
  vendor_id,
  passenger_count,
  total_amount,
  pickup_datetime,
  dropoff_datetime,
  taxi_type,
  year_month
FROM ${catalog}.clean.taxi_trips
