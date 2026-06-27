"""
db/ingest.py
Database connection factory and upsert functions for all three tables.

Uses INSERT ... ON CONFLICT DO NOTHING so re-runs are always safe.
"""

import logging
import os

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker, Session

from db.models import Base, City, WeatherReading, AirQualityReading

load_dotenv()
log = logging.getLogger("db.ingest")


# ── Engine ─────────────────────────────────────────────────────────────────

def get_engine():
    """
    Build a SQLAlchemy engine from environment variables.
    Uses URL.create() instead of a raw URL string so that special characters
    in the password ($ ? = etc.) are handled safely without manual encoding.
    """
    url = URL.create(
        drivername="postgresql+psycopg2",
        username=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        database=os.getenv("DB_NAME", "eaweather"),
    )
    return create_engine(url, pool_pre_ping=True)


def get_session(engine=None) -> Session:
    engine = engine or get_engine()
    return sessionmaker(bind=engine)()


# ── City lookup cache ──────────────────────────────────────────────────────

_city_cache: dict[str, int] = {}

def _get_city_id(session: Session, city_name: str) -> int | None:
    """Return city_id for a given city_name, using a local cache."""
    if city_name not in _city_cache:
        row = session.query(City).filter_by(city_name=city_name).first()
        if row is None:
            log.error("City not found in DB: %s — run schema.sql first.", city_name)
            return None
        _city_cache[city_name] = row.city_id
    return _city_cache[city_name]


# ── Upsert: weather ────────────────────────────────────────────────────────

def ingest_weather(df: pd.DataFrame, session: Session | None = None) -> int:
    """
    Upsert cleaned weather DataFrame into weather_readings.
    Returns the number of rows inserted.
    """
    session = session or get_session()
    inserted = 0

    try:
        for _, row in df.iterrows():
            city_id = _get_city_id(session, row["city_name"])
            if city_id is None:
                continue

            stmt = text("""
                INSERT INTO weather_readings (
                    city_id, recorded_at,
                    temperature_c, feels_like_c, temp_min_c, temp_max_c,
                    humidity_pct, pressure_hpa, wind_speed_ms, wind_deg,
                    cloudiness_pct, visibility_m,
                    weather_main, weather_description, validation_flag
                ) VALUES (
                    :city_id, :recorded_at,
                    :temperature_c, :feels_like_c, :temp_min_c, :temp_max_c,
                    :humidity_pct, :pressure_hpa, :wind_speed_ms, :wind_deg,
                    :cloudiness_pct, :visibility_m,
                    :weather_main, :weather_description, :validation_flag
                )
                ON CONFLICT (city_id, recorded_at) DO NOTHING
            """)

            result = session.execute(stmt, {
                "city_id":             city_id,
                "recorded_at":         row["recorded_at"],
                "temperature_c":       _val(row, "temperature_c"),
                "feels_like_c":        _val(row, "feels_like_c"),
                "temp_min_c":          _val(row, "temp_min_c"),
                "temp_max_c":          _val(row, "temp_max_c"),
                "humidity_pct":        _val(row, "humidity_pct"),
                "pressure_hpa":        _val(row, "pressure_hpa"),
                "wind_speed_ms":       _val(row, "wind_speed_ms"),
                "wind_deg":            _val(row, "wind_deg"),
                "cloudiness_pct":      _val(row, "cloudiness_pct"),
                "visibility_m":        _val(row, "visibility_m"),
                "weather_main":        row.get("weather_main"),
                "weather_description": row.get("weather_description"),
                "validation_flag":     row.get("validation_flag", ""),
            })
            inserted += result.rowcount

        session.commit()
        log.info("Weather upsert: %d rows inserted", inserted)

    except Exception as e:
        session.rollback()
        log.error("Weather ingest failed: %s", e)
        raise

    return inserted


# ── Upsert: air quality ────────────────────────────────────────────────────

def ingest_airquality(df: pd.DataFrame, session: Session | None = None) -> int:
    """
    Upsert cleaned air quality DataFrame into air_quality_readings.
    Returns the number of rows inserted.
    """
    session = session or get_session()
    inserted = 0

    try:
        for _, row in df.iterrows():
            city_id = _get_city_id(session, row["city_name"])
            if city_id is None:
                continue

            stmt = text("""
                INSERT INTO air_quality_readings (
                    city_id, recorded_at,
                    aqi, aqi_category,
                    co, no, no2, o3, so2, pm2_5, pm10, nh3,
                    validation_flag
                ) VALUES (
                    :city_id, :recorded_at,
                    :aqi, :aqi_category,
                    :co, :no, :no2, :o3, :so2, :pm2_5, :pm10, :nh3,
                    :validation_flag
                )
                ON CONFLICT (city_id, recorded_at) DO NOTHING
            """)

            result = session.execute(stmt, {
                "city_id":         city_id,
                "recorded_at":     row["recorded_at"],
                "aqi":             _val(row, "aqi"),
                "aqi_category":    row.get("aqi_category"),
                "co":              _val(row, "co"),
                "no":              _val(row, "no"),
                "no2":             _val(row, "no2"),
                "o3":              _val(row, "o3"),
                "so2":             _val(row, "so2"),
                "pm2_5":           _val(row, "pm2_5"),
                "pm10":            _val(row, "pm10"),
                "nh3":             _val(row, "nh3"),
                "validation_flag": row.get("validation_flag", ""),
            })
            inserted += result.rowcount

        session.commit()
        log.info("Air quality upsert: %d rows inserted", inserted)

    except Exception as e:
        session.rollback()
        log.error("Air quality ingest failed: %s", e)
        raise

    return inserted


# ── Helper ─────────────────────────────────────────────────────────────────

def _val(row, col):
    """Return None instead of pandas NA/NaN so psycopg2 maps to SQL NULL."""
    v = row.get(col)
    return None if pd.isna(v) else v
