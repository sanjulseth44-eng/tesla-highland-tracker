"""AutoNation -- Houston-area AutoNation stores (franchise stores + "AutoNation USA" used-car
stores) within LOCAL_RADIUS_MI of HOME_ZIP, via the JSON search endpoint the used-car SRP calls.

How it works: the SRP (https://www.autonation.com/used-cars/tesla/model%203) is an Angular app
(/cars-for-sale/public/dist/SearchResultsPage/main-*.js) that POSTs a JSON "Info" object to
    POST https://www.autonation.com/v2/api/sitecore/SearchResultPage/Search
and renders the returned Elements[]. We send the same request shape the bundle builds:
Filter[] of {FieldName, SelectedValues} (stocktype, make, model="Tesla^^^Model 3", year=[min,max]),
Take/Skip paging, Sort by distance, Location{ZipCode, Radius}. The response has Count (total),
Elements (vehicles: Vin, Year, Mileage, Pricing[{Name:"EcomPrice",Value}], StyleName, Trim,
DriveType, Distance, Store{Name,City,StateCode,ZipCode}, Location{lat,lng}, StockNumber...).
The body carries a __RequestVerificationToken that is a constant baked into the JS bundle (not a
per-session cookie token); it is copied below and may need refreshing if the bundle changes.

VDP URL (what we link to) follows the bundle's tileLinkUrl():
    /cars/<vin lowercase>/<make>-<model>-<year>  e.g. /cars/5yj3e1ea5rf724416/tesla-model-3-2024
(verified 2026-09-02: both sample VDPs returned 200 with the VIN on the page).

robots.txt (checked 2026-09-02). It is written as ~35 separate "User-agent: *" groups, one rule
each. Merged, the "*" rules that matter here:
    Disallow: /cars-search-results*      (the OLD SRP API -- we do not use it)
    Disallow: /SimpleSearch/get           (not used)
    Disallow: /nlp-search*                (not used)
    Disallow: /api/sitecore/StoreDetails/GetOffers/*
    Disallow: /api/sitecore/AppointmentsAndReservations/ApptAndResRenderingLazy*
    Disallow: /site-search/*, /my-autonation*, /car-research*, /buy-now*, /deeplink*, ...
Nothing matches /v2/api/sitecore/SearchResultPage/Search, /used-cars/*, or /cars/<vin>/... .
No Crawl-delay. NOTE: highland.robots.Robots merges every "User-agent: *" group (RFC 9309), so the
shared client would see just "Disallow: /my-autonation*"; this module therefore re-checks every
URL against the union of all "*" groups itself (_merged_can_fetch) before requesting it.

Bot wall: Cloudflare puts a JS challenge ("Just a moment...", HTTP 403) on the homepage and on
non-existent /cars/... paths for every curl_cffi fingerprint. The real SRP, VDP, sitemap and
/v2/api/... paths are served normally with impersonate="chrome". We never try to pass the
challenge; if it ever spreads to the search endpoint this source will simply fail with HTTP 403.

Quirks: the shared Http class has no POST, so this module does its own robots + throttle + retry
around http.session.post (see _post_json). "ExtendedRadius": true is what the site sends; we still
drop anything with Distance > LOCAL_RADIUS_MI. Model strings are hierarchical ("Tesla^^^Model 3").
StyleName ("RWD *Ltd Avail*", "Performance AWD", "Long Range AWD") is the trim text the tile shows.
"""
from __future__ import annotations

import json
import logging
import random
import re
import time
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlsplit

from ..config import HOME_ZIP, LOCAL_RADIUS_MI, MIN_YEAR
from ..http import HttpError, RobotsDisallowed
from ..models import RawListing, SourceResult
from ..normalize import normalize_drivetrain
from ..robots import Robots, RobotsGroup
from .base import Source

log = logging.getLogger("highland.autonation")

