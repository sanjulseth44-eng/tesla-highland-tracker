"""Carvana -- nationwide (delivered) inventory parsed from the server-rendered search page
https://www.carvana.com/cars/tesla-model-3. The SRP is a Next.js App Router page whose React Server
Component payload (streamed as <script>self.__next_f.push([1,"..."])</script> chunks) embeds the
24 results of the requested page, so no XHR/JSON endpoint is needed.

robots.txt (checked 2026-09-02, "User-agent: *" group, 19 rules, no Crawl-delay):
  Disallow: /search/*           Disallow: /advanced-search/*   Disallow: /browse/*
  Disallow: /inventory/         Disallow: /cars/filters*       Disallow: /purchase/
  Disallow: /carvanalocations   Disallow: /search/getspinnerdatalarge   Disallow: /drive/  (+ account/admin/...)
  - /cars/tesla-model-3 and its ?sortBy=...&page=N variants: ALLOWED (no rule matches).
  - /vehicle/<vehicleId> (the VDP we link to): ALLOWED. Verified 2 URLs return 200 with
    "<year> Tesla Model 3 | Carvana" titles.
  - Every filter URL (/cars/filters/<encoded filters>) and the JSON search APIs (/search/*, /inventory/)
    are disallowed, so we never request them; ?year=... on the vanity path is ignored by the server.

Endpoint: GET /cars/tesla-model-3?sortBy=NewestYear&page=N   (pageSize 24, ~1.3 MB HTML per page).
  ?sortBy=NewestYear IS honored (echoed in forAppliedFiltersContext.sortBy), so pages are walked
  newest-year-first and the walk stops at the first page that contains a pre-MIN_YEAR car. If the echo
  ever disappears we fall back to walking every page (up to MAX_PAGES) and simply skip old cars.
Payload path: forInventoryContext.inventoryData = {inventory: {pagination: {currentPage, pageSize,
  totalMatchedInventory, totalMatchedPages}, vehicles: [{stockNumber, vehicleId, vin, year, make,
  parentModel, model, trim, kbbTrim, mileage, price: {total, msrp, kbbValue, transportCost, ...}, color,
  interiorColor, transportCost, locationId, vehiclePurchaseType, isPurchasePending, isOnDemand, vdpSlug,
  priceUpdateDate, factoryUpgrades, ...}]}, userDeliveryInfo: {city, state, zip5, ...}}

Quirks:
  - Carvana delivers nationally and the SRP does not say where a car physically sits (locationId is an
    opaque hub id; /carvanalocations is disallowed), so every listing is emitted with kind="local",
    distance_mi=None and no lat/lng, per the project convention for Carvana.
  - price.transportCost is the delivery fee for the *IP-geolocated* location of the machine running the
    scraper (userDeliveryInfo.zip5), not for 77479 -- the delivery zip can only be changed through the
    disallowed search APIs / account flows. shipping_cost is therefore left None; the geo-IP quote and the
    zip it was quoted for are kept in extra for reference.
  - Cloudflare fronts the site; curl_cffi Chrome impersonation gets 200s.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from ..config import HOME_ZIP, MIN_YEAR
from ..http import HttpError
from ..models import RawListing, SourceResult
from .base import Source

log = logging.getLogger("highland.carvana")

BASE = "https://www.carvana.com"
SEARCH_URL = f"{BASE}/cars/tesla-model-3"
SORT_BY = "NewestYear"
MAX_PAGES = 40
_CHUNK_RE = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', re.S)
REQUIRED_KEYS = {"stockNumber", "vehicleId", "vin", "year", "mileage", "price", "make"}


def _int(s: Any) -> Optional[int]:
    if s is None or isinstance(s, bool):
        return None
    if isinstance(s, (int, float)):
        return int(round(s))
    m = re.sub(r"[^\d]", "", str(s))
    return int(m) if m else None


def _rsc_payload(html: str) -> str:
    """Join the JS-string chunks Next.js streams into self.__next_f into one text blob."""
    chunks = _CHUNK_RE.findall(html)
    if not chunks:
        raise ValueError("no __next_f RSC chunks on SRP (markup changed or bot wall)")
    out: list[str] = []
    for c in chunks:
        try:
            out.append(json.loads('"' + c + '"'))   # chunks are JSON-escaped JS string literals
        except json.JSONDecodeError:
            continue
    return "".join(out)


def _json_after(blob: str, key: str, start: int = 0) -> tuple[Any, int]:
    """Decode the JSON value that follows '"<key>":' at or after `start`. Returns (value, index)."""
    needle = f'"{key}":'
    i = blob.find(needle, start)
    if i < 0:
        raise ValueError(f"'{key}' not in RSC payload (markup changed)")
    try:
        obj, _ = json.JSONDecoder().raw_decode(blob, i + len(needle))
    except json.JSONDecodeError as e:
        raise ValueError(f"'{key}' value is not JSON ({e}); markup changed")
    return obj, i


class CarvanaSource(Source):
    key = "carvana"
    label = "Carvana"
    kind = "local"      # Carvana delivers nationally; see module docstring
    homepage = f"{SEARCH_URL}?sortBy={SORT_BY}"
    impersonate = "chrome"
    min_interval_s = 2.5

    # ---- page fetch / parse ----
    def _fetch_page(self, page: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Return (inventory, applied_filters, user_delivery_info) for one SRP page.
        Raises HttpError / ValueError."""
        html = self.http.get_text(
            SEARCH_URL,
            params={"sortBy": SORT_BY, "page": page},
            headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                     "Referer": BASE + "/"},
        )
        blob = _rsc_payload(html)
        _, ctx_idx = _json_after(blob, "forInventoryContext")
        inv_data, _ = _json_after(blob, "inventoryData", ctx_idx)
        if not isinstance(inv_data, dict) or not isinstance(inv_data.get("inventory"), dict):
            raise ValueError("inventoryData shape changed (no .inventory dict)")
        inventory = inv_data["inventory"]
        if not isinstance(inventory.get("vehicles"), list) or not isinstance(inventory.get("pagination"), dict):
            raise ValueError(f"inventory shape changed: keys={sorted(inventory)[:12]}")
        try:
            applied, _ = _json_after(blob, "forAppliedFiltersContext")
        except ValueError:
            applied = {}
        udi = inv_data.get("userDeliveryInfo") if isinstance(inv_data.get("userDeliveryInfo"), dict) else {}
        return inventory, applied if isinstance(applied, dict) else {}, udi

    # ---- main ----
    def fetch(self) -> SourceResult:
        res = SourceResult(source=self.key, listings=[])
        seen: set[str] = set()
        page = 1
        total_pages: Optional[int] = None
        total_count: Optional[int] = None
        sorted_ok = True
        quote_zip: Optional[str] = None
        skipped_unavailable = 0
        skipped_old = 0
        while True:
            try:
                inventory, applied, udi = self._fetch_page(page)
            except HttpError as e:
                res.ok = False
                res.error = f"{e} (status={e.status})"
                return res
            except ValueError as e:
                res.ok = False
                res.error = str(e)
                return res
            res.pages_fetched += 1
            pag = inventory["pagination"]
            vehicles = inventory["vehicles"]
            total_pages = _int(pag.get("totalMatchedPages"))
            total_count = _int(pag.get("totalMatchedInventory"))
            cur = _int(pag.get("currentPage"))
            if cur is not None and cur != page:
                res.notes.append(f"asked for page {page} but got page {cur}; stopping")
                break
            if page == 1:
                if applied.get("sortBy") != SORT_BY:
                    sorted_ok = False
                    res.notes.append(f"sortBy={SORT_BY} not echoed (got {applied.get('sortBy')!r}); walking every page")
                if udi:
                    quote_zip = str(udi.get("zip5") or "") or None
                    res.notes.append(
                        f"transportCost is quoted for the scraper's geo-IP location "
                        f"({udi.get('city')}, {udi.get('state')} {quote_zip}), not {HOME_ZIP}; shipping_cost left None")
            saw_old = False
            for v in vehicles:
                if not isinstance(v, dict):
                    continue
                missing = REQUIRED_KEYS - set(v)
                if missing:
                    res.notes.append(f"vehicle missing keys {sorted(missing)} (markup change?)")
                    continue
                if (v.get("make") or "").strip().lower() != "tesla":
                    continue
                model = (v.get("parentModel") or v.get("model") or "").strip().lower()
                if model != "model 3":
                    continue
                year = _int(v.get("year"))
                if year is None:
                    continue
                if year < MIN_YEAR:
                    saw_old = True
                    skipped_old += 1
                    continue
                vin = (v.get("vin") or "").strip().upper()
                if not vin or vin in seen:
                    continue
                if (v.get("vehiclePurchaseType") or "Purchasable") != "Purchasable" or v.get("isPurchasePending"):
                    skipped_unavailable += 1
                    continue
                price_obj = v.get("price") if isinstance(v.get("price"), dict) else {}
                price = _int(price_obj.get("total"))
                mileage = _int(v.get("mileage"))
                if price is None:
                    res.notes.append(f"stock {v.get('stockNumber')} ({vin}) has no price.total; skipped")
                    continue
                if mileage is None:
                    res.notes.append(f"stock {v.get('stockNumber')} ({vin}) has no mileage; skipped")
                    continue
                seen.add(vin)
                transport = v.get("transportCost", price_obj.get("transportCost"))
                upgrades = (v.get("factoryUpgrades") or {}).get("packagesAndOptions") or []
                res.listings.append(
                    RawListing(
                        source=self.key,
                        source_id=str(v["stockNumber"]),
                        url=f"{BASE}/vehicle/{v['vehicleId']}",
                        vin=vin,
                        year=year,
                        price=price,
                        mileage=mileage,
                        trim_raw=(v.get("trim") or None),
                        drivetrain=None,          # not on the SRP; the pipeline reads the VIN motor code
                        dealer="Carvana",
                        city=None,
                        state=None,
                        zip=None,
                        distance_mi=None,
                        shipping_cost=None,
                        shipping_note=f"Carvana delivery to {HOME_ZIP} (fee quoted at checkout)",
                        exterior_color=v.get("color") or None,
                        interior_color=v.get("interiorColor") or None,
                        extra={
                            "vehicle_id": v.get("vehicleId"),
                            "kbb_trim": v.get("kbbTrim"),
                            "kbb_value": price_obj.get("kbbValue"),
                            "msrp_carvana": price_obj.get("msrp"),
                            "market_adjustment": price_obj.get("marketAdjustment"),
                            "price_update_date": v.get("priceUpdateDate"),
                            "transport_cost_geoip": transport,
                            "transport_quote_zip": quote_zip,
                            "location_id": v.get("locationId"),
                            "fulfillment_type": v.get("fulfillmentType"),
                            "is_on_demand": v.get("isOnDemand"),
                            "vdp_slug": v.get("vdpSlug"),
                            "factory_upgrades": [u.get("displayName") or u.get("name") for u in upgrades if isinstance(u, dict)],
                        },
                    )
                )
            if not vehicles:
                break
            if sorted_ok and saw_old:
                break   # newest-first: everything after this page is older than MIN_YEAR
            if total_pages is not None and page >= total_pages:
                break
            if res.pages_fetched >= MAX_PAGES:
                res.notes.append(f"stopped after {MAX_PAGES} pages (safety cap); {total_pages} pages reported")
                break
            page += 1
        if skipped_unavailable:
            res.notes.append(f"skipped {skipped_unavailable} purchase-pending / non-purchasable listing(s)")
        log.info("carvana: %d listings (%s Model 3s of all years reported, %d pages, %d pre-%d skipped)",
                 len(res.listings), total_count, res.pages_fetched, skipped_old, MIN_YEAR)
        return res


SOURCE = CarvanaSource
