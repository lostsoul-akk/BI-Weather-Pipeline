"""
airflow/dags/daily_summary_dag.py
Daily DAG: aggregate yesterday's readings into daily_summaries.

Runs at 00:15 UTC so hourly weather and 3-hourly AQI data
for the previous day are all safely committed before aggregation.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

default_args = {
    "owner":            "eaweather",
    "retries":          2,
    "retry_delay":      timedelta(minutes=10),
    "email_on_failure": True,
    "email_on_retry":   False,
    "email":            ["{{ var.value.alert_email }}"],
}


# ── Task callable ──────────────────────────────────────────────────────────

def task_build_summaries(**ctx):
    """
    For each city, aggregate yesterday's weather_readings and
    air_quality_readings into a single daily_summaries row.
    Uses INSERT ... ON CONFLICT DO UPDATE so re-runs are safe.
    """
    import logging
    from datetime import date, timedelta

    from sqlalchemy import text
    from db.ingest import get_session

    log     = logging.getLogger("daily_summary_dag")
    session = get_session()

    # Target date: yesterday in UTC
    target_date = (ctx["logical_date"].date() - timedelta(days=1))
    log.info("Building daily summaries for %s", target_date)

    sql = text("""
        INSERT INTO daily_summaries (
            city_id, summary_date,
            avg_temp_c, min_temp_c, max_temp_c,
            avg_humidity, avg_wind_ms,
            avg_aqi, max_aqi,
            dominant_weather
        )
        SELECT
            w.city_id,
            DATE(w.recorded_at AT TIME ZONE 'UTC')          AS summary_date,
            ROUND(AVG(w.temperature_c)::numeric, 2)         AS avg_temp_c,
            ROUND(MIN(w.temperature_c)::numeric, 2)         AS min_temp_c,
            ROUND(MAX(w.temperature_c)::numeric, 2)         AS max_temp_c,
            ROUND(AVG(w.humidity_pct)::numeric, 2)          AS avg_humidity,
            ROUND(AVG(w.wind_speed_ms)::numeric, 3)         AS avg_wind_ms,
            ROUND(AVG(a.aqi)::numeric, 2)                   AS avg_aqi,
            MAX(a.aqi)                                      AS max_aqi,
            MODE() WITHIN GROUP (ORDER BY w.weather_main)   AS dominant_weather
        FROM weather_readings w
        LEFT JOIN air_quality_readings a
            ON  a.city_id    = w.city_id
            AND DATE(a.recorded_at AT TIME ZONE 'UTC') = DATE(w.recorded_at AT TIME ZONE 'UTC')
        WHERE DATE(w.recorded_at AT TIME ZONE 'UTC') = :target_date
        GROUP BY w.city_id, summary_date
        ON CONFLICT (city_id, summary_date)
        DO UPDATE SET
            avg_temp_c       = EXCLUDED.avg_temp_c,
            min_temp_c       = EXCLUDED.min_temp_c,
            max_temp_c       = EXCLUDED.max_temp_c,
            avg_humidity     = EXCLUDED.avg_humidity,
            avg_wind_ms      = EXCLUDED.avg_wind_ms,
            avg_aqi          = EXCLUDED.avg_aqi,
            max_aqi          = EXCLUDED.max_aqi,
            dominant_weather = EXCLUDED.dominant_weather
    """)

    try:
        result = session.execute(sql, {"target_date": target_date})
        session.commit()
        log.info("Daily summaries upserted: %d rows for %s", result.rowcount, target_date)
    except Exception as e:
        session.rollback()
        log.error("Daily summary failed: %s", e)
        raise


# ── DAG ────────────────────────────────────────────────────────────────────

with DAG(
    dag_id="daily_summary_pipeline",
    description="Daily aggregation of weather + AQI into daily_summaries",
    schedule="15 0 * * *",     # 00:15 UTC every day
    start_date=datetime(2026, 6, 1),
    catchup=False,
    default_args=default_args,
    tags=["eaweather", "summary"],
) as dag:

    build = PythonOperator(
        task_id="build_daily_summaries",
        python_callable=task_build_summaries,
    )
