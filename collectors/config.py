"""
collectors/config.py
Shared configuration: target cities, API base URL, output paths.
"""

from pathlib import Path

# ── Target cities — East & Central Africa ──────────────────────────────────
CITIES = [
    # East Africa - capitals & major cities.
    {"name": "Nairobi",         "country": "KE", "lat": -1.2864,  "lon": 36.8172},
    {"name": "Mombasa",         "country": "KE", "lat": -4.0435,  "lon": 39.6682},
    {"name": "Kampala",         "country": "UG", "lat":  0.3476,  "lon": 32.5825},
    {"name": "Dar es Salaam",   "country": "TZ", "lat": -6.7924,  "lon": 39.2083},
    {"name": "Kisumu",          "country": "KE", "lat": -0.0917,  "lon": 34.7680},
    {"name": "Dodoma",          "country": "TZ", "lat": -6.1630,  "lon": 35.7516},
    {"name": "Arusha",          "country": "TZ", "lat": -3.3869,  "lon": 36.6830},
    {"name": "Kigali",          "country": "RW", "lat": -1.9441,  "lon": 30.0619},
    {"name": "Bujumbura",       "country": "BI", "lat": -3.3614,  "lon": 29.3599},
    {"name": "Juba",            "country": "SS", "lat":  4.8594,  "lon": 31.5713},
    {"name": "Addis Ababa",     "country": "ET", "lat":  9.0301,  "lon": 38.7400},
    {"name": "Dire Dawa",       "country": "ET", "lat":  9.5931,  "lon": 41.8500},
    {"name": "Mogadishu",       "country": "SO", "lat":  2.0469,  "lon": 45.3182},
    {"name": "Djibouti City",   "country": "DJ", "lat": 11.5886,  "lon": 43.1456},
    {"name": "Asmara",          "country": "ER", "lat": 15.3229,  "lon": 38.9251},

    # Central Africa — capitals & major cities
    {"name": "Kinshasa",        "country": "CD", "lat": -4.4419,  "lon": 15.2663},
    {"name": "Lubumbashi",      "country": "CD", "lat": -11.6609, "lon": 27.4794},
    {"name": "Goma",            "country": "CD", "lat": -1.6792,  "lon": 29.2228},
    {"name": "Brazzaville",     "country": "CG", "lat": -4.2634,  "lon": 15.2429},
    {"name": "Yaoundé",         "country": "CM", "lat":  3.8480,  "lon": 11.5021},
    {"name": "Douala",          "country": "CM", "lat":  4.0511,  "lon": 9.7679},
    {"name": "Bangui",          "country": "CF", "lat":  4.3947,  "lon": 18.5582},
    {"name": "N'Djamena",       "country": "TD", "lat": 12.1348,  "lon": 15.0557},
    {"name": "Libreville",      "country": "GA", "lat":  0.4162,  "lon": 9.4673},
    {"name": "Malabo",          "country": "GQ", "lat":  3.7523,  "lon": 8.7741},
]

# ── API ────────────────────────────────────────────────────────────────────
OWM_BASE_URL = "https://api.openweathermap.org/data/2.5"

# Seconds to wait between city requests to stay well under rate limits
REQUEST_DELAY = 1.0

# ── Paths ──────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR      = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
