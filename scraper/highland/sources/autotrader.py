"""Autotrader -- aggregates Houston-area franchise and independent dealers (plus Autotrader's own
"Private Seller Exchange"). Searched within LOCAL_RADIUS_MI of HOME_ZIP.

How it works: the search-results page (SRP) is a Next.js app that embeds its whole Redux state in
<script id="__NEXT_DATA__">. props.pageProps.__eggsState.inventory[<id>] holds every listing on the
page (vin, year, mileage, pricingDetail, trim, driveType, ownerId...) and .owners[<ownerId>] holds
the dealer (name, address, lat/lng). We parse that blob instead of calling the site's XHR endpoints.

robots.txt (checked 2026-09-02, "User-agent: *" group):
  - /cars-for-sale/tesla/model-3/sugar-land-tx?... (SRP) is allowed -- no rule matches it.
  - /cars-for-sale/vehicle/<id> (VDP, what we link to) is allowed -- no rule matches it.
  - "Disallow: /rest/frontline/srp/single/aggregate" is the only SRP data endpoint that is blocked;
    we never call it (or any /rest/ endpoint). "Disallow: /rest/" and "Disallow: /cars-for-sale/all-cars"
    exist only in the AdsBot-Google group and do not apply to us. No Crawl-delay.
Akamai fronts the site; curl_cffi's Chrome impersonation gets 200s with default python TLS blocked.

Paging: numRecords (page size) + firstRecord (0-based offset); srp_results.count is the total.
Price: pricingDetail.displayPrice is the advertised price (salePrice/preFeeDerivedPrice subtract the
doc fee and are not what the dealer shows). Listings with no displayPrice are "Contact Dealer For
Price" and are skipped. Autotrader pads a radius search with "market extension" listings from
long-haul-delivery dealers hundreds of miles away; those are dropped by distance.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from ..config import HOME_ZIP, LOCAL_RADIUS_MI, MIN_YEAR
from ..http import HttpError
from ..models import RawListing, SourceResult
from ..normalize import normalize_drivetrain
from .base import Source

log = logging.getLogger("highland.autotrader")

BASE = "https://www.autotrader.com"
# The city slug in the path is cosmetic (Autotrader resolves the search from ?zip=); it matches HOME_ZIP.
SEARCH_URL = f"{BASE}/cars-for-sale/tesla/model-3/sugar-land-tx"
PAGE_SIZE = 100
MAX_PAGES = 10
MAKE_CODE = "TESLA"
MODEL_CODE = "TESMOD3"
_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
REQUIRED_KEYS = {"id", "vin", "year", "mileage", "pricingDetail", "ownerId"}


def _int(s: Any) -> Optional[int]:
    """'16,727' / 16727 / 16727.0 -> 16727; anything else -> None."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return int(round(s))
    m = re.sub(r"[^\d]", "", str(s))
    return int(m) if m else None


