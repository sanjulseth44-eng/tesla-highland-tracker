"""Sewell Automotive Companies -- the Houston-area Sewell stores (Audi North Houston 77090, Audi
Sugar Land 77478, Cadillac of Houston 77079, INFINITI of North Houston 77090, Mercedes-Benz of West
Houston 77079); the DFW / Austin / San Antonio stores are dropped by distance.

How it works (two steps, both first-party sewell.com pages):
 1. GET https://www.sewell.com/dealer-inspire-inventory/inventory_sitemap  (~2.3 MB XML, ~9.5k
    <loc>s, one per vehicle detail page). The VDP slug encodes everything we need to pre-filter:
        /inventory/<used|certified-used|new>-<year>-<make>-<model>-<trim...>-<body>-<vin>/
    e.g. /inventory/used-2025-tesla-model-3-long-range-rwd-4dr-car-5yj3e1eaxsf928585/
    We keep used/certified-used, year >= MIN_YEAR, make tesla, model model-3.
 2. GET each matching VDP (a handful at most) and parse:
      - var inventory_localization = {"vehicle":{vin, stock, year, make, model, trim, ext_color,
        our_price, original_price, date_in_stock, type, api_id ...}}  (WordPress-localized JSON)
      - the schema.org ld+json Offer (price == our_price, the "Total Price" the page shows) and
        mileageFromOdometer.value; the Gravity Forms hidden field (miles=, int_color=, dealer_id=)
      - <div class="vdpContact"> <a class="vdpDealerName">Sewell BMW of Grapevine</a>
        <a class="vdpDealerAddress">1111 E State Hwy 114<br> Grapevine, TX 76051</a>  -> store.
    The store's zip is geocoded (highland.geo, offline zip DB) and anything > LOCAL_RADIUS_MI from
    HOME_ZIP is dropped, so the Dallas / Fort Worth / Austin / San Antonio stores never count.

Why not the search page or the Algolia index: /pre-owned-vehicles/ is a Dealer Inspire "Lightning"
SRP that renders results client-side from Algolia (appId 10APRXOTJR, search-only key in the page).
The *.algolia.net / *.algolianet.com hosts did not resolve from this environment (2026-09-02), and
the site's own "AI assistant" feed https://www.sewell.com/llm/inventory/ (documented in
/llms.txt with make/model/year_min/type/... filters) ignores every query string and serves the
generic "all brands" page instead, so it cannot be filtered or paged (9.5k vehicles, 95 pages).
The sitemap + VDP route is stable, cheap (1 + N requests) and robots-clean.

robots.txt (checked 2026-09-02, "User-agent: *" group):
    Crawl-delay: 1
    Disallow: /wp-admin/  /wp-includes/  /wp-content/uploads/inventory/  /wp-content/uploads/pb_backupbuddy/
    Disallow: /wp-content/uploads/chromeData/  /wp-content/uploads/configuratorTron/  /wp-content/uploads/gravity_forms/
Nothing matches /dealer-inspire-inventory/inventory_sitemap or /inventory/<slug>/ (the VDP we
link to). Crawl-delay 1 is honoured by Http; min_interval_s is 1.5 anyway.

Site is fronted by Cloudflare but serves normally with impersonate="chrome" (no challenge seen).
Prices: our_price (== "Total Price" on the VDP, schema.org Offer price, og:price) is the advertised
price; internet_price/ePrice (a few hundred less) and original_price/msrp are kept in extra.
"""
from __future__ import annotations

import html as htmlmod
import json
import logging
import re
from typing import Any, Optional

from ..config import LOCAL_RADIUS_MI, MIN_YEAR
from ..geo import distance_from_home, zip_latlng
from ..http import HttpError
from ..models import RawListing, SourceResult
from ..normalize import normalize_drivetrain
from .base import Source

log = logging.getLogger("highland.sewell")

