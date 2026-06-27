"""
pipeline/run_pipeline.py
Single entry point — chains collect → clean → ingest for both data types.

Usage:
  python -m pipeline.run_pipeline                     # run everything
  python -m pipeline.run_pipeline --type weather      # weather only
  python -m pipeline.run_pipeline --type airquality   # air quality only
  python -m pipeline.run_pipeline --city Nairobi      # one city only
"""

import argparse
import logging
import sys
import time
from datetime import datetime, timezone

from collectors.config import CITIES
from collectors.weather import collect_all as collect_weather
from collectors.airquality import collect_all as collect_airquality
from cleaning.clean_weather import clean_weather
from cleaning.clean_airquality import clean_airquality
from db.ingest import get_session, ingest_weather, ingest_airquality

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("pipeline.log"),
    ],
)
log = logging.getLogger("pipeline")


# ── Pipeline steps ─────────────────────────────────────────────────────────

def run_weather(city_filter: str | None = None) -> dict:
    """Collect → clean → ingest weather. Returns a result summary dict."""
    log.info("━━ WEATHER PIPELINE START ━━")
    start = time.time()

    cities = _filter_cities(city_filter)

    raw     = collect_weather(cities=cities)
    df      = clean_weather(raw)
    session = get_session()
    inserted = ingest_weather(df, session)

    elapsed = round(time.time() - start, 2)
    log.info("━━ WEATHER PIPELINE DONE — %d rows inserted in %ss ━━", inserted, elapsed)
    return {"type": "weather", "records_collected": len(raw), "rows_inserted": inserted, "elapsed_s": elapsed}


def run_airquality(city_filter: str | None = None) -> dict:
    """Collect → clean → ingest air quality. Returns a result summary dict."""
    log.info("━━ AIR QUALITY PIPELINE START ━━")
    start = time.time()

    cities = _filter_cities(city_filter)

    raw      = collect_airquality(cities=cities)
    df       = clean_airquality(raw)
    session  = get_session()
    inserted = ingest_airquality(df, session)

    elapsed = round(time.time() - start, 2)
    log.info("━━ AIR QUALITY PIPELINE DONE — %d rows inserted in %ss ━━", inserted, elapsed)
    return {"type": "airquality", "records_collected": len(raw), "rows_inserted": inserted, "elapsed_s": elapsed}


# ── Entry point ────────────────────────────────────────────────────────────

def main():
    args   = _parse_args()
    run_at = datetime.now(timezone.utc).isoformat()
    results = []

    log.info("Pipeline run starting at %s", run_at)

    try:
        if args.type in ("weather", "all"):
            results.append(run_weather(args.city))

        if args.type in ("airquality", "all"):
            results.append(run_airquality(args.city))

    except Exception as e:
        log.error("Pipeline failed: %s", e, exc_info=True)
        sys.exit(1)

    # ── Summary ────────────────────────────────────────────────────────────
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("PIPELINE SUMMARY")
    for r in results:
        log.info(
            "  %-12s collected=%d  inserted=%d  time=%ss",
            r["type"], r["records_collected"], r["rows_inserted"], r["elapsed_s"],
        )
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")


# ── Helpers ────────────────────────────────────────────────────────────────

def _filter_cities(city_filter: str | None) -> list[dict]:
    """Return full city list or a single-city list if --city was passed."""
    if not city_filter:
        return CITIES
    match = [c for c in CITIES if c["name"].lower() == city_filter.lower()]
    if not match:
        valid = [c["name"] for c in CITIES]
        log.error("Unknown city '%s'. Valid options: %s", city_filter, valid)
        sys.exit(1)
    return match


def _parse_args():
    parser = argparse.ArgumentParser(description="EAWeather ETL pipeline runner")
    parser.add_argument(
        "--type",
        choices=["weather", "airquality", "all"],
        default="all",
        help="Which pipeline to run (default: all)",
    )
    parser.add_argument(
        "--city",
        default=None,
        help="Run for one city only, e.g. --city Nairobi",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
