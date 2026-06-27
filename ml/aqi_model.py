"""
ml/aqi_model.py
Trains a RandomForestRegressor to predict AQI from weather variables.

Features : temperature_c, humidity_pct, wind_speed_ms, pressure_hpa
Target   : aqi (continuous, 1-5 OWM scale)

Usage:
  python -m ml.aqi_model           # train and save model.pkl
  python -m ml.aqi_model --predict # load saved model, predict for all cities
"""

import argparse
import json
import logging
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sqlalchemy import create_engine

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
log = logging.getLogger("ml.aqi_model")

MODEL_DIR  = Path(__file__).parent
MODEL_PATH = MODEL_DIR / "model.pkl"
META_PATH  = MODEL_DIR / "model_metrics.json"

FEATURES = ["temperature_c", "humidity_pct", "wind_speed_ms", "pressure_hpa"]
TARGET   = "aqi"


def load_training_data() -> pd.DataFrame:
    engine = create_engine(
        f"postgresql+psycopg2://"
        f"{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST','localhost')}:{os.getenv('DB_PORT',5432)}"
        f"/{os.getenv('DB_NAME','eaweather')}"
    )
    query = """
        SELECT w.temperature_c, w.humidity_pct, w.wind_speed_ms,
               w.pressure_hpa, a.aqi
        FROM weather_readings w
        JOIN air_quality_readings a
            ON  a.city_id = w.city_id
            AND ABS(EXTRACT(EPOCH FROM (a.recorded_at - w.recorded_at))) <= 7200
        WHERE w.temperature_c IS NOT NULL AND w.humidity_pct IS NOT NULL
          AND w.wind_speed_ms IS NOT NULL AND w.pressure_hpa IS NOT NULL
          AND a.aqi IS NOT NULL
    """
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)
    log.info("Loaded %d joined rows for training", len(df))
    return df.dropna()


def train(df: pd.DataFrame) -> dict:
    X = df[FEATURES].values
    y = df[TARGET].values
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    scaler  = StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_test  = scaler.transform(X_test)
    model   = RandomForestRegressor(n_estimators=100, max_depth=8,
                                     min_samples_leaf=3, random_state=42, n_jobs=-1)
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)
    mae    = round(float(mean_absolute_error(y_test, y_pred)), 4)
    r2     = round(float(r2_score(y_test, y_pred)), 4)
    log.info("MAE: %.4f   R2: %.4f", mae, r2)
    importances = dict(zip(FEATURES, model.feature_importances_.round(4).tolist()))
    bundle = {"model": model, "scaler": scaler, "features": FEATURES}
    joblib.dump(bundle, MODEL_PATH)
    log.info("Model saved to %s", MODEL_PATH)
    metrics = {"mae": mae, "r2": r2, "feature_importances": importances,
               "train_rows": len(X_train), "test_rows": len(X_test)}
    with open(META_PATH, "w") as f:
        json.dump(metrics, f, indent=2)
    return metrics


def predict_current() -> pd.DataFrame:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"No model at {MODEL_PATH} - run training first.")
    bundle = joblib.load(MODEL_PATH)
    model, scaler = bundle["model"], bundle["scaler"]
    engine = create_engine(
        f"postgresql+psycopg2://"
        f"{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST','localhost')}:{os.getenv('DB_PORT',5432)}"
        f"/{os.getenv('DB_NAME','eaweather')}"
    )
    query = """
        SELECT DISTINCT ON (city_id) c.city_name,
               w.temperature_c, w.humidity_pct, w.wind_speed_ms, w.pressure_hpa
        FROM weather_readings w JOIN cities c USING (city_id)
        WHERE w.temperature_c IS NOT NULL AND w.humidity_pct IS NOT NULL
          AND w.wind_speed_ms IS NOT NULL AND w.pressure_hpa IS NOT NULL
        ORDER BY city_id, w.recorded_at DESC
    """
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)
    X = scaler.transform(df[FEATURES].values)
    df["predicted_aqi"] = model.predict(X).round(2)
    for _, row in df.iterrows():
        log.info("  %-16s predicted AQI %.2f", row["city_name"], row["predicted_aqi"])
    return df[["city_name", *FEATURES, "predicted_aqi"]]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--predict", action="store_true")
    args = parser.parse_args()
    if args.predict:
        print(predict_current().to_string(index=False))
    else:
        df = load_training_data()
        print(json.dumps(train(df), indent=2))