BASE = "https://www.sewell.com"
SITEMAP_URL = f"{BASE}/dealer-inspire-inventory/inventory_sitemap"
MAX_VDPS = 20
_LOC_RE = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.S)
_SLUG_RE = re.compile(
    r"^https://www\.sewell\.com/inventory/(used|certified-used|certified-pre-owned|new)-(\d{4})-tesla-model-3-([a-z0-9\-]*?)-?([a-z0-9]{17})/?$"
)
_LOCALIZATION_RE = re.compile(r"var inventory_localization\s*=\s*(\{.*?\});\s*(?:/\*|\n|</script>)", re.S)
_VEHICLE_JSON_RE = re.compile(r'"vehicle":(\{"type":"[^"]*","modelCode":.*?\})\}', re.S)
_DEALER_NAME_RE = re.compile(r'class=["\']vdpDealerName["\'][^>]*>(.*?)</a>', re.S)
_DEALER_ADDR_RE = re.compile(r'class=["\']vdpDealerAddress["\'][^>]*>(.*?)</a>', re.S)
_ODOMETER_RE = re.compile(r'"mileageFromOdometer"\s*:\s*\{[^}]*?"value"\s*:\s*"?(\d[\d,]*)', re.S)
_GFORM_MILES_RE = re.compile(r"(?:&amp;|[?&])miles=(\d+)")
_GFORM_INT_RE = re.compile(r"(?:&amp;|[?&])int_color=([^&'\"]+)")
_LOCATION_ITEM_RE = re.compile(
    r'basic-info-item__label[^>]*>\s*Location:\s*</div>.*?basic-info-item__value[^>]*>(.*?)</span>', re.S)
_ADDR_RE = re.compile(r"^(.*?)(?:<br\s*/?>|\n)\s*([A-Za-z .]+?),\s*([A-Z]{2})\s*(\d{5})", re.S)

# Store -> (city, state, zip) fallback when the VDP contact block is missing (from /locations/, 2026-09-02).
STORES: dict[str, tuple[str, str, str]] = {
    "Sewell Audi North Houston": ("Houston", "TX", "77090"),
    "Sewell Audi Sugar Land": ("Sugar Land", "TX", "77478"),
    "Sewell Cadillac of Houston": ("Houston", "TX", "77079"),
    "Sewell INFINITI of North Houston": ("Houston", "TX", "77090"),
    "Sewell Mercedes-Benz of West Houston": ("Houston", "TX", "77079"),
    "Sewell Audi McKinney": ("McKinney", "TX", "75070"),
    "Sewell BMW of Grapevine": ("Grapevine", "TX", "76051"),
    "Sewell BMW of Plano": ("Plano", "TX", "75024"),
    "Sewell Buick GMC of Dallas": ("Dallas", "TX", "75209"),
    "Sewell Cadillac of Dallas": ("Dallas", "TX", "75209"),
    "Sewell Cadillac of Grapevine": ("Grapevine", "TX", "76051"),
    "Sewell INEOS Grenadier": ("Plano", "TX", "75024"),
    "Sewell INFINITI of Dallas": ("Dallas", "TX", "75209"),
    "Sewell INFINITI of Fort Worth": ("Fort Worth", "TX", "76132"),
    "Sewell Lexus of Dallas": ("Dallas", "TX", "75209"),
    "Sewell Lexus of Fort Worth": ("Fort Worth", "TX", "76132"),
    "Sewell MINI of Plano": ("Plano", "TX", "75024"),
    "Sewell Subaru of Dallas": ("Dallas", "TX", "75209"),
    "Sewell Land Rover North Austin": ("Austin", "TX", "78717"),
    "Sewell Cadillac of San Antonio": ("San Antonio", "TX", "78230"),
    "Sewell INEOS Grenadier San Antonio": ("San Antonio", "TX", "78230"),
    "Sewell Land Rover Boerne": ("Boerne", "TX", "78006"),
    "Sewell Mercedes-Benz of Selma": ("Selma", "TX", "78154"),
}


def _int(v: Any) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(round(v))
    m = re.sub(r"[^\d]", "", str(v))
    return int(m) if m else None


