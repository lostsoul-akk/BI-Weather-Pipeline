"""
collectors/weather.py
Fetches current weather from OpenWeatherMap /data/2.5/weather for each city.

Fields collected:
  city_name, country, lat, lon, recorded_at (UTC),
  temperature_c, feels_like_c, temp_min_c, temp_max_c,
  humidity_pct, pressure_hpa, wind_speed_ms, wind_deg,
  cloudiness_pct, visibility_m, weather_main, weather_description
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

from collectors.config import CITIES, OWM_BASE_URL, RAW_DIR, REQUEST_DELAY

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("collectors.weather")

ENDPOINT = f"{OWM_BASE_URL}/weather"


# ── Fetch ──────────────────────────────────────────────────────────────────

def fetch_weather(city: dict, api_key: str) -> dict | None:
    """
    Call OWM current weather for one city.
    Returns a flat dict of cleaned fields, or None on failure.
    """
    params = {
        "lat":   city["lat"],
        "lon":   city["lon"],
        "units": "metric",   # temperatures in °C, wind in m/s
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
    _save_raw(raw, city["name"], "weather")

    return _parse(raw, city)


def _parse(raw: dict, city: dict) -> dict:
    """Extract and flatten only the fields we care about."""
    main    = raw.get("main", {})
    wind    = raw.get("wind", {})
    clouds  = raw.get("clouds", {})
    weather = raw.get("weather", [{}])[0]

    # OWM returns dt as a Unix UTC timestamp
    recorded_at = datetime.fromtimestamp(raw["dt"], tz=timezone.utc).isoformat()

    return {
        "city_name":           city["name"],
        "country":             city["country"],
        "lat":                 city["lat"],
        "lon":                 city["lon"],
        "recorded_at":         recorded_at,
        "temperature_c":       main.get("temp"),
        "feels_like_c":        main.get("feels_like"),
        "temp_min_c":          main.get("temp_min"),
        "temp_max_c":          main.get("temp_max"),
        "humidity_pct":        main.get("humidity"),
        "pressure_hpa":        main.get("pressure"),
        "wind_speed_ms":       wind.get("speed"),
        "wind_deg":            wind.get("deg"),
        "cloudiness_pct":      clouds.get("all"),
        "visibility_m":        raw.get("visibility"),
        "weather_main":        weather.get("main"),
        "weather_description": weather.get("description"),
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
    Fetch weather for all configured cities (or a supplied subset).
    Returns a list of parsed dicts (skips cities that errored).
    """
    api_key = api_key or os.getenv("OWM_API_KEY")
    if not api_key:
        raise EnvironmentError("OWM_API_KEY not set — check your .env file.")

    targets = cities if cities is not None else CITIES
    results = []
    for city in targets:
        log.info("Fetching weather → %s", city["name"])
        record = fetch_weather(city, api_key)
        if record:
            results.append(record)
            log.info(
                "  ✓ %s  %.1f°C  %d%% RH  wind %.1f m/s",
                city["name"],
                record["temperature_c"],
                record["humidity_pct"],
                record["wind_speed_ms"] or 0,
            )
        else:
            log.warning("  ✗ %s — skipped due to error", city["name"])

        time.sleep(REQUEST_DELAY)

    log.info("Weather collection complete: %d/%d cities", len(results), len(targets))
    return results


# ── CLI entry point ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import pprint
    records = collect_all()
    pprint.pprint(records)
