"""Hertz Car Sales -- Dealer.com-hosted site; used inventory within LOCAL_RADIUS_MI of HOME_ZIP.

robots.txt (checked 2026-09-02, "User-agent: *" group = lines 153-171, no Crawl-delay):
  Disallow: /api/pse/  /api/legacy/pse/  /external-catalog-services/  /tcd/  /esntial.htm  /microsite/
  /*ajax.htm$  /*fragment.htm  /image/viewer.htm  /apis/mycars/  /mycars/  /reserve-it-now/form.htm
  /contact-form.htm  /specials/trims.htm  /inventory-detail/print.htm  /blog/tags/*  /pixall/  */pixall/
  - /used-inventory/index.htm?make=Tesla&model=Model+3&geoZip=77479&geoRadius=100&start=N (SRP): ALLOWED.
  - /used/<Make>/<year>-<make>-<model>-<uuid>.htm (VDP we link to): ALLOWED; verified one resolves (200).
  - Named AI-bot groups (Claude-User, GPTBot, ...) carry stricter rules, but we identify as Chrome and
    the "*" group applies.

Endpoint: the SRP HTML itself. Dealer.com's legacy JSON API
  /apis/widget/INVENTORY_LISTING_DEFAULT_AUTO_USED:inventory-data-bus1/getInventory now answers
  {"message": "Legacy inventory endpoints are deprecated and no longer return data."} and
  /api/widget/ws-inv-data/getInventory 404s, so we parse the inline state the React widget hydrates from:
    DDC.WS.state['ws-inv-data']['inventory-data-bus2'] = {"moreRequestData": {..., "serverGeoZipSource":
    "url-param", "serverResolvedGeoZip": "77479"}, "WIS": {"pageInfo": {totalCount, pageSize, pageStart},
    "inventory": [...], "accounts": {<accountId>: {name, address: {city, state, postalCode}, phone}}, ...}}
  geoZip/geoRadius are honored server-side; without them Dealer.com geolocates the client IP.
  Paging: ?start=<offset> (pageSize 24; verified pageStart echoes 24 on the second page).
Record fields used: vin, year, make, model, trim, link, uuid, stockNumber, status, accountId, offSite,
  pricing.dprice[] (typeClass "askingPrice", value "$19,599") with trackingPricing.internetPrice as fallback,
  trackingAttributes[] (odometer, exteriorColor, interiorColor, driveLine, geodist), attributes[]
  (locationDistance: "Houston, TX ::: 15mi").

Quirks: Imperva/Incapsula fronts the site; curl_cffi Chrome impersonation gets 200s. On 2026-09-02 Hertz
  listed 0 Tesla Model 3 (0 Teslas at all) within 100 mi of 77479 out of 361 used cars, so an empty result
  is the expected steady state until they stock one.
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

log = logging.getLogger("highland.hertz")

BASE = "https://www.hertzcarsales.com"
SRP_URL = f"{BASE}/used-inventory/index.htm"
MAX_PAGES = 10
_STATE_RE = re.compile(r"DDC\.WS\.state\['ws-inv-data'\]\['[^']+'\]\s*=\s*")
REQUIRED_KEYS = {"vin", "year", "make", "model", "link", "uuid"}


def _int(s: Any) -> Optional[int]:
    if s is None or isinstance(s, bool):
        return None
    if isinstance(s, (int, float)):
        return int(round(s))
    m = re.sub(r"[^\d]", "", str(s))
    return int(m) if m else None


def _attrs(v: dict[str, Any], key: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for a in v.get(key) or []:
        if isinstance(a, dict) and a.get("name"):
            out[a["name"]] = a.get("value")
    return out


def _price(v: dict[str, Any]) -> Optional[int]:
    pricing = v.get("pricing") if isinstance(v.get("pricing"), dict) else {}
    for p in pricing.get("dprice") or []:
        if isinstance(p, dict) and (p.get("typeClass") == "askingPrice" or p.get("type") == "TOTAL"):
            n = _int(p.get("value"))
            if n:
                return n
    tp = v.get("trackingPricing") if isinstance(v.get("trackingPricing"), dict) else {}
    for k in ("internetPrice", "salePrice", "retailValue"):
        n = _int(tp.get(k))
        if n:
            return n
    return None


class HertzSource(Source):
    key = "hertz"
    label = "Hertz Car Sales"
    kind = "local"
    homepage = f"{SRP_URL}?make=Tesla&model=Model+3&geoZip={HOME_ZIP}&geoRadius={LOCAL_RADIUS_MI}"
    impersonate = "chrome"
    min_interval_s = 2.0

    def _fetch_page(self, start: int) -> dict[str, Any]:
        """Return the ws-inv-data state dict for one SRP page. Raises HttpError / ValueError."""
        html = self.http.get_text(
            SRP_URL,
            params={"make": "Tesla", "model": "Model 3", "geoZip": HOME_ZIP,
                    "geoRadius": LOCAL_RADIUS_MI, "start": start},
            headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                     "Referer": BASE + "/"},
        )
        m = _STATE_RE.search(html)
        if not m:
            raise ValueError("no DDC.WS.state['ws-inv-data'] blob on SRP (markup changed or bot wall)")
        try:
            state, _ = json.JSONDecoder().raw_decode(html, m.end())
        except json.JSONDecodeError as e:
            raise ValueError(f"ws-inv-data state is not JSON: {e}")
        wis = state.get("WIS") if isinstance(state, dict) else None
        if not isinstance(wis, dict) or not isinstance(wis.get("inventory"), list) or not isinstance(wis.get("pageInfo"), dict):
            raise ValueError(f"WIS shape changed: keys={sorted(wis)[:12] if isinstance(wis, dict) else type(wis)}")
        return state

    def fetch(self) -> SourceResult:
        res = SourceResult(source=self.key, listings=[])
        seen: set[str] = set()
        start = 0
        total: Optional[int] = None
        dropped_far = 0
        while True:
            try:
                state = self._fetch_page(start)
            except HttpError as e:
                res.ok = False
                res.error = f"{e} (status={e.status})"
                return res
            except ValueError as e:
                res.ok = False
                res.error = str(e)
                return res
            res.pages_fetched += 1
            mrd = state.get("moreRequestData") if isinstance(state.get("moreRequestData"), dict) else {}
            if start == 0 and str(mrd.get("serverResolvedGeoZip") or "") not in ("", HOME_ZIP):
                res.notes.append(f"server resolved geoZip {mrd.get('serverResolvedGeoZip')} instead of {HOME_ZIP}")
            wis = state["WIS"]
            info = wis["pageInfo"]
            total = _int(info.get("totalCount")) or 0
            page_size = _int(info.get("pageSize")) or 24
            accounts = wis.get("accounts") if isinstance(wis.get("accounts"), dict) else {}
            items = wis["inventory"]
            for v in items:
                if not isinstance(v, dict):
                    continue
                missing = REQUIRED_KEYS - set(v)
                if missing:
                    res.notes.append(f"vehicle missing keys {sorted(missing)} (markup change?)")
                    continue
                if (v.get("make") or "").strip().lower() != "tesla" or (v.get("model") or "").strip().lower() != "model 3":
                    continue
                year = _int(v.get("year"))
                if year is None or year < MIN_YEAR:
                    continue
                if (v.get("type") or "used").lower() == "new":
                    continue
                vin = (v.get("vin") or "").strip().upper()
                if not vin or vin in seen:
                    continue
                ta = _attrs(v, "trackingAttributes")
                attrs = _attrs(v, "attributes")
                try:
                    dist = float(ta["geodist"]) if ta.get("geodist") not in (None, "") else None
                except (TypeError, ValueError):
                    dist = None
                if dist is not None and dist > LOCAL_RADIUS_MI:
                    dropped_far += 1
                    continue
                price = _price(v)
                mileage = _int(ta.get("odometer"))
                if price is None:
                    res.notes.append(f"{vin} (stock {v.get('stockNumber')}) has no asking price; skipped")
                    continue
                if mileage is None:
                    res.notes.append(f"{vin} (stock {v.get('stockNumber')}) has no odometer; skipped")
                    continue
                seen.add(vin)
                acct = accounts.get(str(v.get("accountId"))) if v.get("accountId") else None
                acct = acct if isinstance(acct, dict) else {}
                addr = acct.get("address") if isinstance(acct.get("address"), dict) else {}
                loc = attrs.get("locationDistance") or ""      # "Houston, TX ::: 15mi"
                loc_city, loc_state = None, None
                m = re.match(r"\s*([^,]+),\s*([A-Z]{2})", str(loc))
                if m:
                    loc_city, loc_state = m.group(1).strip(), m.group(2)
                link = v["link"] if str(v["link"]).startswith("http") else BASE + str(v["link"])
                res.listings.append(
                    RawListing(
                        source=self.key,
                        source_id=str(v.get("stockNumber") or v["uuid"]),
                        url=link,
                        vin=vin,
                        year=year,
                        price=price,
                        mileage=mileage,
                        trim_raw=(v.get("trim") or None),
                        drivetrain=normalize_drivetrain(ta.get("driveLine")),
                        dealer=f"Hertz Car Sales {acct.get('name') or loc_city or ''}".strip(),
                        city=addr.get("city") or loc_city,
                        state=addr.get("state") or loc_state,
                        zip=str(addr["postalCode"]) if addr.get("postalCode") else None,
                        distance_mi=dist,
                        exterior_color=ta.get("exteriorColor"),
                        interior_color=ta.get("interiorColor"),
                        extra={
                            "uuid": v.get("uuid"),
                            "account_id": v.get("accountId"),
                            "status": v.get("status"),
                            "off_site": v.get("offSite"),
                            "certified": v.get("certified"),
                            "inventory_date": v.get("inventoryDate"),
                            "retail_price": (v.get("pricing") or {}).get("retailPrice") if isinstance(v.get("pricing"), dict) else None,
                            "title": v.get("title"),
                        },
                    )
                )
            start += max(len(items), 1)
            if not items or start >= total:
                break
            if res.pages_fetched >= MAX_PAGES:
                res.notes.append(f"stopped after {MAX_PAGES} pages (safety cap); {total} reported")
                break
            start = res.pages_fetched * page_size
        if dropped_far:
            res.notes.append(f"dropped {dropped_far} listing(s) farther than {LOCAL_RADIUS_MI} mi")
        log.info("hertz: %d listings (%s total reported, %d pages)", len(res.listings), total, res.pages_fetched)
        return res


SOURCE = HertzSource