def _clean(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s = re.sub(r"<[^>]+>", " ", s)
    s = htmlmod.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def parse_vdp(html: str, url: str, slug_cond: str, slug_year: int, slug_trim: str, slug_vin: str) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Extract one vehicle from a Sewell VDP. Returns (fields, error). Pure function for tests."""
    m = _LOCALIZATION_RE.search(html)
    if not m:
        return None, "no inventory_localization JSON on VDP (markup changed?)"
    try:
        veh = json.loads(m.group(1)).get("vehicle") or {}
    except (json.JSONDecodeError, AttributeError) as e:
        return None, f"inventory_localization is not JSON: {e}"
    if not isinstance(veh, dict) or not veh.get("vin"):
        return None, "inventory_localization.vehicle missing/empty (markup changed?)"

    vin = str(veh.get("vin") or slug_vin).strip().upper()
    year = _int(veh.get("year")) or slug_year
    price = _int(veh.get("our_price"))
    if price is None:
        pm = re.search(r'"@type"\s*:\s*"Offer".*?"price"\s*:\s*"?(\d[\d,.]*)', html, re.S)
        price = _int(pm.group(1)) if pm else None
    mileage = None
    om = _ODOMETER_RE.search(html)
    if om:
        mileage = _int(om.group(1))
    if mileage is None:
        gm = _GFORM_MILES_RE.search(html)
        mileage = _int(gm.group(1)) if gm else None

    # second, richer vehicle JSON (modelCode / internet_price / msrp)
    v2: dict[str, Any] = {}
    m2 = _VEHICLE_JSON_RE.search(html)
    if m2:
        try:
            v2 = json.loads(m2.group(1))
        except json.JSONDecodeError:
            v2 = {}

    # store
    dealer = _clean((_DEALER_NAME_RE.search(html) or [None, None])[1])
    if not dealer:
        lm = _LOCATION_ITEM_RE.search(html)
        dealer = _clean(lm.group(1)) if lm else None
    city = state = zip_code = street = None
    am = _DEALER_ADDR_RE.search(html)
    if am:
        raw = re.sub(r"<i[^>]*>.*?</i>", "", am.group(1), flags=re.S)
        a = _ADDR_RE.search(raw.strip())
        if a:
            street, city, state, zip_code = _clean(a.group(1)), _clean(a.group(2)), a.group(3), a.group(4)
    if (not zip_code) and dealer and dealer in STORES:
        city, state, zip_code = STORES[dealer]

    im = _GFORM_INT_RE.search(html)
    int_color = _clean(im.group(1).replace("+", " ")) if im else None
    return {
        "vin": vin,
        "year": year,
        "price": price,
        "mileage": mileage,
        "stock": veh.get("stock"),
        "trim": veh.get("trim") or slug_trim.replace("-", " "),
        "slug_trim": slug_trim,
        "condition": veh.get("type") or slug_cond,
        "ext_color": veh.get("ext_color"),
        "int_color": int_color,
        "dealer": dealer,
        "street": street,
        "city": city,
        "state": state,
        "zip": zip_code,
        "dealer_id": veh.get("api_id"),
        "original_price": _int(veh.get("original_price")),
        "internet_price": _int(v2.get("internet_price") or v2.get("ePrice")),
        "msrp": _int(v2.get("msrp")),
        "model_code": v2.get("modelCode"),
        "date_in_stock": veh.get("date_in_stock"),
        "body": veh.get("body"),
        "make": veh.get("make"),
        "model": veh.get("model"),
    }, None


class SewellSource(Source):
    key = "sewell"
    label = "Sewell"
    kind = "local"
    homepage = f"{BASE}/pre-owned-vehicles/"
    impersonate = "chrome"
    min_interval_s = 1.5

    def _candidates(self) -> list[tuple[str, str, int, str, str]]:
        """(url, condition, year, trim_slug, vin) for every 2024+ used Model 3 in the sitemap."""
        xml = self.http.get_text(SITEMAP_URL, headers={"Accept": "application/xml,text/xml,*/*"})
        locs = _LOC_RE.findall(xml)
        if not locs:
            raise ValueError("inventory sitemap has no <loc> entries (markup changed or bot wall)")
        out = []
        for loc in locs:
            m = _SLUG_RE.match(loc.strip())
            if not m:
                continue
            cond, year, trim_slug, vin = m.group(1), int(m.group(2)), m.group(3), m.group(4)
            if cond == "new" or year < MIN_YEAR:
                continue
            out.append((loc.strip(), cond, year, trim_slug, vin))
        log.info("sewell: sitemap has %d vehicles, %d used 2024+ Model 3 candidates", len(locs), len(out))
        return out

    def fetch(self) -> SourceResult:
        res = SourceResult(source=self.key, listings=[])
        try:
            cands = self._candidates()
        except HttpError as e:
            res.ok = False
            res.error = f"{e} (status={e.status})"
            return res
        except ValueError as e:
            res.ok = False
            res.error = str(e)
            return res
        res.pages_fetched += 1
        if len(cands) > MAX_VDPS:
            res.notes.append(f"{len(cands)} candidates; only the first {MAX_VDPS} VDPs fetched (safety cap)")
            cands = cands[:MAX_VDPS]

        seen: set[str] = set()
        dropped_far = 0
        for url, cond, year, trim_slug, vin_slug in cands:
            try:
                page = self.http.get_text(url, headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8", "Referer": self.homepage})
            except HttpError as e:
                if e.status == 404:
                    res.notes.append(f"VDP gone (404): {url}")   # sold between sitemap build and now
                    continue
                res.ok = False
                res.error = f"{e} (status={e.status})"
                return res
            res.pages_fetched += 1
            fields, err = parse_vdp(page, url, cond, year, trim_slug, vin_slug)
            if fields is None:
                res.ok = False
                res.error = f"{err} at {url}"
                return res
            vin = fields["vin"]
            if vin in seen:
                continue
            if (fields.get("make") or "tesla").lower() != "tesla" or (fields.get("model") or "model 3").lower() != "model 3":
                continue
            if fields["year"] < MIN_YEAR:
                continue
            if str(fields.get("condition") or "").lower() == "new":
                continue
            if fields["price"] is None or fields["mileage"] is None:
                res.notes.append(f"{vin}: missing price/mileage on VDP; skipped")
                continue
            zip_code = fields.get("zip")
            if not zip_code:
                res.notes.append(f"{vin}: store {fields.get('dealer')!r} has no address on VDP and is not in STORES; skipped")
                continue
            ll = zip_latlng(zip_code)
            dist = distance_from_home(*ll) if ll else None
            if dist is not None and dist > LOCAL_RADIUS_MI:
                dropped_far += 1
                log.debug("sewell: %s at %s (%s) is %.0f mi away; dropped", vin, fields.get("dealer"), zip_code, dist)
                continue
            seen.add(vin)
            res.listings.append(
                RawListing(
                    source=self.key,
                    source_id=str(fields.get("stock") or vin),
                    url=url,
                    vin=vin,
                    year=fields["year"],
                    price=fields["price"],
                    mileage=fields["mileage"],
                    trim_raw=fields.get("trim"),
                    drivetrain=normalize_drivetrain(fields.get("slug_trim")),
                    dealer=fields.get("dealer"),
                    city=fields.get("city"),
                    state=fields.get("state"),
                    zip=zip_code,
                    lat=ll[0] if ll else None,
                    lng=ll[1] if ll else None,
                    distance_mi=dist,
                    exterior_color=fields.get("ext_color"),
                    interior_color=fields.get("int_color"),
                    extra={
                        "condition": fields.get("condition"),
                        "dealer_id": fields.get("dealer_id"),
                        "store_address": fields.get("street"),
                        "internet_price": fields.get("internet_price"),
                        "original_price": fields.get("original_price"),
                        "msrp_field": fields.get("msrp"),
                        "model_code": fields.get("model_code"),
                        "date_in_stock": fields.get("date_in_stock"),
                        "body": fields.get("body"),
                        "slug_trim": fields.get("slug_trim"),
                    },
                )
            )
        if dropped_far:
            res.notes.append(f"dropped {dropped_far} Model 3(s) at Sewell stores farther than {LOCAL_RADIUS_MI} mi (DFW/Austin/San Antonio)")
        log.info("sewell: %d local listings from %d candidates (%d pages)", len(res.listings), len(cands), res.pages_fetched)
        return res


SOURCE = SewellSource
