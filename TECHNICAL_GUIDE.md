# EAWeather BI Pipeline — Technical Guide

A deep-dive into how the pipeline works, how data flows through each layer,
SQL reference queries for inspecting the database, and a full testing guide.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Component Deep-Dive](#2-component-deep-dive)
3. [Data Flow — End to End](#3-data-flow--end-to-end)
4. [Infrastructure — Supabase + GitHub Actions](#4-infrastructure--supabase--github-actions)
5. [Database Reference](#5-database-reference)
6. [Testing Guide](#6-testing-guide)
7. [Common Issues & Fixes](#7-common-issues--fixes)

---

## 1. Architecture Overview

```
DATA SOURCES
  OpenWeatherMap /data/2.5/weather       (hourly observation)
  OpenWeatherMap /data/2.5/air_pollution (current AQI + pollutants)
        |                        |
        v                        v
COLLECTION LAYER
  collectors/weather.py      collectors/airquality.py
  - HTTP GET per city         - HTTP GET per city
  - Save raw JSON to          - Save raw JSON to
    data/raw/                   data/raw/
  - Return flat dicts         - Return flat dicts
        |
        v
CLEANING LAYER
  cleaning/clean_weather.py  cleaning/clean_airquality.py
  - Pandas DataFrame          - Pandas DataFrame
  - Drop nulls                - Drop nulls
  - Deduplicate               - Deduplicate
  - Validate bounds           - Map AQI 1-5 to category
  - Cast types                - Cast types
  - Save to data/processed/   - Save to data/processed/
        |
        v
DATABASE — Supabase (hosted PostgreSQL)
  Connection: Session mode pooler (IPv4)
  aws-0-eu-west-1.pooler.supabase.com:5432
  Tables: cities, weather_readings, air_quality_readings, daily_summaries
  Upsert: INSERT ... ON CONFLICT (city_id, recorded_at) DO NOTHING
        |
        v
ORCHESTRATION — GitHub Actions (cloud scheduler)
  .github/workflows/weather.yml        every hour
  .github/workflows/airquality.yml     every 3 hours + SMTP alert if AQI >= 4
  .github/workflows/daily_summary.yml  daily at 00:15 UTC
  Each run: fresh Ubuntu VM -> install deps -> run pipeline -> exit
  Secrets injected from GitHub repo Settings -> Secrets
        |
        v
ANALYSIS & VISUALIZATION
  notebooks/01_eda.ipynb       - Seaborn/Matplotlib EDA
  notebooks/02_dashboard.ipynb - Interactive Plotly charts
```

---

## 2. Component Deep-Dive

### 2.1 Collectors

**Files:** `collectors/config.py`, `collectors/weather.py`, `collectors/airquality.py`

Each collector:

1. Reads `OWM_API_KEY` from environment via `python-dotenv`
2. Iterates over the 4 cities defined in `config.py`
3. Makes one `GET` request per city with `lat`, `lon`, `units=metric`, `appid`
4. Saves the raw API response as JSON to `data/raw/` for audit and replay
5. Parses the response into a flat dict — no nested objects, only scalar values
6. Sleeps 1 second between city requests (free tier: 1,000 calls/day limit)

**Why save raw JSON?**
If a bug is found in cleaning logic later, raw files can be replayed without
making new API calls. Standard ETL practice.

**OWM response structure (weather, simplified):**
```json
{
  "dt": 1749370226,
  "main": { "temp": 18.93, "humidity": 72, "pressure": 1021 },
  "wind": { "speed": 1.5, "deg": 210 },
  "clouds": { "all": 75 },
  "weather": [{ "main": "Clouds", "description": "broken clouds" }],
  "visibility": 10000
}
```

`dt` is a Unix UTC timestamp converted on collection:
```python
datetime.fromtimestamp(raw["dt"], tz=timezone.utc).isoformat()
# "2026-06-09T08:26:30+00:00"
```

Both endpoints (weather + air quality) use one OWM API key.

---

### 2.2 Cleaning

**Files:** `cleaning/clean_weather.py`, `cleaning/clean_airquality.py`

Five steps per cleaner:

| Step | What it does |
|---|---|
| 1. Load | `pd.DataFrame(records)` |
| 2. Drop null keys | Drops rows where `city_name` or `recorded_at` is null |
| 3. Deduplicate | `drop_duplicates(subset=["city_name", "recorded_at"])` |
| 4. Validate bounds | Checks numeric fields; flags violations in `validation_flag` instead of dropping |
| 5. Cast types | `pd.to_datetime`, `pd.to_numeric`, `astype("Int64")` for integers |

**Why flag instead of drop out-of-range rows?**
Dropping silently loses data. The `validation_flag` column lets analysts
decide what to do — the pipeline never makes that call on their behalf.

**Air quality specific:** maps OWM AQI (1-5) to a human-readable category:
```python
{1: "Good", 2: "Fair", 3: "Moderate", 4: "Poor", 5: "Very Poor"}
```

---

### 2.3 Database Layer

**Files:** `db/schema.sql`, `db/models.py`, `db/ingest.py`

**Key design decisions:**

- `cities` is a static lookup table seeded once via `schema.sql`. All other
  tables reference it by `city_id` (integer FK). Faster JOINs, less storage.

- Unique constraint on `(city_id, recorded_at)` = idempotency guarantee.
  `ON CONFLICT DO NOTHING` means re-running the pipeline never duplicates data.

- `daily_summaries` is never written by collectors. Populated exclusively by
  `daily_summary.yml` via a SQL aggregate run once per day.

**DB connection — URL.create() for special character safety:**

Supabase passwords may contain `$`, `?`, `=`. These break raw URL strings.
`URL.create()` handles encoding automatically:

```python
from sqlalchemy.engine import URL

url = URL.create(
    drivername="postgresql+psycopg2",
    username=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),  # special chars handled safely
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT", 5432)),
    database=os.getenv("DB_NAME"),
)
```

---

### 2.4 Pipeline Runner

**File:** `pipeline/run_pipeline.py`

Chains the three layers: `collect_all() -> clean_*() -> ingest_*()`

CLI flags:

| Flag | Effect |
|---|---|
| `--type weather` | Weather only |
| `--type airquality` | Air quality only |
| `--type all` (default) | Both sequentially |
| `--city Nairobi` | One city only |

Logs to both `stdout` and `pipeline.log` simultaneously.

---

### 2.5 GitHub Actions Workflows

**Files:** `.github/workflows/weather.yml`, `airquality.yml`, `daily_summary.yml`

GitHub Actions replaces Apache Airflow as the scheduler. Each workflow run:

1. GitHub spins up a fresh Ubuntu VM
2. Checks out the repo code
3. Installs minimal Python packages (no Airflow)
4. Runs the pipeline with secrets injected as environment variables
5. VM is discarded — data persists in Supabase

**Schedules:**

| Workflow | Cron | Runs |
|---|---|---|
| `weather.yml` | `0 * * * *` | Every hour on the hour |
| `airquality.yml` | `0 */3 * * *` | Every 3 hours (00:00, 03:00, 06:00...) |
| `daily_summary.yml` | `15 0 * * *` | Daily at 00:15 UTC |

All workflows have `workflow_dispatch` — trigger manually from the Actions tab
without waiting for the schedule.

**AQI alert in `airquality.yml`:**
After ingesting AQI data, an inline Python step queries Supabase for any city
with `AQI >= 4` in the last 4 hours and sends an SMTP email if found.

**Dependencies installed in CI:**
```
requests, pandas, numpy, sqlalchemy, psycopg2-binary, python-dotenv
```
`apache-airflow` is intentionally excluded — GitHub Actions IS the scheduler.

---

### 2.6 ML Model

**File:** `ml/aqi_model.py`

Trains a `RandomForestRegressor` to predict AQI from weather variables.

- **Features:** `temperature_c`, `humidity_pct`, `wind_speed_ms`, `pressure_hpa`
- **Target:** `aqi` (continuous 1-5)
- **Output:** `model.pkl` (model + scaler bundled) + `model_metrics.json`

Run after accumulating a few days of data:
```bash
python -m ml.aqi_model           # train + save
python -m ml.aqi_model --predict # load saved model, predict per city
```

---

## 3. Data Flow — End to End

### Local run

```
Step 1 - collectors/weather.py
  HTTP GET x 4 cities
  -> data/raw/weather_nairobi_20260609T082630Z.json  (+ 3 more)
  -> returns list of 4 flat dicts

Step 2 - cleaning/clean_weather.py
  4 dicts -> DataFrame: 4 rows x 17 columns
  validation passes -> validation_flag = "" for all rows
  -> data/processed/weather_clean_20260609T082639Z.csv

Step 3 - db/ingest.py ingest_weather()
  city_id lookup per city (cached after first call)
  INSERT ... ON CONFLICT DO NOTHING x 4
  -> Supabase: weather_readings (4 new rows)

Steps 4-6 - same flow for air quality
  -> data/raw/airquality_*.json (x 4 cities)
  -> data/processed/airquality_clean_*.csv
  -> Supabase: air_quality_readings (4 new rows)
```

### Automated run (GitHub Actions)

```
GitHub cron trigger
  -> Ubuntu VM starts
  -> repo checked out
  -> pip install (~25s, cached after first run)
  -> python -m pipeline.run_pipeline --type weather
       same collect -> clean -> ingest flow as local
       data written to Supabase
  -> VM discarded
  Total: ~50 seconds per workflow run
```

### Daily summary (00:15 UTC)

```
daily_summary.yml triggers
  -> SQL aggregate over weather_readings + air_quality_readings
     for yesterday's date
  -> INSERT ... ON CONFLICT DO UPDATE into daily_summaries
  -> 4 rows (one per city) added or updated
```

---

## 4. Infrastructure — Supabase + GitHub Actions

### Supabase

**Project ref:** `cwqkiynpseijbejlsvvm` (West EU / Ireland, eu-west-1)

**Why Supabase?**
Free hosted PostgreSQL with persistent storage, web-based SQL Editor,
and a Table Editor for visual data inspection. No server to manage.

**Connection — Session Mode Pooler (IPv4):**

Supabase free tier direct connections (`db.[ref].supabase.co`) are IPv6-only.
Networks without IPv6 routing get "Network is unreachable" errors.
Solution: use the session mode pooler (IPv4):

```
Host:     aws-0-eu-west-1.pooler.supabase.com
Port:     5432
User:     postgres.cwqkiynpseijbejlsvvm
Database: postgres
```

**Schema applied via Supabase SQL Editor** (browser-based) to bypass the
IPv6 restriction. Paste `db/schema.sql` contents and click Run.

**.env configuration:**
```env
DB_HOST=aws-0-eu-west-1.pooler.supabase.com
DB_PORT=5432
DB_NAME=postgres
DB_USER=postgres.cwqkiynpseijbejlsvvm
DB_PASSWORD=your_supabase_password
```

**Verifying data in Supabase:**
- Dashboard -> Table Editor -> select table
- Or use SQL Editor with queries from Section 5

---

### GitHub Actions

**Repo:** `github.com/lostsoul-akk/eaweather-bi-pipeline`

**Workflows:** `.github/workflows/`

**Secrets configured** (Settings -> Secrets and variables -> Actions):

| Secret | Purpose |
|---|---|
| `OWM_API_KEY` | OpenWeatherMap API key |
| `DB_HOST` | Supabase pooler hostname |
| `DB_PORT` | 5432 |
| `DB_NAME` | postgres |
| `DB_USER` | postgres.[project-ref] |
| `DB_PASSWORD` | Supabase database password |
| `SMTP_HOST` | smtp.gmail.com |
| `SMTP_PORT` | 587 |
| `SMTP_USER` | Gmail address |
| `SMTP_PASSWORD` | Gmail App Password (16-char code) |
| `ALERT_EMAIL` | Recipient for AQI alerts |

**Triggering a manual run:**
1. Repo -> Actions tab
2. Select a workflow
3. Click Run workflow -> Run workflow
4. Click the job -> expand each step for live logs

**Viewing run history:**
Actions tab -> select workflow -> each row is one run (green = success, red = failure)

---

## 5. Database Reference

### 5.1 Schema

```
cities
  city_id    SERIAL PK
  city_name  VARCHAR(100)
  country    CHAR(2)
  latitude   FLOAT
  longitude  FLOAT

weather_readings
  reading_id          SERIAL PK
  city_id             INT FK -> cities
  recorded_at         TIMESTAMPTZ    <- OWM observation timestamp (UTC)
  temperature_c       FLOAT
  feels_like_c        FLOAT
  temp_min_c          FLOAT
  temp_max_c          FLOAT
  humidity_pct        FLOAT
  pressure_hpa        FLOAT
  wind_speed_ms       FLOAT
  wind_deg            SMALLINT
  cloudiness_pct      SMALLINT
  visibility_m        INT
  weather_main        VARCHAR(50)
  weather_description VARCHAR(200)
  validation_flag     TEXT
  UNIQUE (city_id, recorded_at)

air_quality_readings
  reading_id      SERIAL PK
  city_id         INT FK -> cities
  recorded_at     TIMESTAMPTZ
  aqi             SMALLINT       <- 1=Good 2=Fair 3=Moderate 4=Poor 5=Very Poor
  aqi_category    VARCHAR(20)
  co, no, no2, o3, so2, pm2_5, pm10, nh3  FLOAT  <- ug/m3
  validation_flag TEXT
  UNIQUE (city_id, recorded_at)

daily_summaries
  summary_id       SERIAL PK
  city_id          INT FK -> cities
  summary_date     DATE
  avg_temp_c, min_temp_c, max_temp_c  FLOAT
  avg_humidity     FLOAT
  avg_wind_ms      FLOAT
  avg_aqi          FLOAT
  max_aqi          SMALLINT
  dominant_weather VARCHAR(50)
  UNIQUE (city_id, summary_date)
```

---

### 5.2 SQL Inspection Queries

Run in Supabase SQL Editor or via psql with the pooler URL.

**Row counts:**
```sql
SELECT
  (SELECT COUNT(*) FROM cities)               AS cities,
  (SELECT COUNT(*) FROM weather_readings)     AS weather_readings,
  (SELECT COUNT(*) FROM air_quality_readings) AS air_quality_readings,
  (SELECT COUNT(*) FROM daily_summaries)      AS daily_summaries;
```

**Latest weather per city:**
```sql
SELECT DISTINCT ON (city_id)
  c.city_name, w.recorded_at, w.temperature_c,
  w.humidity_pct, w.wind_speed_ms, w.weather_description
FROM weather_readings w
JOIN cities c USING (city_id)
ORDER BY city_id, w.recorded_at DESC;
```

**Latest AQI per city:**
```sql
SELECT DISTINCT ON (city_id)
  c.city_name, a.recorded_at, a.aqi, a.aqi_category, a.pm2_5, a.pm10
FROM air_quality_readings a
JOIN cities c USING (city_id)
ORDER BY city_id, a.recorded_at DESC;
```

**Total readings per city:**
```sql
SELECT
  c.city_name,
  COUNT(w.reading_id) AS weather_rows,
  COUNT(a.reading_id) AS aqi_rows
FROM cities c
LEFT JOIN weather_readings     w ON w.city_id = c.city_id
LEFT JOIN air_quality_readings a ON a.city_id = c.city_id
GROUP BY c.city_name
ORDER BY c.city_name;
```

**Temperature stats per city:**
```sql
SELECT
  c.city_name,
  ROUND(AVG(w.temperature_c)::numeric, 2)    AS avg_temp,
  ROUND(MIN(w.temperature_c)::numeric, 2)    AS min_temp,
  ROUND(MAX(w.temperature_c)::numeric, 2)    AS max_temp,
  ROUND(STDDEV(w.temperature_c)::numeric, 3) AS stddev_temp
FROM weather_readings w
JOIN cities c USING (city_id)
GROUP BY c.city_name
ORDER BY avg_temp DESC;
```

**AQI stats per city:**
```sql
SELECT
  c.city_name,
  ROUND(AVG(a.aqi)::numeric, 2)   AS avg_aqi,
  MAX(a.aqi)                       AS max_aqi,
  ROUND(AVG(a.pm2_5)::numeric, 2) AS avg_pm25,
  ROUND(AVG(a.pm10)::numeric,  2) AS avg_pm10
FROM air_quality_readings a
JOIN cities c USING (city_id)
GROUP BY c.city_name
ORDER BY avg_aqi DESC;
```

**Last 24 hours of readings:**
```sql
SELECT c.city_name, w.recorded_at, w.temperature_c, w.humidity_pct
FROM weather_readings w
JOIN cities c USING (city_id)
WHERE w.recorded_at >= NOW() - INTERVAL '24 hours'
ORDER BY w.recorded_at DESC;
```

**Flagged (out-of-range) rows:**
```sql
SELECT c.city_name, w.recorded_at, w.temperature_c, w.validation_flag
FROM weather_readings w
JOIN cities c USING (city_id)
WHERE w.validation_flag != ''
ORDER BY w.recorded_at DESC;

SELECT c.city_name, a.recorded_at, a.aqi, a.validation_flag
FROM air_quality_readings a
JOIN cities c USING (city_id)
WHERE a.validation_flag != ''
ORDER BY a.recorded_at DESC;
```

**Data freshness check:**
```sql
SELECT
  c.city_name,
  MAX(w.recorded_at)                 AS latest_obs,
  NOW() - MAX(w.recorded_at)         AS age,
  CASE
    WHEN NOW() - MAX(w.recorded_at) > INTERVAL '2 hours'
    THEN 'STALE' ELSE 'OK'
  END AS status
FROM weather_readings w
JOIN cities c USING (city_id)
GROUP BY c.city_name;
```

**Gap detection — hours with zero readings:**
```sql
SELECT
  c.city_name,
  gs.hour_slot,
  COUNT(w.reading_id) AS readings_in_hour
FROM cities c
CROSS JOIN generate_series(
  DATE_TRUNC('hour', NOW() - INTERVAL '24 hours'),
  DATE_TRUNC('hour', NOW()),
  INTERVAL '1 hour'
) AS gs(hour_slot)
LEFT JOIN weather_readings w
  ON  w.city_id = c.city_id
  AND DATE_TRUNC('hour', w.recorded_at) = gs.hour_slot
GROUP BY c.city_name, gs.hour_slot
HAVING COUNT(w.reading_id) = 0
ORDER BY gs.hour_slot;
```
Zero rows = no gaps. Any rows returned = missed GitHub Actions runs.

**Daily summaries:**
```sql
SELECT
  c.city_name, s.summary_date, s.avg_temp_c,
  s.avg_aqi, s.max_aqi, s.dominant_weather
FROM daily_summaries s
JOIN cities c USING (city_id)
ORDER BY s.summary_date DESC, c.city_name;
```

---

## 6. Testing Guide

### 6.1 Local Component Tests

Always activate venv first: `source venv/bin/activate`

**One-city weather collect:**
```bash
python - << 'EOF'
from collectors.weather import fetch_weather
import os; from dotenv import load_dotenv; load_dotenv()
city = {"name": "Nairobi", "country": "KE", "lat": -1.2864, "lon": 36.8172}
import pprint; pprint.pprint(fetch_weather(city, os.getenv("OWM_API_KEY")))
EOF
```

**Cleaning without API call:**
```bash
python - << 'EOF'
from cleaning.clean_weather import clean_weather
mock = [{"city_name": "Nairobi", "country": "KE", "lat": -1.2864, "lon": 36.8172,
         "recorded_at": "2026-06-09T08:00:00+00:00", "temperature_c": 20.1,
         "feels_like_c": 19.8, "temp_min_c": 18.0, "temp_max_c": 22.0,
         "humidity_pct": 64, "pressure_hpa": 1018, "wind_speed_ms": 2.3,
         "wind_deg": 180, "cloudiness_pct": 60, "visibility_m": 10000,
         "weather_main": "Clouds", "weather_description": "broken clouds"}]
df = clean_weather(mock)
print(df[["city_name", "temperature_c", "validation_flag"]])
EOF
```

**Supabase connection:**
```bash
python - << 'EOF'
from db.ingest import get_engine
from sqlalchemy import text
engine = get_engine()
with engine.connect() as conn:
    for row in conn.execute(text("SELECT city_id, city_name FROM cities ORDER BY city_id;")):
        print(row)
EOF
```

**Full pipeline:**
```bash
python -m pipeline.run_pipeline
```

**Confirmed working output (2026-06-09):**
```
weather      collected=4  inserted=4  time=19.91s
airquality   collected=4  inserted=4  time=14.36s
```

---

### 6.2 GitHub Actions Tests

**Trigger manual run:**
Repo -> Actions tab -> select workflow -> Run workflow -> Run workflow

**Verify data in Supabase after run:**
```sql
SELECT c.city_name, w.recorded_at, w.temperature_c
FROM weather_readings w
JOIN cities c USING (city_id)
ORDER BY w.recorded_at DESC
LIMIT 8;
```
Timestamps should match the workflow run time.

---

### 6.3 Data Quality Checks

**All cities have data:**
```sql
SELECT c.city_name,
  COUNT(w.reading_id) AS weather_rows,
  COUNT(a.reading_id) AS aqi_rows
FROM cities c
LEFT JOIN weather_readings     w ON w.city_id = c.city_id
LEFT JOIN air_quality_readings a ON a.city_id = c.city_id
GROUP BY c.city_name;
```

**No validation flags:**
```sql
SELECT COUNT(*) AS flagged_weather FROM weather_readings WHERE validation_flag != '';
SELECT COUNT(*) AS flagged_aqi     FROM air_quality_readings WHERE validation_flag != '';
```

---

## 7. Common Issues & Fixes

| Symptom | Cause | Fix |
|---|---|---|
| `Network is unreachable` on Supabase | Direct connection is IPv6-only | Use pooler: `aws-0-eu-west-1.pooler.supabase.com:5432`; apply schema via SQL Editor |
| `could not translate host name` | Wrong pooler hostname | Confirm region matches your project (eu-west-1 for Ireland) |
| Password with special chars breaks connection | `$`, `?`, `=` are URL special characters | Use `URL.create()` in `db/ingest.py` — already fixed |
| `401 Unauthorized` from OWM | Key wrong or not yet active | Wait 10 min after registration; check `.env` |
| `inserted=0` for all cities | Observations already in DB | Normal — OWM timestamps not yet updated; re-run next hour |
| `column "city_name" does not exist` | Querying table without JOIN | Always `JOIN cities c USING (city_id)` |
| `EnvironmentError: OWM_API_KEY not set` | venv not active or .env missing | `source venv/bin/activate`; confirm `.env` in project root |
| Commit message with `*` or `"` breaks git | Shell interprets as glob/syntax | Use single quotes: `git commit -m 'message'` |
| GitHub Actions schedule delayed | Free tier cron is best-effort | Use Run workflow button to trigger manually |

---

## 7. Production Setup — Supabase + GitHub Actions

This section documents the full production configuration: a hosted PostgreSQL
database on Supabase and automated pipeline runs via GitHub Actions.

---

### 7.1 Architecture in Production

```
LOCAL MACHINE (development only)
  python -m pipeline.run_pipeline   <- manual runs, testing
  notebooks/                        <- EDA and dashboards
  ml/aqi_model.py                   <- model training

        |
        | git push
        v

GITHUB REPOSITORY (lostsoul-akk/eaweather-bi-pipeline)
  |
  |-- .github/workflows/weather.yml        <- triggers hourly
  |-- .github/workflows/airquality.yml     <- triggers every 3h
  `-- .github/workflows/daily_summary.yml  <- triggers daily 00:15 UTC
        |
        | GitHub spins up Ubuntu VM
        | installs Python + deps
        | runs pipeline
        v

SUPABASE (hosted PostgreSQL — eu-west-1, Ireland)
  cities               <- 4 rows, static
  weather_readings     <- +4 rows every hour
  air_quality_readings <- +4 rows every 3 hours
  daily_summaries      <- +4 rows every day at 00:15 UTC
```

---

### 7.2 Supabase Configuration

**Project:** ngugimartin995-tech's Project
**Region:** West EU (Ireland) — eu-west-1
**Plan:** Free tier (Nano compute)

**Connection pooler (IPv4 — required for free tier):**

Supabase free tier's direct connection (`db.[ref].supabase.co:5432`) resolves
to an IPv6 address. If the host network does not route IPv6, the connection
fails with `Network is unreachable`. The connection pooler uses IPv4 and
works on all networks.

```env
DB_HOST=aws-0-eu-west-1.pooler.supabase.com
DB_PORT=5432
DB_NAME=postgres
DB_USER=postgres.cwqkiynpseijbejlsvvm
DB_PASSWORD=your_supabase_password
```

Note the `DB_USER` format — it is `postgres.[project-ref]`, not just
`postgres`. The project ref identifies your project through the shared pooler.

**Schema applied via SQL Editor:**
Because the direct connection is IPv6-only and the local network does not
support IPv6, the schema was applied through the Supabase dashboard:
Dashboard → SQL Editor → paste `db/schema.sql` → Run.

**Why URL.create() in db/ingest.py:**
The Supabase password contains special characters (`$`, `?`, `=`). When
embedded directly in a URL string, these are misinterpreted as URL syntax:
```python
# WRONG — $ and ? break URL parsing
url = f"postgresql+psycopg2://user:{password}@host:5432/db"

# CORRECT — SQLAlchemy URL.create() handles encoding internally
url = URL.create(
    drivername="postgresql+psycopg2",
    username=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),   # special chars safe here
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT", 5432)),
    database=os.getenv("DB_NAME"),
)
```

---

### 7.3 GitHub Actions — How It Works

GitHub Actions is a cloud CI/CD platform built into GitHub. It runs scripts
automatically in response to events or on a cron schedule.

Each workflow file defines:
- **WHEN** to run (`on: schedule` with cron expression)
- **WHERE** to run (`runs-on: ubuntu-latest` — GitHub provides the VM free)
- **WHAT** to run (steps: checkout → setup Python → install deps → run pipeline)

The VM is ephemeral — it is created fresh for each run and discarded
afterwards. Data persists because it is written to Supabase, not the VM.

**Three workflows:**

| File | Schedule | Cron | Purpose |
|---|---|---|---|
| `weather.yml` | Every hour | `0 * * * *` | Collect → clean → ingest weather |
| `airquality.yml` | Every 3 hours | `0 */3 * * *` | Collect → clean → ingest AQI + alert |
| `daily_summary.yml` | Daily 00:15 UTC | `15 0 * * *` | SQL aggregate into daily_summaries |

**Why not Airflow in production?**
Apache Airflow requires a persistent server to run the scheduler process.
GitHub Actions provides that scheduling for free, without any server to
maintain. The DAG logic is replaced by three YAML files.

The Airflow DAG files remain in `airflow/dags/` and are fully functional for
anyone who wants to self-host with Airflow. GitHub Actions is the production
scheduler for this deployment.

**Manual trigger:**
All three workflows include `workflow_dispatch:` which adds a "Run workflow"
button in the GitHub Actions UI. Use this to test a workflow immediately
without waiting for the scheduled time.

**Viewing logs:**
GitHub repo → Actions tab → click the workflow name → click the most recent
run → click the job name → expand any step to see its full output.

---

### 7.4 GitHub Secrets

All credentials are stored as encrypted GitHub Secrets, never in the
repository code. Set at: repo → Settings → Secrets and variables → Actions.

| Secret | Purpose |
|---|---|
| `OWM_API_KEY` | OpenWeatherMap API authentication |
| `DB_HOST` | Supabase pooler hostname |
| `DB_PORT` | Database port (5432) |
| `DB_NAME` | Database name (postgres) |
| `DB_USER` | Pooler user (postgres.[project-ref]) |
| `DB_PASSWORD` | Supabase database password |
| `SMTP_HOST` | Gmail SMTP server |
| `SMTP_PORT` | SMTP port (587) |
| `SMTP_USER` | Gmail address for sending alerts |
| `SMTP_PASSWORD` | Gmail App Password (16-char code, not login password) |
| `ALERT_EMAIL` | Recipient address for AQI alerts |

Secrets are injected into the workflow as environment variables:
```yaml
env:
  OWM_API_KEY: ${{ secrets.OWM_API_KEY }}
  DB_PASSWORD: ${{ secrets.DB_PASSWORD }}
```
They never appear in logs — GitHub masks them automatically.

---

### 7.5 Data Collection Schedule (Production)

With all three workflows running:

| Table | Rows added per day per city | Rows per day (4 cities) |
|---|---|---|
| `weather_readings` | 24 | 96 |
| `air_quality_readings` | 8 | 32 |
| `daily_summaries` | 1 | 4 |

After one week of running: ~672 weather rows, ~224 AQI rows.
After two weeks: ~1,344 weather rows, ~448 AQI rows.
This is sufficient data for meaningful EDA and ML training.

---

### 7.6 Verifying Production Runs

**Check GitHub Actions ran successfully:**
Go to repo → Actions tab. Each workflow shows green (success) or red (failed)
for every run. Click any run to see the full log including how many rows were
inserted.

**Check data is arriving in Supabase:**
Dashboard → Table Editor → `weather_readings` → sort by `recorded_at` DESC.
New rows should appear every hour from GitHub Actions.

**SQL check — confirm latest timestamps are recent:**
Run in Supabase SQL Editor:
```sql
SELECT
  c.city_name,
  MAX(w.recorded_at)              AS latest_weather,
  MAX(a.recorded_at)              AS latest_aqi,
  NOW() - MAX(w.recorded_at)      AS weather_age
FROM cities c
LEFT JOIN weather_readings     w ON w.city_id = c.city_id
LEFT JOIN air_quality_readings a ON a.city_id = c.city_id
GROUP BY c.city_name
ORDER BY c.city_name;
```
`weather_age` should be under 1 hour for all cities if the pipeline is healthy.

**SQL check — total rows accumulated:**
```sql
SELECT
  (SELECT COUNT(*) FROM weather_readings)     AS weather_rows,
  (SELECT COUNT(*) FROM air_quality_readings) AS aqi_rows,
  (SELECT COUNT(*) FROM daily_summaries)      AS summary_rows;
```

---

### 7.7 Commit History Reference

| Commit | Description |
|---|---|
| Initial scaffolding | Project structure, .env.example, .gitignore, requirements.txt |
| `feat(collectors)` | weather.py, airquality.py, config.py |
| `feat(cleaning)` | clean_weather.py, clean_airquality.py |
| `feat(db)` | schema.sql, models.py, ingest.py |
| `feat(pipeline)` | run_pipeline.py with --type and --city flags |
| `feat(airflow)` | weather_dag, airquality_dag, daily_summary_dag |
| `feat(notebooks)` | 01_eda.ipynb, 02_dashboard.ipynb |
| `feat(bonus)` | ML model, Dockerfile, docker-compose |
| `feat(ci)` | GitHub Actions workflows, Supabase pooler config |
| `fix(db)` | URL.create() for special characters in DB password |

