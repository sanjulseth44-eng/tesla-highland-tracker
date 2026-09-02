"""Enterprise Car Sales -- AEM site. Used Model 3s within LOCAL_RADIUS_MI of HOME_ZIP, discovered
through the VDP sitemap and read from the server-rendered vehicle detail pages.

robots.txt (checked 2026-09-02, "User-Agent: *" group = lines 376-389, no Crawl-delay):
  Disallow: /bin/  /crx/  /system/  /apps/  /libs/  /tmp/  /var/  /etc/  /services/  /content/dam/
  /content/usergenerated/  /azure-b2c/      Allow: /
  (the same 13 rules are repeated for ~25 named bots incl. ClaudeBot/GPTBot; "/services/" is disallowed
  for "*" too.)  Sitemap: /sitemap.xml, /vdp-sitemap.xml, /search.sitemap.xml, /locations.sitemap.xml
  - /vdp-sitemap.xml, /vdp-sitemap.xml/<n>.xml and /vehicle/<VIN> (VDP): ALLOWED (only "Allow: /" matches).

Why the sitemap: the search pages (/search/..., /content/carsales-web/us/en_us/search/...) render no
  vehicles server-side. The browser app fetches an anonymous OAuth bearer token from
  https://api.ehi.com/identityAndAccessManagement with an API key embedded in the page and queries an
  OpenSearch BFF on api.ehi.com ("carSalesBffConfig" / "openSearchConfig" in the page config). That is an
  authenticated private API, so this module does not use it. The VDP, however, is fully server-rendered:
  <script id="vdp-page-config" type="application/json"> holds salePrice, originalSalePrice, listDate,
  stockDateTime, kelleyBlueBook, vehicle.{vin, fleetVehicleId, odometer.lastKnownValue,
  physicalLocation.postalCode, geoLocation.point{lat,lon}, specification{year, trimDescription,
  drivetrainDescription, makeDescription, modelDescription}, color, filter-tags.vehicleAvailableForSale,
  prices.stateLevelPrices[{destinationState, salePrice, stateFee, transferRateFee, totalPriceForVDP}]}
  and <title> is "Used <year> Tesla Model 3 in <City>, <ST> <VIN> | Enterprise Car Sales".

Flow: GET /vdp-sitemap.xml (index) -> each part -> keep /vehicle/<VIN> where the VIN starts with 5YJ3
  (Fremont-built Model 3) and its model-year code is >= MIN_YEAR -> GET each VDP (cap MAX_VDP_FETCHES)
  -> keep cars within LOCAL_RADIUS_MI (straight-line from the VDP's lat/lng, else its zip).

Quirks: on 2026-09-02 the sitemap (14,781 VDPs) held 14 Model 3s, all 2018-2023, so this module is
  expected to return nothing until Enterprise de-fleets a Highland car. The sitemap is regenerated
  periodically: a car can sell before the sitemap drops it (VDP 404 -> skipped) or be listed before it
  appears. salePrice is Enterprise's no-haggle price before the state doc fee; the TX fee/transfer entry
  is kept in extra. Akamai fronts the site; curl_cffi Chrome impersonation gets 200s.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from ..config import LOCAL_RADIUS_MI, MIN_YEAR
from ..geo import distance_from_home, zip_latlng
from ..http import HttpError
from ..models import RawListing, SourceResult
from ..normalize import normalize_drivetrain, vin_year
from .base import Source

log = logging.getLogger("highland.enterprise")

BASE = "https://www.enterprisecarsales.com"
SITEMAP_INDEX = f"{BASE}/vdp-sitemap.xml"
MAX_SITEMAP_PARTS = 10
MAX_VDP_FETCHES = 40
_LOC_RE = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.S)
_VDP_VIN_RE = re.compile(r"/vehicle/([A-HJ-NPR-Z0-9]{17})/?$")
_CONFIG_RE = re.compile(r'<script[^>]*id="vdp-page-config"[^>]*>\s*(\{.*?\})\s*</script>', re.S)
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)


def _int(s: Any) -> Optional[int]:
    if s is None or isinstance(s, bool):
        return None
    if isinstance(s, (int, float)):
        return int(round(s))
    m = re.sub(r"[^\d]", "", str(s))
    return int(m) if m else None


def _is_candidate(vin: str) -> bool:
    v = vin.upper()
    if not v.startswith("5YJ3"):
        return False
    y = vin_year(v)
    return y is not None and y >= MIN_YEAR


class EnterpriseSource(Source):
    key = "enterprise"
    label = "Enterprise Car Sales"
    kind = "local"
    homepage = f"{BASE}/search/buy-a-car/electric-vehicles"
    impersonate = "chrome"
    min_interval_s = 2.0

    # ---- sitemap ----
    def _candidate_vins(self, res: SourceResult) -> Optional[list[str]]:
        """VINs of 2024+ Model 3 VDPs listed in the sitemap, or None (res.error set) on failure."""
        try:
            index = self.http.get_text(SITEMAP_INDEX, headers={"Accept": "application/xml,text/xml,*/*;q=0.8"})
        except HttpError as e:
            res.ok = False
            res.error = f"{e} (status={e.status})"
            return None
        res.pages_fetched += 1
        locs = _LOC_RE.findall(index)
        if not locs:
            res.ok = False
            res.error = "vdp-sitemap.xml has no <loc> entries (markup changed)"
            return None
        parts = [u for u in locs if not _VDP_VIN_RE.search(u)]
        texts = [index] if len(parts) < len(locs) else []
        for part in parts[:MAX_SITEMAP_PARTS]:
            try:
                texts.append(self.http.get_text(part, headers={"Accept": "application/xml,text/xml,*/*;q=0.8"}))
            except HttpError as e:
                res.notes.append(f"sitemap part {part} failed: {e}")
                continue
            res.pages_fetched += 1
        if len(parts) > MAX_SITEMAP_PARTS:
            res.notes.append(f"only the first {MAX_SITEMAP_PARTS} of {len(parts)} sitemap parts were read")
        vins: list[str] = []
        seen: set[str] = set()
        n_urls = 0
        for t in texts:
            for u in _LOC_RE.findall(t):
                m = _VDP_VIN_RE.search(u)
                if not m:
                    continue
                n_urls += 1
                vin = m.group(1).upper()
                if vin not in seen and _is_candidate(vin):
                    seen.add(vin)
                    vins.append(vin)
        if n_urls == 0:
            res.ok = False
            res.error = "no /vehicle/<VIN> URLs in the VDP sitemap (markup changed)"
            return None
        log.info("enterprise: %d VDP urls in sitemap, %d are %d+ Model 3 candidates", n_urls, len(vins), MIN_YEAR)
        return vins

    # ---- VDP ----
    def _parse_vdp(self, html: str, vin: str) -> Optional[RawListing]:
        """Build a RawListing from one VDP. Raises ValueError on unexpected markup; None if not for sale."""
        m = _CONFIG_RE.search(html)
        if not m:
            raise ValueError("no vdp-page-config JSON on VDP (markup changed)")
        try:
            cfg = json.loads(m.group(1))
        except json.JSONDecodeError as e:
            raise ValueError(f"vdp-page-config is not JSON: {e}")
        veh = cfg.get("vehicle") if isinstance(cfg, dict) else None
        if not isinstance(veh, dict) or "salePrice" not in cfg:
            raise ValueError("vdp-page-config shape changed (no vehicle/salePrice)")
        tags = veh.get("filter-tags") if isinstance(veh.get("filter-tags"), dict) else {}
        if str(tags.get("vehicleAvailableForSale", "true")).lower() != "true":
            return None
        spec = veh.get("specification") if isinstance(veh.get("specification"), dict) else {}
        if (spec.get("makeDescription") or tags.get("make") or "").lower() != "tesla":
            return None
        if (spec.get("modelDescription") or tags.get("model") or "").lower() != "model 3":
            return None
        year = _int(spec.get("year")) or vin_year(vin)
        if year is None or year < MIN_YEAR:
            return None
        price = _int(cfg.get("salePrice"))
        odo = veh.get("odometer") if isinstance(veh.get("odometer"), dict) else {}
        mileage = _int(odo.get("lastKnownValue"))
        if price is None or mileage is None:
            raise ValueError(f"{vin}: salePrice={cfg.get('salePrice')!r} odometer={odo!r}")
        loc = veh.get("physicalLocation") if isinstance(veh.get("physicalLocation"), dict) else {}
        zipc = str(loc.get("postalCode") or "")[:5] or None
        pt = ((veh.get("geoLocation") or {}).get("point")) if isinstance(veh.get("geoLocation"), dict) else None
        lat = lng = None
        if isinstance(pt, dict):
            try:
                lat, lng = float(pt["lat"]), float(pt["lon"])
            except (KeyError, TypeError, ValueError):
                lat = lng = None
        if (lat is None or lng is None) and zipc:
            ll = zip_latlng(zipc)
            if ll:
                lat, lng = ll
        dist = distance_from_home(lat, lng) if lat is not None and lng is not None else None
        city = state = None
        tm = _TITLE_RE.search(html)
        if tm:
            t = re.search(r"\bin\s+([^,|]+?),\s*([A-Z]{2})\b", tm.group(1))
            if t:
                city, state = t.group(1).strip(), t.group(2)
        color = veh.get("color") if isinstance(veh.get("color"), dict) else {}
        tx = None
        prices = veh.get("prices") if isinstance(veh.get("prices"), dict) else {}
        for p in prices.get("stateLevelPrices") or []:
            if isinstance(p, dict) and p.get("destinationState") == "TX":
                tx = {k: p.get(k) for k in ("salePrice", "stateFee", "transferRateFee", "totalPriceForVDP", "distance")}
                break
        kbb = cfg.get("kelleyBlueBook") if isinstance(cfg.get("kelleyBlueBook"), dict) else {}
        badge = ((cfg.get("badges") or {}).get("operational") or {}) if isinstance(cfg.get("badges"), dict) else {}
        return RawListing(
            source=self.key,
            source_id=str(veh.get("fleetVehicleId") or vin),
            url=f"{BASE}/vehicle/{vin}",
            vin=vin,
            year=year,
            price=price,
            mileage=mileage,
            trim_raw=(spec.get("trimDescription") or tags.get("trim") or None),
            drivetrain=normalize_drivetrain(spec.get("drivetrainDescription") or tags.get("driveTrain")),
            dealer=f"Enterprise Car Sales {city}".strip() if city else "Enterprise Car Sales",
            city=city,
            state=state,
            zip=zipc,
            lat=lat,
            lng=lng,
            distance_mi=dist,
            exterior_color=color.get("exteriorColorDescription") or tags.get("exteriorColor"),
            interior_color=color.get("interiorColorDescription") or tags.get("interiorColor"),
            extra={
                "original_sale_price": cfg.get("originalSalePrice"),
                "list_date": cfg.get("listDate"),
                "stock_date": cfg.get("stockDateTime"),
                "kbb_value": kbb.get("value"),
                "badge": badge.get("description") if isinstance(badge, dict) else None,
                "tx_pricing": tx,
                "location_urn": loc.get("location"),
            },
        )

    # ---- main ----
    def fetch(self) -> SourceResult:
        res = SourceResult(source=self.key, listings=[])
        vins = self._candidate_vins(res)
        if vins is None:
            return res
        if len(vins) > MAX_VDP_FETCHES:
            res.notes.append(f"{len(vins)} candidate VDPs; only the first {MAX_VDP_FETCHES} fetched (safety cap)")
            vins = vins[:MAX_VDP_FETCHES]
        fetched = failed = 0
        dropped_far = 0
        for vin in vins:
            url = f"{BASE}/vehicle/{vin}"
            try:
                html = self.http.get_text(url, headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                                                        "Referer": BASE + "/"})
            except HttpError as e:
                if e.status in (404, 410):
                    res.notes.append(f"{vin}: VDP gone ({e.status}); probably sold")
                else:
                    failed += 1
                    res.notes.append(f"{vin}: {e} (status={e.status})")
                continue
            res.pages_fetched += 1
            fetched += 1
            try:
                listing = self._parse_vdp(html, vin)
            except ValueError as e:
                res.notes.append(f"{vin}: {e}")
                continue
            if listing is None:
                continue
            if listing.distance_mi is not None and listing.distance_mi > LOCAL_RADIUS_MI:
                dropped_far += 1
                continue
            if listing.distance_mi is None:
                res.notes.append(f"{vin}: no location on VDP; kept without distance")
            res.listings.append(listing)
        if vins and fetched == 0 and failed:
            res.ok = False
            res.error = f"all {failed} VDP fetches failed"
            return res
        if dropped_far:
            res.notes.append(f"dropped {dropped_far} Model 3(s) farther than {LOCAL_RADIUS_MI} mi")
        log.info("enterprise: %d listings within %d mi (%d candidate VDPs, %d fetched)",
                 len(res.listings), LOCAL_RADIUS_MI, len(vins), fetched)
        return res


SOURCE = EnterpriseSource
