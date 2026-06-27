"""
cleaning/clean_airquality.py
Cleans and validates raw air quality records from collectors.airquality.

Steps:
  1. Load records into a DataFrame
  2. Drop rows missing primary key fields (city_name, recorded_at)
  3. Deduplicate on (city_name, recorded_at)
  4. Validate value ranges
  5. Map OWM AQI (1–5) to a human-readable category column
  6. Cast to correct dtypes
  7. Save cleaned CSV to data/processed/
"""

# TODO: OWM API key setup — come back to document where to get the key,
#       how to set it in .env, and confirm free-tier limits before first run.

import logging
from datetime import datetime, timezone

import pandas as pd
import numpy as np

from collectors.config import PROCESSED_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("cleaning.airquality")

# ── OWM AQI scale (European) ───────────────────────────────────────────────
AQI_CATEGORIES = {
    1: "Good",
    2: "Fair",
    3: "Moderate",
    4: "Poor",
    5: "Very Poor",
}

# ── Validation bounds (μg/m³ unless noted) ────────────────────────────────
# Upper bounds are generous — we flag, not drop.
BOUNDS = {
    "aqi":   (1,    5),
    "co":    (0, 15400),   # CO can spike very high in pollution events
    "no":    (0,  1000),
    "no2":   (0,   500),
    "o3":    (0,   500),
    "so2":   (0,   500),
    "pm2_5": (0,  1000),
    "pm10":  (0,  1000),
    "nh3":   (0,   500),
}


# ── Main clean function ────────────────────────────────────────────────────

def clean_airquality(records: list[dict]) -> pd.DataFrame:
    """
    Clean a list of raw air quality dicts (from collectors.airquality.collect_all).
    Returns a cleaned DataFrame and saves it to data/processed/.
    """
    if not records:
        log.warning("No air quality records to clean.")
        return pd.DataFrame()

    df = pd.DataFrame(records)
    initial_count = len(df)
    log.info("Starting clean: %d air quality records", initial_count)

    # 1. Drop rows missing primary key fields
    df = _drop_missing_keys(df)

    # 2. Deduplicate
    df = _deduplicate(df)

    # 3. Validate ranges
    df = _validate_bounds(df)

    # 4. Add human-readable AQI category
    df["aqi_category"] = df["aqi"].map(AQI_CATEGORIES).fillna("Unknown")

    # 5. Cast dtypes
    df = _cast_types(df)

    log.info(
        "Clean complete: %d → %d records (dropped %d)",
        initial_count, len(df), initial_count - len(df),
    )

    _save(df, "airquality")
    return df


# ── Steps ──────────────────────────────────────────────────────────────────

def _drop_missing_keys(df: pd.DataFrame) -> pd.DataFrame:
    before = len(df)
    df = df.dropna(subset=["city_name", "recorded_at"])
    dropped = before - len(df)
    if dropped:
        log.warning("Dropped %d rows with null primary key fields", dropped)
    return df


def _deduplicate(df: pd.DataFrame) -> pd.DataFrame:
    before = len(df)
    df = df.drop_duplicates(subset=["city_name", "recorded_at"], keep="first")
    dropped = before - len(df)
    if dropped:
        log.warning("Dropped %d duplicate (city_name, recorded_at) rows", dropped)
    return df


def _validate_bounds(df: pd.DataFrame) -> pd.DataFrame:
    df["validation_flag"] = ""

    for col, (low, high) in BOUNDS.items():
        if col not in df.columns:
            continue
        mask = df[col].notna() & ~df[col].between(low, high)
        if mask.any():
            cities = df.loc[mask, "city_name"].tolist()
            log.warning(
                "Out-of-range %s (expected %s–%s): %s",
                col, low, high, cities,
            )
            df.loc[mask, "validation_flag"] += f"{col}:out_of_range;"

    return df


def _cast_types(df: pd.DataFrame) -> pd.DataFrame:
    df["recorded_at"] = pd.to_datetime(df["recorded_at"], utc=True)
    df["aqi"]         = pd.to_numeric(df["aqi"],   errors="coerce").astype("Int64")
    for col in ["co", "no", "no2", "o3", "so2", "pm2_5", "pm10", "nh3"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# ── Save ───────────────────────────────────────────────────────────────────

def _save(df: pd.DataFrame, kind: str) -> None:
    ts       = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = PROCESSED_DIR / f"{kind}_clean_{ts}.csv"
    df.to_csv(filename, index=False)
    log.info("Saved cleaned data → %s", filename)


# ── CLI ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from collectors.airquality import collect_all
    records = collect_all()
    df = clean_airquality(records)
    print(df.to_string())
