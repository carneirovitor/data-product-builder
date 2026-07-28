-- Compatibility interface under the original TLC column names.
-- Consumers expect VendorID, passenger_count, total_amount, tpep_pickup_datetime
-- and tpep_dropoff_datetime in the consumption layer. The physical table follows
-- platform snake_case, so this view carries the contracted names for consumers
-- pinned to them — one interface, two vocabularies, no second copy of the data.
SELECT
  vendor_id AS VendorID,
  passenger_count,
  total_amount,
  pickup_datetime AS tpep_pickup_datetime,
  dropoff_datetime AS tpep_dropoff_datetime,
  taxi_type,
  year_month
FROM ${catalog}.consumption.taxi_trips
