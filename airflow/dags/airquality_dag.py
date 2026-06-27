"""
airflow/dags/airquality_dag.py
Every-3-hour DAG: collect → clean → ingest air quality → alert if AQI >= 4.

OWM AQI scale: 1=Good 2=Fair 3=Moderate 4=Poor 5=Very Poor
Alert fires when any city hits 4 or above.
"""

import os
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText

from airflow import DAG
from airflow.operators.python import PythonOperator, BranchPythonOperator
from airflow.operators.empty import EmptyOperator

# ── Default args ───────────────────────────────────────────────────────────
default_args = {
    "owner":            "eaweather",
    "retries":          3,
    "retry_delay":      timedelta(minutes=5),
    "email_on_failure": True,
    "email_on_retry":   False,
    "email":            ["{{ var.value.alert_email }}"],
}

AQI_ALERT_THRESHOLD = 4   # Poor or worse


# ── Task callables ─────────────────────────────────────────────────────────

def task_collect(**ctx):
    from collectors.airquality import collect_all
    records = collect_all()
    if not records:
        raise ValueError("Collector returned 0 records — aborting.")
    ctx["ti"].xcom_push(key="raw_records", value=records)


def task_clean(**ctx):
    from cleaning.clean_airquality import clean_airquality

    records = ctx["ti"].xcom_pull(key="raw_records", task_ids="collect_airquality")
    df = clean_airquality(records)
    if df.empty:
        raise ValueError("Cleaning produced an empty DataFrame — aborting.")
    ctx["ti"].xcom_push(key="clean_df_json", value=df.to_json(date_format="iso"))


def task_ingest(**ctx):
    from db.ingest import get_session, ingest_airquality
    import pandas as pd

    df_json = ctx["ti"].xcom_pull(key="clean_df_json", task_ids="clean_airquality")
    df = pd.read_json(df_json)
    df["recorded_at"] = pd.to_datetime(df["recorded_at"], utc=True)

    session  = get_session()
    inserted = ingest_airquality(df, session)
    ctx["ti"].xcom_push(key="rows_inserted", value=inserted)


def task_check_aqi(**ctx) -> str:
    """
    Branch: return 'send_aqi_alert' if any city is at AQI >= threshold,
    otherwise return 'no_alert'.
    """
    import pandas as pd

    df_json = ctx["ti"].xcom_pull(key="clean_df_json", task_ids="clean_airquality")
    df = pd.read_json(df_json)

    breached = df[df["aqi"] >= AQI_ALERT_THRESHOLD][["city_name", "aqi", "aqi_category"]]
    ctx["ti"].xcom_push(key="breached_json", value=breached.to_json())

    return "send_aqi_alert" if not breached.empty else "no_alert"


def task_send_alert(**ctx):
    """Send an SMTP email listing cities above the AQI threshold."""
    import pandas as pd

    breached_json = ctx["ti"].xcom_pull(key="breached_json", task_ids="check_aqi")
    breached = pd.read_json(breached_json)

    lines = "\n".join(
        f"  • {row.city_name}: AQI {row.aqi} ({row.aqi_category})"
        for _, row in breached.iterrows()
    )
    run_time = ctx["logical_date"].strftime("%Y-%m-%d %H:%M UTC")

    body = (
        f"⚠️  EAWeather AQI Alert — {run_time}\n\n"
        f"The following cities have reached AQI ≥ {AQI_ALERT_THRESHOLD} (Poor or worse):\n\n"
        f"{lines}\n\n"
        f"OWM scale: 1=Good  2=Fair  3=Moderate  4=Poor  5=Very Poor\n"
        f"Please review the dashboard for details."
    )

    msg = MIMEText(body)
    msg["Subject"] = f"⚠️  AQI Alert — {breached['city_name'].tolist()}"
    msg["From"]    = os.getenv("SMTP_USER", "")
    msg["To"]      = os.getenv("ALERT_EMAIL", "")

    with smtplib.SMTP(os.getenv("SMTP_HOST", "smtp.gmail.com"),
                      int(os.getenv("SMTP_PORT", 587))) as server:
        server.starttls()
        server.login(os.getenv("SMTP_USER", ""), os.getenv("SMTP_PASSWORD", ""))
        server.send_message(msg)


# ── DAG ────────────────────────────────────────────────────────────────────

with DAG(
    dag_id="airquality_pipeline",
    description="3-hourly air quality ETL + AQI alert for 4 East African cities",
    schedule="0 */3 * * *",
    start_date=datetime(2026, 6, 1),
    catchup=False,
    default_args=default_args,
    tags=["eaweather", "airquality"],
) as dag:

    collect = PythonOperator(
        task_id="collect_airquality",
        python_callable=task_collect,
    )

    clean = PythonOperator(
        task_id="clean_airquality",
        python_callable=task_clean,
    )

    ingest = PythonOperator(
        task_id="ingest_airquality",
        python_callable=task_ingest,
    )

    check = BranchPythonOperator(
        task_id="check_aqi",
        python_callable=task_check_aqi,
    )

    alert = PythonOperator(
        task_id="send_aqi_alert",
        python_callable=task_send_alert,
    )

    no_alert = EmptyOperator(task_id="no_alert")

    collect >> clean >> ingest >> check >> [alert, no_alert]
