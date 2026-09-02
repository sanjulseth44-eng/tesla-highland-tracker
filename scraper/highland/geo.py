"""Distance helpers. All distances are straight-line miles from HOME_ZIP (77479)."""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Optional

from .config import HOME_LAT, HOME_LNG


def haversine_mi(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def distance_from_home(lat: float, lng: float) -> float:
    return round(haversine_mi(HOME_LAT, HOME_LNG, lat, lng), 1)


@lru_cache(maxsize=4096)
def zip_latlng(zip_code: str) -> Optional[tuple[float, float]]:
    try:
        import zipcodes  # offline US zip database
    except ImportError:  # pragma: no cover
        return None
    z = (zip_code or "").strip()[:5]
    if not z.isdigit():
        return None
    hits = zipcodes.matching(z)
    if not hits:
        return None
    try:
        return float(hits[0]["lat"]), float(hits[0]["long"])
    except (KeyError, TypeError, ValueError):
        return None


@lru_cache(maxsize=1024)
def city_latlng(city: str, state: str) -> Optional[tuple[float, float]]:
    try:
        import zipcodes
    except ImportError:  # pragma: no cover
        return None
    if not city or not state:
        return None
    hits = zipcodes.filter_by(city=city.strip().title(), state=state.strip().upper())
    if not hits:
        return None
    try:
        return float(hits[0]["lat"]), float(hits[0]["long"])
    except (KeyError, TypeError, ValueError):
        return None


@lru_cache(maxsize=256)
def nearest_place(lat: float, lng: float, state: Optional[str] = "TX") -> Optional[tuple[str, str, str]]:
    """Reverse-geocode to the nearest US zip centroid -> (city, state, zip). Cheap, offline, approximate."""
    try:
        import zipcodes
    except ImportError:  # pragma: no cover
        return None
    cands = zipcodes.filter_by(state=state) if state else zipcodes.list_all()
    best, best_d = None, 1e9
    for z in cands:
        try:
            d = haversine_mi(lat, lng, float(z["lat"]), float(z["long"]))
        except (KeyError, TypeError, ValueError):
            continue
        if d < best_d:
            best, best_d = z, d
    if best is None or best_d > 60:
        return None
    return best["city"], best["state"], best["zip_code"]