class AutotraderSource(Source):
    key = "autotrader"
    label = "Autotrader"
    kind = "local"
    homepage = (f"{SEARCH_URL}?zip={HOME_ZIP}&searchRadius={LOCAL_RADIUS_MI}"
                f"&startYear={MIN_YEAR}&listingType=USED")
    impersonate = "chrome"
    min_interval_s = 2.0

    # ---- page fetch / parse ----
    def _fetch_page(self, first_record: int) -> dict[str, Any]:
        """Return the __eggsState dict for one SRP page. Raises HttpError / ValueError."""
        params = {
            "zip": HOME_ZIP,
            "searchRadius": LOCAL_RADIUS_MI,
            "startYear": MIN_YEAR,
            "listingType": "USED",
            "numRecords": PAGE_SIZE,
            "firstRecord": first_record,
        }
        html = self.http.get_text(
            SEARCH_URL,
            params=params,
            headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                     "Referer": BASE + "/"},
        )
        m = _NEXT_DATA_RE.search(html)
        if not m:
            raise ValueError("no __NEXT_DATA__ script on SRP (markup changed or bot wall)")
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError as e:
            raise ValueError(f"__NEXT_DATA__ is not JSON: {e}")
        try:
            state = data["props"]["pageProps"]["__eggsState"]
        except (KeyError, TypeError):
            raise ValueError("__NEXT_DATA__ shape changed: no props.pageProps.__eggsState")
        if not isinstance(state.get("inventory"), dict) or not isinstance(state.get("srp_results"), dict):
            raise ValueError(f"__eggsState shape changed: keys={sorted(state)[:15]}")
        if state["srp_results"].get("fetchError"):
            raise ValueError("Autotrader reported srp_results.fetchError")
        return state

    # ---- main ----
    def fetch(self) -> SourceResult:
        res = SourceResult(source=self.key, listings=[])
        seen: set[str] = set()
        first = 0
        total: Optional[int] = None
        dropped_far = 0
        dropped_noprice = 0
        while True:
            try:
                state = self._fetch_page(first)
            except HttpError as e:
                res.ok = False
                res.error = f"{e} (status={e.status})"
                return res
            except ValueError as e:
                res.ok = False
                res.error = str(e)
                return res
            res.pages_fetched += 1
            results = state["srp_results"]
            inventory: dict[str, Any] = state["inventory"]
            owners: dict[str, Any] = state.get("owners") or {}
            try:
                total = int(results.get("count") or 0)
            except (TypeError, ValueError):
                total = 0
            ids = results.get("activeResults") or []
            if not isinstance(ids, list):
                res.ok = False
                res.error = "srp_results.activeResults is not a list (markup changed)"
                return res

            for lid in ids:
                it = inventory.get(str(lid))
                if not isinstance(it, dict):
                    res.notes.append(f"listing {lid} in activeResults but not in inventory")
                    continue
                missing = REQUIRED_KEYS - set(it)
                if missing:
                    res.notes.append(f"listing {lid} missing keys {sorted(missing)} (markup change?)")
                    continue
                if (it.get("makeCode") or (it.get("make") or {}).get("code")) != MAKE_CODE:
                    continue
                if (it.get("modelCode") or (it.get("model") or {}).get("code")) != MODEL_CODE:
                    continue
                if (it.get("listingType") or "USED").upper() == "NEW":
                    continue
                vin = (it.get("vin") or "").strip().upper()
                if not vin or vin in seen:
                    continue
                year = _int(it.get("year"))
                if not year or year < MIN_YEAR:
                    continue
                mileage = _int((it.get("mileage") or {}).get("value") if isinstance(it.get("mileage"), dict) else it.get("mileage"))
                pd = it.get("pricingDetail") or {}
                price = _int(pd.get("displayPrice"))
                owner = owners.get(str(it.get("ownerId"))) or {}
                addr = ((owner.get("location") or {}).get("address")) or {}
                dealer = it.get("ownerName") or owner.get("name")
                mext = it.get("marketExtension") or {}
                dist = mext.get("distance")
                if dist is None:
                    dist = owner.get("distanceFromSearch")
                try:
                    dist_f = float(dist) if dist is not None else None
                except (TypeError, ValueError):
                    dist_f = None
                if dist_f is not None and dist_f > LOCAL_RADIUS_MI:
                    dropped_far += 1   # market-extension / long-haul listing outside the radius
                    continue
                if price is None:
                    dropped_noprice += 1
                    log.debug("autotrader: %s %s at %s has no advertised price; skipped", lid, vin, dealer)
                    continue
                if mileage is None:
                    res.notes.append(f"listing {lid} ({vin}) has unparseable mileage {it.get('mileage')!r}; skipped")
                    continue
                seen.add(vin)
                trim = it.get("trim")
                trim_raw = trim.get("name") if isinstance(trim, dict) else (trim if isinstance(trim, str) else None)
                dt = it.get("driveType")
                dt_name = dt.get("name") if isinstance(dt, dict) else dt
                color = it.get("color") or {}
                batt = ((it.get("electricComponentInfo") or {}).get("batteryDegradationInfo")) or {}
                res.listings.append(
                    RawListing(
                        source=self.key,
                        source_id=str(it["id"]),
                        url=f"{BASE}/cars-for-sale/vehicle/{it['id']}",
                        vin=vin,
                        year=year,
                        price=price,
                        mileage=mileage,
                        trim_raw=trim_raw or None,
                        drivetrain=normalize_drivetrain(dt_name),
                        dealer=dealer,
                        city=addr.get("city"),
                        state=addr.get("state"),
                        zip=str(addr["zip"]) if addr.get("zip") else None,
                        lat=addr.get("latitude"),
                        lng=addr.get("longitude"),
                        distance_mi=dist_f,
                        exterior_color=color.get("exteriorColor") if isinstance(color, dict) else None,
                        interior_color=None,   # only on the VDP, which we do not fetch
                        extra={
                            "stock_id": it.get("stockId"),
                            "owner_id": it.get("ownerId"),
                            "private_seller": owner.get("privateSeller"),
                            "listing_type": it.get("listingType"),
                            "days_on_site": it.get("daysOnSite"),
                            "is_reduced_price": it.get("isReducedPrice"),
                            "is_newly_listed": it.get("isNewlyListed"),
                            "dealer_fees_total": pd.get("dealerFeesTotal"),
                            "kbb_fair_price": pd.get("kbbFppAmount"),
                            "kbb_fair_price_delta": pd.get("kbbFppDelta"),
                            "ev_range_mi": it.get("electricVehicleRange"),
                            "battery_health_pct": batt.get("healthRating"),
                            "vhr_preview": it.get("vhrPreview"),
                            "market_extension": mext.get("isMarketExtListing"),
                        },
                    )
                )
            first += len(ids)
            if not ids or first >= total:
                break
            if res.pages_fetched >= MAX_PAGES:
                res.notes.append(f"stopped after {MAX_PAGES} pages (safety cap); {total} reported")
                break
        if dropped_far:
            res.notes.append(f"dropped {dropped_far} market-extension listing(s) farther than {LOCAL_RADIUS_MI} mi")
        if dropped_noprice:
            res.notes.append(f"skipped {dropped_noprice} listing(s) with no advertised price (Contact Dealer)")
        log.info("autotrader: %d listings (%s total reported, %d pages)", len(res.listings), total, res.pages_fetched)
        return res


SOURCE = AutotraderSource