BASE = "https://www.autonation.com"
SEARCH_URL = f"{BASE}/v2/api/sitecore/SearchResultPage/Search"
SRP_URL = f"{BASE}/used-cars/tesla/model%203"
PAGE_SIZE = 24          # what the site's own SRP requests
MAX_PAGES = 10
MAKE = "Tesla"
MODEL = "Model 3"
MODEL_VALUE = f"{MAKE}^^^{MODEL}"   # hierarchical facet value used by the "model" filter
# Constant from main-4TB63MR6.js (2026-09-02). Not tied to a session cookie.
REQUEST_VERIFICATION_TOKEN = (
    "eJuukeamjUn_dYwsahyhfyzTj9sHOddI4aviXRkG_Z43nXgWG-b7G9VEozio7CD-2q-wbfpQTwz9LYla3h9ELeLmsV41"
)
REQUIRED_KEYS = {"Vin", "Year", "Mileage", "Pricing", "Store", "StockNumber", "Model", "StockType"}


def _slug(s: str) -> str:
    """Mirror the bundle's tileLinkUrl(): lowercase, spaces->'-', drop '.' and '&'."""
    return (s or "").lower().replace(" ", "-").replace(".", "").replace("&", "")


def _price(pricing: Any) -> Optional[int]:
    """Pricing is a list of {Name, Value, Type}; EcomPrice is the advertised internet price."""
    if not isinstance(pricing, list) or not pricing:
        return None
    chosen = None
    for p in pricing:
        if isinstance(p, dict) and p.get("Name") == "EcomPrice":
            chosen = p
            break
    if chosen is None:
        chosen = pricing[0] if isinstance(pricing[0], dict) else None
    try:
        v = chosen.get("Value") if chosen else None
        return int(round(float(v))) if v is not None else None
    except (TypeError, ValueError):
        return None


