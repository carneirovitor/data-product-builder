# Data product — NYC taxi trips

**Language:** **English** · [Português](business_questions.pt.md)

## Goal

Ingest New York City taxi trip records into a data lake, make them available for analytical consumption, and answer business questions about fleet pricing and occupancy — with auditable quality and governance.

Product scope:

- Ingest TLC files (yellow and green) into the lake
- A queryable consumption layer (SQL)
- Two business analyses materialized as KPIs

---

## Data

Source: [NYC TLC Trip Record Data](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page).

Window: **January–May 2023** (yellow + green). Supporting dictionaries and metadata live under `files/`.

---

## Modeling notes

- Landing for original files (Volume / object store)
- Structured consumption layer for end users
- Cleaning and quality rules per domain policy
- Consumption must expose at least: **VendorID**, **passenger_count**, **total_amount**, **tpep_pickup_datetime**, **tpep_dropoff_datetime**
- Other columns are optional; the lake starts with no pre-existing tables

---

## Business questions

1. What is the average total amount (`total_amount`) received in a month across all yellow taxis in the fleet?
2. What is the average passenger count (`passenger_count`) for each hour of day in May across all taxis in the fleet?

Materialized answers: `consumption.kpi_*` (see README).
