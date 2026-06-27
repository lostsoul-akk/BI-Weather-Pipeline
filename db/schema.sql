-- db/schema.sql
-- Run once to initialize the eaweather database.
-- Usage: psql -U <user> -d eaweather -f db/schema.sql

-- ── Cities registry ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cities (
    city_id    SERIAL PRIMARY KEY,
    city_name  VARCHAR(100) NOT NULL,
    country    CHAR(2)      NOT NULL,
    latitude   FLOAT        NOT NULL,
    longitude  FLOAT        NOT NULL,
    UNIQUE (city_name, country)
);

-- Seed the target cities up front so FKs always resolve.
-- Original 4 kept first so existing city_id references are unaffected.
INSERT INTO cities (city_name, country, latitude, longitude) VALUES
    ('Nairobi',         'KE', -1.2864,  36.8172),
    ('Mombasa',         'KE', -4.0435,  39.6682),
    ('Kampala',         'UG',  0.3476,  32.5825),
    ('Dar es Salaam',   'TZ', -6.7924,  39.2083),
    ('Kisumu',          'KE', -0.0917,  34.7680),
    ('Dodoma',          'TZ', -6.1630,  35.7516),
    ('Arusha',          'TZ', -3.3869,  36.6830),
    ('Kigali',          'RW', -1.9441,  30.0619),
    ('Bujumbura',       'BI', -3.3614,  29.3599),
    ('Juba',            'SS',  4.8594,  31.5713),
    ('Addis Ababa',     'ET',  9.0301,  38.7400),
    ('Dire Dawa',       'ET',  9.5931,  41.8500),
    ('Mogadishu',       'SO',  2.0469,  45.3182),
    ('Djibouti City',   'DJ', 11.5886,  43.1456),
    ('Asmara',          'ER', 15.3229,  38.9251),
    ('Kinshasa',        'CD', -4.4419,  15.2663),
    ('Lubumbashi',      'CD', -11.6609, 27.4794),
    ('Goma',            'CD', -1.6792,  29.2228),
    ('Brazzaville',     'CG', -4.2634,  15.2429),
    ('Yaoundé',         'CM',  3.8480,  11.5021),
    ('Douala',          'CM',  4.0511,  9.7679),
    ('Bangui',          'CF',  4.3947,  18.5582),
    ('N''Djamena',      'TD', 12.1348,  15.0557),
    ('Libreville',      'GA',  0.4162,  9.4673),
    ('Malabo',          'GQ',  3.7523,  8.7741)
ON CONFLICT (city_name, country) DO NOTHING;

-- ── Hourly weather readings ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS weather_readings (
    reading_id          SERIAL PRIMARY KEY,
    city_id             INT REFERENCES cities(city_id) ON DELETE CASCADE,
    recorded_at         TIMESTAMPTZ  NOT NULL,
    temperature_c       FLOAT,
    feels_like_c        FLOAT,
    temp_min_c          FLOAT,
    temp_max_c          FLOAT,
    humidity_pct        FLOAT,
    pressure_hpa        FLOAT,
    wind_speed_ms       FLOAT,
    wind_deg            SMALLINT,
    cloudiness_pct      SMALLINT,
    visibility_m        INT,
    weather_main        VARCHAR(50),
    weather_description VARCHAR(200),
    validation_flag     TEXT DEFAULT '',
    UNIQUE (city_id, recorded_at)
);

CREATE INDEX IF NOT EXISTS idx_weather_city_time
    ON weather_readings (city_id, recorded_at DESC);

-- ── 3-hourly air quality readings ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS air_quality_readings (
    reading_id      SERIAL PRIMARY KEY,
    city_id         INT REFERENCES cities(city_id) ON DELETE CASCADE,
    recorded_at     TIMESTAMPTZ NOT NULL,
    aqi             SMALLINT,          -- OWM scale 1–5
    aqi_category    VARCHAR(20),       -- Good / Fair / Moderate / Poor / Very Poor
    co              FLOAT,             -- μg/m³
    no              FLOAT,
    no2             FLOAT,
    o3              FLOAT,
    so2             FLOAT,
    pm2_5           FLOAT,
    pm10            FLOAT,
    nh3             FLOAT,
    validation_flag TEXT DEFAULT '',
    UNIQUE (city_id, recorded_at)
);

CREATE INDEX IF NOT EXISTS idx_aqi_city_time
    ON air_quality_readings (city_id, recorded_at DESC);

-- ── Daily summaries (populated by Airflow daily DAG) ──────────────────────
CREATE TABLE IF NOT EXISTS daily_summaries (
    summary_id      SERIAL PRIMARY KEY,
    city_id         INT REFERENCES cities(city_id) ON DELETE CASCADE,
    summary_date    DATE NOT NULL,
    avg_temp_c      FLOAT,
    min_temp_c      FLOAT,
    max_temp_c      FLOAT,
    avg_humidity    FLOAT,
    avg_wind_ms     FLOAT,
    avg_aqi         FLOAT,
    max_aqi         SMALLINT,
    dominant_weather VARCHAR(50),
    UNIQUE (city_id, summary_date)
);

CREATE INDEX IF NOT EXISTS idx_summary_city_date
    ON daily_summaries (city_id, summary_date DESC);