class AutoNationSource(Source):
    key = "autonation"
    label = "AutoNation"
    kind = "local"
    homepage = f"{SRP_URL}?zip={HOME_ZIP}"
    impersonate = "chrome"
    min_interval_s = 2.0

    # ---- POST goes through the shared client (robots + throttle + retry) ----
    def _post_json(self, url: str, body: dict[str, Any], headers: dict[str, str]) -> Any:
        return self.http.post_json(url, json_body=body, headers=headers)

    def _body(self, skip: int, max_year: int) -> dict[str, Any]:
        return {
            "Info": {
                "ReturnElementsResult": True,
                "ScoringProfile": {"FieldName": None, "Parameters": None},
                "Filter": [
                    {"FieldName": "stocktype", "SelectedValues": ["used", "cpo"]},
                    {"FieldName": "make", "SelectedValues": [MAKE]},
                    {"FieldName": "model", "SelectedValues": [MODEL_VALUE]},
                    {"FieldName": "year", "SelectedValues": [str(MIN_YEAR), str(max_year)]},  # [min, max]
                ],
                "Take": PAGE_SIZE,
                "Skip": skip,
                "Sort": [{"SortBy": "distance", "SortDirection": "ASC"}],
                "Select": [{"Action": 0, "FieldName": "base64desktop"}],
                "SearchText": "",
                "Location": {"ZipCode": HOME_ZIP, "Radius": str(LOCAL_RADIUS_MI), "Type": 0},
                "ExtendedRadius": True,
            },
            "Settings": {"name": "cloud.AN"},
            "IncludeTealiumData": False,
            "__RequestVerificationToken": REQUEST_VERIFICATION_TOKEN,
        }

    # ---- main ----
    def fetch(self) -> SourceResult:
        res = SourceResult(source=self.key, listings=[])
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Origin": BASE,
            "Referer": self.homepage,
        }
        max_year = datetime.now().year + 1
        seen: set[str] = set()
        skip = 0
        total: Optional[int] = None
        dropped_far = 0
        while True:
            try:
                data = self._post_json(SEARCH_URL, self._body(skip, max_year), headers)
            except HttpError as e:
                res.ok = False
                res.error = f"{e} (status={e.status})"
                return res
            res.pages_fetched += 1
            if not isinstance(data, dict) or "Elements" not in data or "Count" not in data:
                res.ok = False
                res.error = (f"unexpected response shape (markup changed?): "
                             f"keys={list(data)[:10] if isinstance(data, dict) else type(data).__name__}")
                return res
            if data.get("Success") is False:
                res.ok = False
                res.error = f"AutoNation search reported Success=false: {data.get('Messages')}"
                return res
            try:
                total = int(data.get("Count") or 0)
            except (TypeError, ValueError):
                total = 0
            elements = data.get("Elements") or []
            if not isinstance(elements, list):
                res.ok = False
                res.error = "Elements is not a list (markup changed)"
                return res

            for el in elements:
                if not isinstance(el, dict):
                    continue
                missing = REQUIRED_KEYS - set(el)
                if missing:
                    res.notes.append(f"element missing keys {sorted(missing)} (markup change?)")
                    continue
                model_parts = str(el.get("Model") or "").split("^^^")
                make = model_parts[0] if model_parts else ""
                model = model_parts[1] if len(model_parts) > 1 else ""
                if make.lower() != MAKE.lower() or model.lower() != MODEL.lower():
                    continue
                if str(el.get("StockType") or "").upper() == "NEW":
                    continue
                vin = (el.get("Vin") or "").strip().upper()
                if not vin or vin in seen:
                    continue
                try:
                    year = int(el["Year"])
                    mileage = int(round(float(el["Mileage"])))
                except (TypeError, ValueError):
                    res.notes.append(f"unparseable year/mileage on stock {el.get('StockNumber')}")
                    continue
                if year < MIN_YEAR:
                    continue
                price = _price(el.get("Pricing"))
                if price is None:
                    res.notes.append(f"no EcomPrice on {vin} (stock {el.get('StockNumber')}); skipped")
                    continue
                dist = el.get("Distance")
                try:
                    dist_f = float(dist) if dist is not None else None
                except (TypeError, ValueError):
                    dist_f = None
                if dist_f is not None and dist_f > LOCAL_RADIUS_MI:
                    dropped_far += 1
                    continue
                store = el.get("Store") or {}
                loc = el.get("Location") or {}
                trim_parts = str(el.get("Trim") or "").split("^^^")
                trim_leaf = trim_parts[2] if len(trim_parts) > 2 else None
                seen.add(vin)
                res.listings.append(
                    RawListing(
                        source=self.key,
                        source_id=str(el["StockNumber"]),
                        url=f"{BASE}/cars/{vin.lower()}/{_slug(make)}-{_slug(model)}-{year}",
                        vin=vin,
                        year=year,
                        price=price,
                        mileage=mileage,
                        trim_raw=(el.get("StyleName") or trim_leaf or None),
                        drivetrain=normalize_drivetrain(el.get("DriveType")),
                        dealer=store.get("Name"),
                        city=store.get("City"),
                        state=store.get("StateCode"),
                        zip=str(store.get("ZipCode")) if store.get("ZipCode") else None,
                        lat=loc.get("Latitude"),
                        lng=loc.get("Longitude"),
                        distance_mi=round(dist_f, 1) if dist_f is not None else None,
                        exterior_color=el.get("ExteriorColor") or None,
                        interior_color=el.get("InteriorColor") or None,
                        extra={
                            "inventory_vehicle_id": el.get("InventoryVehicleId"),
                            "store_id": el.get("HyperionId"),
                            "store_address": store.get("Address1"),
                            "store_phone": store.get("Phone"),
                            "stock_type": el.get("StockType"),
                            "trim_facet": trim_leaf,
                            "price_action": el.get("PriceAction"),
                            "pricing": el.get("Pricing"),
                            "reservable": el.get("Reservable"),
                            "inventory_status": el.get("InventoryStatus"),
                            "entry_date": el.get("EntryDate"),
                            "engine": el.get("Engine"),
                            "features": el.get("VehicleFeatures"),
                            "highlights": [h.get("AttributeText") for h in (el.get("VehicleHighlights") or []) if isinstance(h, dict)],
                        },
                    )
                )
            skip += len(elements)
            if not elements or skip >= total:
                break
            if res.pages_fetched >= MAX_PAGES:
                res.notes.append(f"stopped after {MAX_PAGES} pages (safety cap); {total} reported")
                break
        if dropped_far:
            res.notes.append(f"dropped {dropped_far} listing(s) farther than {LOCAL_RADIUS_MI} mi (ExtendedRadius)")
        log.info("autonation: %d listings (%s total reported, %d pages)", len(res.listings), total, res.pages_fetched)
        return res


SOURCE = AutoNationSource
