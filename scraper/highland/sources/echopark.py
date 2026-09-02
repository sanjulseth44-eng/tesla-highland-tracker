"""EchoPark Automotive -- the two Houston stores (Houston Southwest, Stafford 77477, ~7 mi;
Houston (North), 77090, ~35 mi) via the server-rendered used-car search page.

How it works: https://www.echopark.com/used-cars/tesla/model-3 is a Sitecore JSS / Vue app whose
SSR HTML embeds the whole Pinia store in <script type="application/json" id="__STORE__">.
store.vehicleSearch.srpVehiclesData = {resultCount, pages, currentPage, items[]} holds the page of
vehicles (year, make, model, trim, modelNumber, vin, miles, stockNumber, dealership (dealer id),
sellingPrice, basePrice, feeBreakdown, originalPrice, url "/car/<VIN>", shippable, distanceToUser,
inventoryStatus ...) and store.common.dealerships[] lists every store with zip, city/state,
location{latitude,longitude} and distance from the search zip. Query string (from the bundle's
URL builder): radius=<mi>, page=<0-based>, take=<n>, sortby=distance&sortdir=asc.

Zip: the SSR ignores ?zip= and geolocates the request IP unless the cookie
ep_selectedZipcode=<zip> (+ ep_zipstatus=ManualEntry) is present -- the same cookie the site sets
when a visitor types a zip. We send it and verify common.zipCode == HOME_ZIP on every page.

robots.txt (checked 2026-09-02, "User-agent: *" group):
    Allow: /used-cars/*
    Disallow: /checkout/*  /used-cars1  /used-cars2  /used-cars1/*  /used-cars2/*  /tactical-fleet
    Disallow: */car-offer?gen=1   */trade-offer-confirm?gen=1
No rule matches /used-cars/tesla/model-3?... (explicitly allowed) or /car/<VIN> (the VDP we link
to; verified 2026-09-02 with GET -> 200). No Crawl-delay.

Why not the JSON API: the SPA also calls /api/vehicle-inventory-search and /api/dealership-search
(robots-allowed). They answered once and then returned 403 "Unauthorized" / 429 on the next calls
(Akamai Bot Manager sits in front of /api/*), so the SSR page -- which stayed stable -- is used.
The HTML is ~450 KB per page; a 100-mile radius search rarely needs more than one page.

Price: sellingPrice is the number EchoPark advertises on the tile and VDP; it INCLUDES the $499
document fee ("priceBreakdown": "$36,497 + $499 Document fee"). extra.base_price / extra.doc_fee
carry the split. Drivetrain and colors are not on the SRP; modelNumber (e.g. MODEL3LR) is kept in
extra. "shippable" items from far-away stores can appear when ship-to-store is on; anything with
distanceToUser > LOCAL_RADIUS_MI is dropped.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from ..config import HOME_ZIP, LOCAL_RADIUS_MI, MIN_YEAR
from ..http import HttpError
from ..models import RawListing, SourceResult
from .base import Source

log = logging.getLogger("highland.echopark")

BASE = "https://www.echopark.com"
SRP_URL = f"{BASE}/used-cars/tesla/model-3"
PAGE_SIZE = 24
MAX_PAGES = 10
MAKE = "Tesla"
MODEL = "Model 3"
_STORE_RE = re.compile(r'<script type="application/json" id="__STORE__">(.*?)</script>', re.S)
REQUIRED_KEYS = {"vin", "year", "make", "model", "miles", "sellingPrice", "dealership", "url", "stockNumber"}


def _int(v: Any) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(round(v))
    m = re.sub(r"[^\d]", "", str(v))
    return int(m) if m else None


class EchoParkSource(Source):
    key = "echopark"
    label = "EchoPark"
    kind = "local"
    homepage = f"{SRP_URL}?radius={LOCAL_RADIUS_MI}"
    impersonate = "chrome"
    min_interval_s = 2.5

    def _fetch_page(self, page: int) -> dict[str, Any]:
        """Return the __STORE__ dict for one SRP page. Raises HttpError / ValueError."""
        params = {"radius": LOCAL_RADIUS_MI, "page": page, "take": PAGE_SIZE, "sortby": "distance", "sortdir": "asc"}
        # Put the zip in the session's cookie jar (not a Cookie header): the server sets its own
        # geo-IP ep_selectedZipcode on other responses and a jar cookie would otherwise win.
        jar = self.http.session.cookies
        for name, value in (("ep_selectedZipcode", HOME_ZIP), ("ep_zipstatus", "ManualEntry")):
            try:
                jar.delete(name)
            except Exception:
                pass
            jar.set(name, value, domain="www.echopark.com", path="/")
        html = self.http.get_text(
            SRP_URL,
            params=params,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": BASE + "/",
            },
        )
        m = _STORE_RE.search(html)
        if not m:
            raise ValueError("no __STORE__ JSON on SRP (markup changed or bot wall)")
        try:
            store = json.loads(m.group(1))
        except json.JSONDecodeError as e:
            raise ValueError(f"__STORE__ is not JSON: {e}")
        vs = store.get("vehicleSearch") if isinstance(store, dict) else None
        common = store.get("common") if isinstance(store, dict) else None
        if not isinstance(vs, dict) or not isinstance(common, dict):
            raise ValueError(f"__STORE__ shape changed: keys={sorted(store)[:10] if isinstance(store, dict) else type(store)}")
        if not isinstance(vs.get("srpVehiclesData"), dict):
            raise ValueError("__STORE__.vehicleSearch.srpVehiclesData missing (markup changed)")
        if str(common.get("zipCode") or "") != HOME_ZIP:
            raise ValueError(f"search zip is {common.get('zipCode')!r}, not {HOME_ZIP} (zip cookie not honoured)")
        return store

    def fetch(self) -> SourceResult:
        res = SourceResult(source=self.key, listings=[])
        seen: set[str] = set()
        page = 0
        total: Optional[int] = None
        pages: Optional[int] = None
        dropped_far = 0
        while True:
            try:
                store = self._fetch_page(page)
            except HttpError as e:
                res.ok = False
                res.error = f"{e} (status={e.status})"
                return res
            except ValueError as e:
                res.ok = False
                res.error = str(e)
                return res
            res.pages_fetched += 1
            sv = store["vehicleSearch"]["srpVehiclesData"]
            dealers: dict[str, dict[str, Any]] = {}
            for d in store["common"].get("dealerships") or []:
                if isinstance(d, dict) and d.get("dealerId"):
                    dealers[str(d["dealerId"])] = d
            if not dealers:
                res.notes.append("no dealerships list in __STORE__ (markup change?)")
            total = _int(sv.get("resultCount")) or 0
            pages = _int(sv.get("pages")) or 0
            items = sv.get("items") or []
            if not isinstance(items, list):
                res.ok = False
                res.error = "srpVehiclesData.items is not a list (markup changed)"
                return res

            for it in items:
                if not isinstance(it, dict):
                    continue
                missing = REQUIRED_KEYS - set(it)
                if missing:
                    res.notes.append(f"item missing keys {sorted(missing)} (markup change?)")
                    continue
                if str(it.get("make") or "").lower() != MAKE.lower() or str(it.get("model") or "").lower() != MODEL.lower():
                    continue
                vin = (it.get("vin") or "").strip().upper()
                if not vin or vin in seen:
                    continue
                year = _int(it.get("year"))
                if not year or year < MIN_YEAR:
                    continue
                price = _int(it.get("sellingPrice"))
                mileage = _int(it.get("miles"))
                if price is None or mileage is None:
                    res.notes.append(f"{vin}: unparseable price/miles {it.get('sellingPrice')!r}/{it.get('miles')!r}; skipped")
                    continue
                dealer = dealers.get(str(it.get("dealership"))) or {}
                dist = it.get("distanceToUser")
                if dist is None:
                    dist = dealer.get("distance")
                try:
                    dist_f = float(dist) if dist is not None else None
                except (TypeError, ValueError):
                    dist_f = None
                if dist_f is not None and dist_f > LOCAL_RADIUS_MI:
                    dropped_far += 1
                    continue
                if not dealer:
                    res.notes.append(f"{vin}: dealership id {it.get('dealership')!r} not in store list; kept without address")
                loc = dealer.get("location") or {}
                store_name = dealer.get("marketingDisplayName") or (f"EchoPark {dealer['storeName']}" if dealer.get("storeName") else None)
                url = it.get("url") or ""
                if url.startswith("/"):
                    url = BASE + url
                if not url.startswith("http"):
                    res.notes.append(f"{vin}: bad url {it.get('url')!r}; skipped")
                    continue
                fees = it.get("feeBreakdown") or {}
                seen.add(vin)
                res.listings.append(
                    RawListing(
                        source=self.key,
                        source_id=str(it["stockNumber"]),
                        url=url,
                        vin=vin,
                        year=year,
                        price=price,
                        mileage=mileage,
                        trim_raw=(it.get("trim") or None),
                        drivetrain=None,   # not on the SRP
                        dealer=store_name or str(it.get("dealership")),
                        city=dealer.get("city"),
                        state=dealer.get("state"),
                        zip=str(dealer["zip"]) if dealer.get("zip") else None,
                        lat=loc.get("latitude"),
                        lng=loc.get("longitude"),
                        distance_mi=dist_f,
                        shipping_cost=float(it["shippingPrice"]) if it.get("shippingPrice") is not None else None,
                        shipping_note=("ship to store" if it.get("shippingStore") else ("at local store" if dist_f is not None else None)),
                        exterior_color=None,
                        interior_color=None,
                        extra={
                            "dealer_id": it.get("dealership"),
                            "store_id": dealer.get("storeId"),
                            "store_address": dealer.get("address"),
                            "model_number": it.get("modelNumber"),
                            "base_price": _int(it.get("basePrice")),
                            "doc_fee": _int(fees.get("documentFee")) if isinstance(fees, dict) else None,
                            "price_breakdown": it.get("priceBreakdown"),
                            "original_price": _int(it.get("originalPrice")),
                            "price_drop": _int(it.get("priceDifference")),
                            "days_since_price_drop": it.get("daysSincePriceDrop"),
                            "inventory_status": it.get("inventoryStatus"),
                            "shippable": it.get("shippable"),
                            "shipping_store": it.get("shippingStore"),
                            "consignment_source": it.get("consignmentSource"),
                        },
                    )
                )
            page += 1
            if not items or (pages and page >= pages) or (not pages and len(items) < PAGE_SIZE):
                break
            if res.pages_fetched >= MAX_PAGES:
                res.notes.append(f"stopped after {MAX_PAGES} pages (safety cap); {total} reported")
                break
        if dropped_far:
            res.notes.append(f"dropped {dropped_far} listing(s) farther than {LOCAL_RADIUS_MI} mi")
        log.info("echopark: %d listings (%s total reported incl. pre-2024, %d pages)", len(res.listings), total, res.pages_fetched)
        return res


SOURCE = EchoParkSource
