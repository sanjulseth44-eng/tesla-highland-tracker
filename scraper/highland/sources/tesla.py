"""Tesla used inventory (tesla.com/inventory/used/m3) within LOCAL_RADIUS_MI of HOME_ZIP.

Data comes from the same JSON endpoint the inventory page calls:
  GET https://www.tesla.com/inventory/api/v4/inventory-results?query=<url-encoded JSON>
robots.txt (checked 2026-09-02): no rule in the "*" group touches /inventory/ -- allowed.

Akamai fronts tesla.com and challenges most non-browser TLS fingerprints (HTTP 429 {"cpr_chlge":"true"}
or a 403 page). What worked in testing: curl_cffi impersonating iOS Safari, after first loading the
inventory HTML page once to pick up the bot-manager cookies. It is not 100% reliable, so fetch() walks a
ladder of fingerprints and gives up cleanly (SourceResult.ok=False) if every one is challenged; the
pipeline then keeps yesterday's Tesla listings and flags the source instead of marking cars sold.

Listing URL: https://www.tesla.com/m3/order/<VIN>?titleStatus=used  (Tesla's own VDP for a used car).
Location: the API gives the delivery centre ("VRL") id and coordinates but no name; the pipeline
reverse-geocodes the coordinates to the nearest Texas town for display.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any, Optional
from urllib.parse import quote

from ..config import HOME_LAT, HOME_LNG, HOME_ZIP, LOCAL_RADIUS_MI, MIN_YEAR
from ..geo import distance_from_home, nearest_place
from ..http import Http, HttpError
from ..models import RawListing, SourceResult
from .base import Source

log = logging.getLogger("highland.tesla")

INVENTORY_PAGE = f"https://www.tesla.com/inventory/used/m3?zip={HOME_ZIP}&range={LOCAL_RADIUS_MI}"
API_URL = "https://www.tesla.com/inventory/api/v4/inventory-results"
PAGE_SIZE = 50
# Tried in order; names not supported by the installed curl_cffi are skipped automatically.
IMPERSONATION_LADDER = [
    "safari_ios", "safari18_4_ios", "safari17_2_ios", "chrome_android", "chrome131_android",
    "safari", "safari18_0", "safari15_5", "chrome", "chrome131", "chrome124", "chrome110",
    "edge101", "edge99", "firefox133", "firefox135",
]
REQUIRED_KEYS = {"VIN", "Year", "InventoryPrice", "Odometer"}

# Tesla "VRL" (delivery location) ids seen for the Houston area, for nicer dealer labels.
KNOWN_VRL = {
    401027: "Tesla Houston-Southwest (Richmond/Sugar Land)",
    4411: "Tesla Houston-Southwest (Richmond/Sugar Land)",
}


def _query(offset: int) -> str:
    years = [str(y) for y in range(MIN_YEAR, datetime.now().year + 2)]
    q = {
        "query": {
            "model": "m3",
            "condition": "used",
            "options": {"Year": years},
            "arrangeby": "Price",
            "order": "asc",
            "market": "US",
            "language": "en",
            "super_region": "north america",
            "lng": HOME_LNG,
            "lat": HOME_LAT,
            "zip": HOME_ZIP,
            "range": LOCAL_RADIUS_MI,
        },
        "offset": offset,
        "count": PAGE_SIZE,
        "outsideOffset": 0,
        "outsideSearch": False,
    }
    return quote(json.dumps(q, separators=(",", ":")))


class TeslaSource(Source):
    key = "tesla"
    label = "Tesla (used)"
    kind = "local"
    homepage = INVENTORY_PAGE
    impersonate = "safari_ios"
    min_interval_s = 1.5

    def _get_page(self, http: Http, offset: int) -> dict[str, Any]:
        data = http.get_json(
            API_URL + "?query=" + _query(offset),
            headers={"Accept": "application/json, text/plain, */*", "Referer": INVENTORY_PAGE},
        )
        if not isinstance(data, dict) or "results" not in data:
            # Akamai's challenge comes back as JSON too: {"cpr_chlge":"true", ...}
            raise HttpError(f"unexpected response shape: {str(data)[:120]}", None, str(data))
        return data

    def _open_session(self) -> tuple[Optional[Http], list[str]]:
        """Try each fingerprint: warm up on the HTML page, then hit the API once."""
        notes: list[str] = []
        for imp in IMPERSONATION_LADDER:
            try:
                http = Http(impersonate=imp, min_interval=self.min_interval_s, max_retries=1)
            except Exception:  # fingerprint name unknown to this curl_cffi version
                continue
            try:
                try:
                    http.get(INVENTORY_PAGE, ok_statuses=(200, 403, 404))
                except HttpError as e:  # warm-up failures are not fatal
                    notes.append(f"{imp}: warm-up {e.status}")
                page = self._get_page(http, 0)
                if imp != IMPERSONATION_LADDER[0]:
                    notes.append(f"fell back to impersonate={imp}")
                self._first_page = page
                return http, notes
            except HttpError as e:
                notes.append(f"{imp}: {e.status or 'challenge'}")
                time.sleep(2)
        return None, notes

    def fetch(self) -> SourceResult:
        res = SourceResult(source=self.key, listings=[])
        self._first_page = None
        http, notes = self._open_session()
        res.notes.extend(notes)
        if http is None:
            res.ok = False
            res.error = "Tesla inventory API challenged every browser fingerprint (" + "; ".join(notes) + ")"
            return res
        seen: set[str] = set()
        offset = 0
        total: Optional[int] = None
        page = self._first_page
        while True:
            if page is None:
                try:
                    page = self._get_page(http, offset)
                except HttpError as e:
                    res.ok = False
                    res.error = f"{e} (status={e.status})"
                    return res
            res.pages_fetched += 1
            try:
                total = int(page.get("total_matches_found") or 0)
            except (TypeError, ValueError):
                total = 0
            results = page.get("results") or []
            if not isinstance(results, list):
                res.ok = False
                res.error = "results is not a list (markup changed)"
                return res
            for it in results:
                missing = REQUIRED_KEYS - set(it)
                if missing:
                    res.notes.append(f"item missing keys {sorted(missing)} (API change?)")
                    continue
                vin = (it.get("VIN") or "").upper()
                if not vin or vin in seen:
                    continue
                try:
                    year = int(it["Year"])
                    price = int(round(float(it["InventoryPrice"])))
                    mileage = int(it["Odometer"])
                except (TypeError, ValueError):
                    res.notes.append(f"unparseable numbers on {vin}")
                    continue
                if year < MIN_YEAR:
                    continue
                seen.add(vin)
                codes = it.get("TRIM") or []
                code = codes[0] if isinstance(codes, list) and codes else (codes if isinstance(codes, str) else "")
                dt = "AWD" if "AWD" in str(code).upper() else ("RWD" if "RWD" in str(code).upper() else None)
                vrl_list = it.get("vrlList") or []
                lat = lng = None
                vrl_id = it.get("Vrl")
                if vrl_list and isinstance(vrl_list[0], dict):
                    lat, lng = vrl_list[0].get("lat"), vrl_list[0].get("lon")
                    vrl_id = vrl_list[0].get("vrl", vrl_id)
                city = state = zipc = None
                if lat is not None and lng is not None:
                    place = nearest_place(float(lat), float(lng), "TX") or nearest_place(float(lat), float(lng), None)
                    if place:
                        city, state, zipc = place
                dealer = KNOWN_VRL.get(vrl_id) or (f"Tesla {city}" if city else "Tesla")
                fee = it.get("TransportationFee")
                paint = it.get("PAINT") or []
                interior = it.get("INTERIOR") or []
                res.listings.append(
                    RawListing(
                        source=self.key,
                        source_id=vin,
                        url=f"https://www.tesla.com/m3/order/{vin}?titleStatus=used",
                        vin=vin,
                        year=year,
                        price=price,
                        mileage=mileage,
                        trim_raw=(it.get("TrimName") or "").strip() or None,
                        drivetrain=dt,
                        dealer=dealer,
                        city=city,
                        state=state,
                        zip=zipc,
                        lat=float(lat) if lat is not None else None,
                        lng=float(lng) if lng is not None else None,
                        distance_mi=distance_from_home(float(lat), float(lng)) if lat is not None and lng is not None else None,
                        shipping_cost=float(fee) if fee is not None else None,
                        shipping_note="Tesla transport fee" if fee else "at Tesla delivery center",
                        exterior_color=(paint[0] if paint else None),
                        interior_color=(interior[0] if interior else None),
                        extra={
                            "trim_code": code,
                            "vrl": vrl_id,
                            "factory_gated": it.get("FactoryGatedDate"),
                            "autopilot": it.get("AUTOPILOT"),
                            "adl_opts": it.get("ADL_OPTS"),
                            "actual_range_mi": it.get("ActualRange"),
                            "vehicle_history": it.get("VehicleHistory"),
                            "is_demo": it.get("IsDemo"),
                            "battery_warranty_exp": it.get("WarrantyBatteryExpDate"),
                            "discount": it.get("Discount"),
                            "wheels": it.get("WHEELS"),
                            "option_codes": it.get("OptionCodeList"),
                            "ap_hardware": it.get("AP_HARDWARE_VERSION"),
                        },
                    )
                )
            offset += len(results)
            page = None
            if not results or offset >= total:
                break
            if res.pages_fetched >= 20:
                res.notes.append("stopped after 20 pages (safety cap)")
                break
        log.info("tesla: %d listings (%s total reported, %d pages)", len(res.listings), total, res.pages_fetched)
        return res


SOURCE = TeslaSource
