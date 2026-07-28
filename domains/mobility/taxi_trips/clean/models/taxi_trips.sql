-- Canonical trip record: yellow and green harmonized into one shape.
-- The source prefixes name the vendor programme, not the fleet — yellow ships
-- tpep_*, green ships lpep_* — so both collapse to pickup_datetime /
-- dropoff_datetime, and VendorID takes the platform's snake_case.
-- This model is not materialized directly: build_clean feeds it to the Soda gate,
-- which splits it into clean.taxi_trips and clean.taxi_trips_quarantine.
SELECT
  vendor_id,
  passenger_count,
  total_amount,
  pickup_datetime,
  dropoff_datetime,
  source_file,
  ingest_ts,
  taxi_type,
  DATE_FORMAT(pickup_datetime, 'yyyy-MM') AS year_month
FROM (
  SELECT
    VendorID AS vendor_id,
    passenger_count,
    total_amount,
    tpep_pickup_datetime AS pickup_datetime,
    tpep_dropoff_datetime AS dropoff_datetime,
    source_file,
    ingest_ts,
    'yellow' AS taxi_type
  FROM ${catalog}.raw.yellow_tripdata

  UNION ALL

  SELECT
    VendorID AS vendor_id,
    passenger_count,
    total_amount,
    lpep_pickup_datetime AS pickup_datetime,
    lpep_dropoff_datetime AS dropoff_datetime,
    source_file,
    ingest_ts,
    'green' AS taxi_type
  FROM ${catalog}.raw.green_tripdata
)
