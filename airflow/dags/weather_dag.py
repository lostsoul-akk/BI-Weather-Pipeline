"""
airflow/dags/weather_dag.py
Hourly DAG: collect → clean → ingest weather for all 4 cities.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

# ── Default args ───────────────────────────────────────────────────────────
default_args = {
    "owner":            "eaweather",
    "retries":          3,
    "retry_delay":      timedelta(minutes=5),
    "email_on_failure": True,
    "email_on_retry":   False,
    "email":            ["{{ var.value.alert_email }}"],
}

# ── Task callables ─────────────────────────────────────────────────────────

def task_collect(**ctx):
    from collectors.weather import collect_all
    records = collect_all()
    if not records:
        raise ValueError("Collector returned 0 records — aborting.")
    # Push to XCom so the next task can pull it
    ctx["ti"].xcom_push(key="raw_records", value=records)


def task_clean(**ctx):
    from cleaning.clean_weather import clean_weather
    import pandas as pd

    records = ctx["ti"].xcom_pull(key="raw_records", task_ids="collect_weather")
    df = clean_weather(records)
    if df.empty:
        raise ValueError("Cleaning produced an empty DataFrame — aborting.")
    # Serialise to JSON for XCom (DataFrames can't be pickled across tasks safely)
    ctx["ti"].xcom_push(key="clean_df_json", value=df.to_json(date_format="iso"))


def task_ingest(**ctx):
    from db.ingest import get_session, ingest_weather
    import pandas as pd

    df_json = ctx["ti"].xcom_pull(key="clean_df_json", task_ids="clean_weather")
    df = pd.read_json(df_json)
    df["recorded_at"] = pd.to_datetime(df["recorded_at"], utc=True)

    session  = get_session()
    inserted = ingest_weather(df, session)
    ctx["ti"].xcom_push(key="rows_inserted", value=inserted)


# ── DAG ────────────────────────────────────────────────────────────────────

with DAG(
    dag_id="weather_pipeline",
    description="Hourly weather ETL for 4 East African cities",
    schedule="@hourly",
    start_date=datetime(2026, 6, 1),
    catchup=False,
    default_args=default_args,
    tags=["eaweather", "weather"],
) as dag:

    collect = PythonOperator(
        task_id="collect_weather",
        python_callable=task_collect,
    )

    clean = PythonOperator(
        task_id="clean_weather",
        python_callable=task_clean,
    )

    ingest = PythonOperator(
        task_id="ingest_weather",
        python_callable=task_ingest,
    )

    collect >> clean >> ingest
