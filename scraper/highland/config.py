"""Static configuration shared by all sources."""
from __future__ import annotations

HOME_ZIP = "77479"           # Sugar Land, TX
HOME_LAT = 29.5994
HOME_LNG = -95.6349
LOCAL_RADIUS_MI = 100        # "local" sources are searched within this radius of HOME_ZIP
MIN_YEAR = 2024              # Highland refresh = 2024+ model year; everything older is dropped
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
# Per-domain minimum seconds between requests (politeness). Overridden by robots.txt Crawl-delay.
DEFAULT_MIN_INTERVAL_S = 1.0
# How many days a removed listing stays in the exported JSON (for the change log).
CHANGE_WINDOW_DAYS = 14
