"""CarMax -- nationwide inventory via the same JSON search endpoint carmax.com's own
search page calls (https://www.carmax.com/cars/api/search/run).

robots.txt (checked 2026-09-02): /cars/api/search/run is allowed; /car/* detail pages are
disallowed for crawling, which is why we never fetch them -- we only LINK to them.
Akamai blocks default python/curl TLS fingerprints; curl_cffi's Chrome impersonation passes.
"""
from __future__ import annotations

import logging
from datetime import datetime

from ..config import HOME_ZIP, MIN_YEAR
from ..http import HttpError
from ..models import RawListing, SourceResult
from ..normalize import normalize_drivetrain
from .base import Source

log = logging.getLogger("highland.carmax")

SEARCH_URL = "https://www.carmax.com/cars/api/search/run"
PAGE_SIZE = 100
REQUIRED_KEYS = {"stockNumber", "vin", "year", "basePrice", "mileage", "storeName", "isSaleable"}


class CarMaxSource(Source):
    key = "carmax"
    label = "CarMax"
    kind = "carmax"
    homepage = "https://www.carmax.com/cars/tesla/model-3"
    impersonate = "chrome"
    min_interval_s = 1.5

    def fetch(self) -> SourceResult:
        res = SourceResult(source=self.key, listings=[])
        max_year = datetime.now().year + 1
        uri = f"/cars/tesla/model-3?year={MIN_YEAR}-{max_year}"
        skip = 0
        total = None
        seen: set[str] = set()
        while True:
            params = {
                "uri": uri,
                "skip": skip,
                "take": PAGE_SIZE,
                "zipCode": HOME_ZIP,
                "radius": "radius-nationwide",
                "shipping": -1,
                "sort": "best-match",
                "scoringRules": "default",
                "showCustomShipping": "true",
            }
            try:
                data = self.http.get_json(
                    SEARCH_URL,
                    params=params,
                    headers={"Accept": "application/json", "Referer": self.homepage},
                )
            except HttpError as e:
                res.ok = False
                res.error = f"{e} (status={e.status})"
                return res
            res.pages_fetched += 1
            if not isinstance(data, dict) or "items" not in data or "totalCount" not in data:
                res.ok = False
                res.error = f"unexpected response shape: keys={list(data)[:10] if isinstance(data, dict) else type(data)}"
                return res
            if data.get("searchFailed") or data.get("hasSearchError"):
                res.ok = False
                res.error = "CarMax reported searchFailed/hasSearchError"
                return res
            total = int(data["totalCount"])
            items = data["items"] or []
            for it in items:
                missing = REQUIRED_KEYS - set(it)
                if missing:
                    res.notes.append(f"item missing keys {sorted(missing)} (markup change?)")
                    continue
                vin = (it.get("vin") or "").upper()
                if not vin or vin in seen:
                    continue
                seen.add(vin)
                if not it.get("isSaleable") or it.get("isReserved") or it.get("isComingSoon"):
                    continue
                try:
                    year = int(it["year"])
                    price = int(round(float(it["basePrice"])))
                    mileage = int(it["mileage"])
                except (TypeError, ValueError):
                    res.notes.append(f"unparseable numbers on stock {it.get('stockNumber')}")
                    continue
                fee = it.get("transferFee")
                ttype = it.get("transferType") or ""
                if fee is None:
                    if ttype == "available-elsewhere" or it.get("isTransferable") is False:
                        note = "not shippable to 77479"
                    else:
                        note = "shipping unknown"
                elif fee == 0:
                    note = "free transfer" if "FreeTransfer" in (it.get("transferTags") or []) else "at local store"
                else:
                    note = "shipping"
                res.listings.append(
                    RawListing(
                        source=self.key,
                        source_id=str(it["stockNumber"]),
                        url=f"https://www.carmax.com/car/{it['stockNumber']}",
                        vin=vin,
                        year=year,
                        price=price,
                        mileage=mileage,
                        trim_raw=it.get("trim"),
                        drivetrain=normalize_drivetrain(it.get("driveTrain")),
                        horsepower=it.get("horsepower"),
                        dealer=f"CarMax {it.get('storeName')}",
                        city=it.get("storeCity"),
                        state=it.get("stateAbbreviation"),
                        distance_mi=float(it["distance"]) if it.get("distance") is not None else None,
                        shipping_cost=float(fee) if fee is not None else None,
                        shipping_note=note,
                        exterior_color=it.get("exteriorColor"),
                        interior_color=it.get("interiorColor"),
                        extra={
                            "store_id": it.get("storeId"),
                            "has_price_drop": it.get("hasPriceDrop"),
                            "original_price": it.get("originalPrice"),
                            "listed_since": it.get("lastMadeSaleableDate"),
                            "transfer_type": ttype,
                            "ev_tax_credit": it.get("isEVTaxCreditEligible"),
                            "highlights": it.get("highlights"),
                        },
                    )
                )
            skip += PAGE_SIZE
            if not items or skip >= total:
                break
            if res.pages_fetched > 20:
                res.notes.append("stopped after 20 pages (safety cap)")
                break
        log.info("carmax: %d listings (%d total reported, %d pages)", len(res.listings), total, res.pages_fetched)
        return res


SOURCE = CarMaxSource
