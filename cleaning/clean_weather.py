"""
cleaning/clean_weather.py
Cleans and validates raw weather records returned by collectors.weather.

Steps:
  1. Load records into a DataFrame
  2. Drop rows missing primary key fields (city_name, recorded_at)
  3. Deduplicate on (city_name, recorded_at)
  4. Validate value ranges — out-of-range rows are flagged, not silently dropped
  5. Cast to correct dtypes
  6. Save cleaned CSV to data/processed/
"""

# TODO: OWM API key setup — come back to document where to get the key,
#       how to set it in .env, and confirm free-tier limits before first run.

import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import numpy as np

from collectors.config import PROCESSED_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("cleaning.weather")

# ── Validation bounds ──────────────────────────────────────────────────────
BOUNDS = {
    "temperature_c":  (-40,  60),
    "feels_like_c":   (-50,  70),
    "temp_min_c":     (-40,  60),
    "temp_max_c":     (-40,  60),
    "humidity_pct":   (  0, 100),
    "pressure_hpa":   (870, 1085),
    "wind_speed_ms":  (  0,  90),
    "cloudiness_pct": (  0, 100),
}


# ── Main clean function ────────────────────────────────────────────────────

def clean_weather(records: list[dict]) -> pd.DataFrame:
    """
    Clean a list of raw weather dicts (from collectors.weather.collect_all).
    Returns a cleaned DataFrame and saves it to data/processed/.
    """
    if not records:
        log.warning("No weather records to clean.")
        return pd.DataFrame()

    df = pd.DataFrame(records)
    initial_count = len(df)
    log.info("Starting clean: %d weather records", initial_count)

    # 1. Drop rows missing primary key fields
    df = _drop_missing_keys(df)

    # 2. Deduplicate
    df = _deduplicate(df)

    # 3. Validate ranges
    df = _validate_bounds(df)

    # 4. Cast dtypes
    df = _cast_types(df)

    # 5. Fill known safe defaults for minor nulls
    df["cloudiness_pct"] = df["cloudiness_pct"].fillna(0)
    df["visibility_m"]   = df["visibility_m"].fillna(np.nan)

    log.info(
        "Clean complete: %d → %d records (dropped %d)",
        initial_count, len(df), initial_count - len(df),
    )

    _save(df, "weather")
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
    """
    Flag rows where a numeric field falls outside expected bounds.
    Logs a warning per violation but keeps the row — the DB upsert
    will still store it; analysts can filter the flag column.
    """
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
    df["recorded_at"]     = pd.to_datetime(df["recorded_at"], utc=True)
    df["temperature_c"]   = pd.to_numeric(df["temperature_c"],  errors="coerce")
    df["feels_like_c"]    = pd.to_numeric(df["feels_like_c"],   errors="coerce")
    df["temp_min_c"]      = pd.to_numeric(df["temp_min_c"],     errors="coerce")
    df["temp_max_c"]      = pd.to_numeric(df["temp_max_c"],     errors="coerce")
    df["humidity_pct"]    = pd.to_numeric(df["humidity_pct"],   errors="coerce")
    df["pressure_hpa"]    = pd.to_numeric(df["pressure_hpa"],   errors="coerce")
    df["wind_speed_ms"]   = pd.to_numeric(df["wind_speed_ms"],  errors="coerce")
    df["wind_deg"]        = pd.to_numeric(df["wind_deg"],       errors="coerce").astype("Int64")
    df["cloudiness_pct"]  = pd.to_numeric(df["cloudiness_pct"], errors="coerce").astype("Int64")
    df["visibility_m"]    = pd.to_numeric(df["visibility_m"],   errors="coerce").astype("Int64")
    return df


# ── Save ───────────────────────────────────────────────────────────────────

def _save(df: pd.DataFrame, kind: str) -> None:
    ts       = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = PROCESSED_DIR / f"{kind}_clean_{ts}.csv"
    df.to_csv(filename, index=False)
    log.info("Saved cleaned data → %s", filename)


# ── CLI ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from collectors.weather import collect_all
    records = collect_all()
    df = clean_weather(records)
    print(df.to_string())
