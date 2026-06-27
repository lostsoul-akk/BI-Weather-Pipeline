"""
collectors/airquality.py
Fetches air pollution data from OpenWeatherMap /data/2.5/air_pollution.

OWM AQI scale (European standard):
  1 = Good  2 = Fair  3 = Moderate  4 = Poor  5 = Very Poor

Fields collected:
  city_name, country, lat, lon, recorded_at (UTC),
  aqi (1–5), co, no, no2, o3, so2, pm2_5, pm10, nh3
  (all component concentrations in μg/m³)
"""

import json
import logging
import os
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

from collectors.config import CITIES, OWM_BASE_URL, RAW_DIR, REQUEST_DELAY

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("collectors.airquality")

ENDPOINT = f"{OWM_BASE_URL}/air_pollution"

# Human-readable AQI labels for logging
AQI_LABELS = {1: "Good", 2: "Fair", 3: "Moderate", 4: "Poor", 5: "Very Poor"}


# ── Fetch ──────────────────────────────────────────────────────────────────

def fetch_airquality(city: dict, api_key: str) -> dict | None:
    """
    Call OWM air pollution endpoint for one city.
    Returns a flat dict of cleaned fields, or None on failure.
    """
    params = {
        "lat":   city["lat"],
        "lon":   city["lon"],
        "appid": api_key,
    }

    try:
        resp = requests.get(ENDPOINT, params=params, timeout=10)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        log.error("HTTP error for %s: %s", city["name"], e)
        return None
    except requests.exceptions.RequestException as e:
        log.error("Request failed for %s: %s", city["name"], e)
        return None

    raw = resp.json()
    _save_raw(raw, city["name"], "airquality")

    return _parse(raw, city)


def _parse(raw: dict, city: dict) -> dict:
    """Extract AQI and all pollutant component concentrations."""
    # OWM wraps results in a list; we always want index 0 (current)
    entry      = raw.get("list", [{}])[0]
    main       = entry.get("main", {})
    components = entry.get("components", {})

    recorded_at = datetime.fromtimestamp(entry["dt"], tz=timezone.utc).isoformat()

    return {
        "city_name":   city["name"],
        "country":     city["country"],
        "lat":         city["lat"],
        "lon":         city["lon"],
        "recorded_at": recorded_at,
        # AQI index 1–5
        "aqi":         main.get("aqi"),
        # Concentrations in μg/m³
        "co":          components.get("co"),
        "no":          components.get("no"),
        "no2":         components.get("no2"),
        "o3":          components.get("o3"),
        "so2":         components.get("so2"),
        "pm2_5":       components.get("pm2_5"),
        "pm10":        components.get("pm10"),
        "nh3":         components.get("nh3"),
    }


def _save_raw(raw: dict, city_name: str, kind: str) -> None:
    """Persist raw API response as JSON for audit / replay."""
    ts       = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug     = city_name.lower().replace(" ", "_")
    filename = RAW_DIR / f"{kind}_{slug}_{ts}.json"
    with open(filename, "w") as f:
        json.dump(raw, f, indent=2)
    log.debug("Raw saved → %s", filename)


# ── Collect all cities ─────────────────────────────────────────────────────

def collect_all(api_key: str | None = None, cities: list[dict] | None = None) -> list[dict]:
    """
    Fetch air quality for all configured cities (or a supplied subset).
    Returns a list of parsed dicts (skips cities that errored).
    """
    api_key = api_key or os.getenv("OWM_API_KEY")
    if not api_key:
        raise EnvironmentError("OWM_API_KEY not set — check your .env file.")

    targets = cities if cities is not None else CITIES
    results = []
    for city in targets:
        log.info("Fetching air quality → %s", city["name"])
        record = fetch_airquality(city, api_key)
        if record:
            results.append(record)
            aqi_label = AQI_LABELS.get(record["aqi"], "Unknown")
            log.info(
                "  ✓ %s  AQI=%s (%s)  PM2.5=%.1f  PM10=%.1f",
                city["name"],
                record["aqi"],
                aqi_label,
                record["pm2_5"] or 0,
                record["pm10"] or 0,
            )
        else:
            log.warning("  ✗ %s — skipped due to error", city["name"])

        time.sleep(REQUEST_DELAY)

    log.info("Air quality collection complete: %d/%d cities", len(results), len(targets))
    return results


# ── CLI entry point ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import pprint
    records = collect_all()
    pprint.pprint(records)
