# Model 3 Highland Tracker — Sugar Land / Houston (77479)

Live dashboard: **https://sanjulseth44-eng.github.io/tesla-highland-tracker/**

Tracks verifiable used **2024+ Tesla Model 3 (Highland refresh)** listings: every CarMax car nationwide
(with CarMax's shipping quote to 77479) plus local dealers within 100 miles of Sugar Land. Every card links
back to the dealer's own listing page so the price can be checked at the source. Pre-refresh (2017–2023)
cars are excluded entirely.

A GitHub Actions cron job refreshes the data once a day, commits the SQLite database and a JSON export to
this repo, rebuilds the React app and deploys it to GitHub Pages. Nothing runs on anyone's laptop.

## How it works

```
GitHub Actions (daily 06:30 CT)
  └─ scraper/run.py
       ├─ highland/sources/*.py   one module per dealer site (CarMax, Tesla, …)
       ├─ highland/normalize.py   VIN + trim canonicalization, 2024+ filter
       ├─ highland/pipeline.py    upsert into SQLite, detect new / price change / removed
       └─ data/latest.json        export consumed by the web app
  └─ web/ (Vite + React)  →  GitHub Pages
```

* **Store:** `data/listings.db` (SQLite, committed). Tables `listings`, `price_history`, `changes`, `runs`.
* **Export:** `data/latest.json` — active listings plus anything removed in the last 14 days, the change
  log, the MSRP table and per-source health. The web app fetches this file at load.
* **Front end:** `web/` — dark instrument-cluster dashboard with table/card views, filters, median-by-spec
  panel, price-vs-mileage scatter, change log, MSRP reference. Read-only, no login, mobile friendly.

## Running locally

```bash
python3.12 -m venv .venv && ./.venv/bin/pip install -r scraper/requirements.txt pytest
./.venv/bin/python -m pytest scraper/tests -q
./.venv/bin/python scraper/run.py --dry-run --sources carmax -v        # fetch + normalize, no writes
./.venv/bin/python scraper/run.py --db data/listings.db --out data/latest.json   # real run, all sources
cd web && npm install && npm run dev                                   # http://localhost:5173/tesla-highland-tracker/
```

`run.py` exits non-zero only if *every* requested source failed, so one flaky dealer never blocks the
daily refresh. A source that fails is logged in the `runs` table and shown as an error in the dashboard's
sources strip; its previous listings stay active until the source succeeds again (they are never "removed"
on the strength of a failed or suspicious-looking run).

## Adding a dealer source

1. **Check robots.txt.** Fetch `https://<site>/robots.txt` and test each path you plan to request with
   `highland.robots.Robots.can_fetch(path_and_query)`. The `Http` client enforces robots.txt (and
   `Crawl-delay`) for you and raises `RobotsDisallowed`; do not bypass it. If the search pages you need
   are disallowed, the site is off limits — note it in the table below and stop.
2. **Find the data.** Load the site's own search page in a browser and look at what it fetches: a JSON API
   is ideal, embedded JSON (`__NEXT_DATA__`, `window.__STATE__`, JSON-LD) is fine, HTML `data-*` attributes
   are a last resort. Prefer a query already restricted to Tesla / Model 3 / 2024+ / zip 77479 / 100 mi.
3. **Write `scraper/highland/sources/<key>.py`:**

   ```python
   from ..models import RawListing, SourceResult
   from ..http import HttpError
   from .base import Source

   class ExampleSource(Source):
       key = "example"            # DB / CLI id
       label = "Example Motors"   # shown in the dashboard
       kind = "local"             # "local" (100-mile radius) or "carmax" (nationwide + shipping)
       homepage = "https://www.example.com/used/tesla-model-3"
       impersonate = "chrome"     # curl_cffi fingerprint; try "safari_ios" if the edge challenges Chrome
       min_interval_s = 1.0

       def fetch(self) -> SourceResult:
           res = SourceResult(source=self.key, listings=[])
           try:
               data = self.http.get_json("https://www.example.com/api/inventory", params={...})
           except HttpError as e:
               res.ok, res.error = False, str(e)      # never raise for expected failures
               return res
           if "vehicles" not in data:                  # markup / API drift
               res.ok, res.error = False, "unexpected response shape"
               return res
           for v in data["vehicles"]:
               if v["make"] != "Tesla" or v["model"] != "Model 3" or int(v["year"]) < 2024:
                   continue
               res.listings.append(RawListing(
                   source=self.key, source_id=str(v["id"]), url=v["vdp_url"], vin=v["vin"],
                   year=int(v["year"]), price=int(v["price"]), mileage=int(v["miles"]),
                   trim_raw=v.get("trim"), drivetrain=v.get("drivetrain"),
                   dealer="Example Motors Katy", city="Katy", state="TX", zip="77494",
               ))
           return res

   SOURCE = ExampleSource
   ```

   Fill `trim_raw` exactly as the site shows it (the pipeline maps it to RWD / Long Range RWD /
   Long Range AWD / Performance / Standard using `normalize.infer_trim`, with the VIN as a tiebreaker).
   Give a `zip` (or `lat`/`lng`, or `distance_mi`) so the distance from 77479 can be computed.
   Put anything else useful in `extra` (it is stored as JSON and exported).
4. **Register it:** add the module name to `SOURCE_MODULES` in `scraper/highland/sources/__init__.py`.
5. **Test:** `./.venv/bin/python scraper/run.py --dry-run --sources <key> -v` (in-memory DB, prints a
   summary) and `pytest`. Spot-check two listing URLs by hand.
6. **Document it** in the source table below (what endpoint, any fingerprint workaround, reliability).

The daily workflow picks up new modules automatically. Pre-2024 or non-Model-3 rows are dropped by the
pipeline even if a source returns them, so err on the side of returning too much rather than filtering
with fragile string matching.

## Data model notes

* **Trims.** Canonical buckets are `RWD` (2024–25 base LFP), `Long Range RWD`, `Long Range AWD`,
  `Performance`, and `Standard` (the decontented 2026 car). Tesla's 2026 "Premium RWD/AWD" names map to
  Long Range RWD/AWD so year-over-year buckets stay comparable. `trim_confidence` is `low` when the source
  gave no usable trim string and the pipeline fell back on horsepower / model-year heuristics (Tesla's VIN
  cannot distinguish RWD from Long Range RWD); the dashboard marks those with "?".
* **Model year** comes from the VIN (position 10) when it disagrees with the dealer's listing.
* **MSRP** is the base price at the start of the model year, before destination and order fees, from
  `scraper/highland/msrp.py` (with the notable mid-year changes in `NOTES`).
* **Distance** is straight-line miles from 77479 (CarMax reports its own driving distance).
* **Shipping** is only known for CarMax (its transfer fee quote to 77479). `effective_price` =
  price + shipping; the dashboard has a toggle to compare on that basis.
* **Changes.** `new` (first seen), `price_drop` / `price_up`, `removed` (not in the source's latest
  successful run), `returned` (came back after being removed). Removal is skipped when a source fails or
  returns a suspiciously small result (0 when it had ≥3, or a >60% drop), so an outage never shows up as
  "everything sold". Three consecutive genuine-zero runs are accepted.

## Sources

Status as of 2026-09-02. "Works, 0 today" means the scraper is validated against the site's live markup but the
dealer had no 2024+ Model 3 within 100 miles of 77479 on that day; those sources will show cars when stock appears.

| Source | Coverage | Status | How it is read | Notes / workarounds |
|---|---|---|---|---|
| **CarMax** | nationwide (38 cars) | reliable | `carmax.com/cars/api/search/run`, the JSON endpoint the search page uses; 1 page of 100 | Akamai rejects plain `requests`/`curl`; curl_cffi Chrome TLS impersonation passes locally and from GitHub runners. Shipping = CarMax's `transferFee` to 77479; "available elsewhere" cars have no quote and are marked not shippable. Reserved / coming-soon cars are dropped. |
| **Tesla used inventory** | 100 mi (12 cars) | works from CI, flaky elsewhere | `tesla.com/inventory/api/v4/inventory-results` (same call the inventory page makes) | Akamai challenges most fingerprints (`429 cpr_chlge` / 403). An iOS Safari 17 fingerprint passes from GitHub Actions; the module walks a ladder of fingerprints and fails cleanly if all are challenged, so listings are never marked sold because of a block. Listing URL `tesla.com/m3/order/<VIN>?titleStatus=used`. The API gives the delivery-centre coordinates but no name, so the location is reverse-geocoded. |
| **Autotrader** | 100 mi, many Houston dealers (15 cars) | reliable | `__NEXT_DATA__` JSON embedded in the search-results page; robots allows the SRP and VDP paths | Drops "market extension" long-haul listings beyond 100 mi and "call for price" cars. Includes franchise dealers, independents and Autotrader's private-seller exchange, so it is the best single view of local non-CarMax stock. |
| **AutoNation** | 100 mi (2 cars) | works | POST to the SRP's own JSON search API (`/v2/api/sitecore/SearchResultPage/Search`) with the static verification token from its bundle | Cloudflare challenges the homepage and made-up paths but serves this endpoint and the VDPs normally; if that changes the source fails with a 403 and nothing is bypassed. |
| **Carvana** | nationwide delivery (18–21 cars) | works, limited | Server-rendered `carvana.com/cars/tesla-model-3?sortBy=NewestYear&page=N`, the only robots-allowed listing path (search, filters and inventory APIs are all disallowed) | Delivery fee and physical location for 77479 cannot be obtained from allowed pages, so Carvana cars show no distance or shipping cost; the fee is quoted at checkout. Pages are walked newest-year-first and stop at the first pre-2024 car. |
| **EchoPark** | 100 mi: Stafford, Houston North (0 today) | works, 0 today | `__STORE__` JSON in the server-rendered search page, with EchoPark's own zip cookie set to 77479 | The SPA's JSON endpoints answer once then 403/429 and are not used. Advertised price includes EchoPark's $499 doc fee (split kept in `extra`). |
| **Sewell** | 100 mi: Audi/INFINITI North Houston, Audi Sugar Land, Cadillac of Houston, Mercedes West Houston (0 today) | works, 0 today | Inventory sitemap filtered by slug, then each matching vehicle page's embedded JSON | The pre-owned search runs on Algolia client-side and their `/llm/inventory/` feed ignores filters, so the sitemap route is used (one 2.3 MB download per run). Group-wide Highlands are usually at DFW stores, which are dropped as >100 mi. |
| **Hertz Car Sales** | 100 mi (0 today) | works, 0 today | Dealer.com `ws-inv-data` state embedded in the SRP (the legacy JSON API is retired) | Zero listings is the normal state until Hertz de-fleets Highland cars. |
| **Enterprise Car Sales** | 100 mi (0 today) | works, 0 today | `/vdp-sitemap.xml` filtered by VIN, then each vehicle page's `vdp-page-config` JSON | The search UI talks to an authenticated api.ehi.com service, which is not used. No Highland cars nationally today. |
| CarGurus | — | **dropped** | — | robots.txt disallows `/Cars/inventorylisting/`, `/Cars/search`, `/Cars/api/` and paging of the one allowed SEO page, which also ignores the zip. |
| Cars.com | — | **dropped** | — | robots.txt disallows `/shopping/results/` (the search results page). |

## Caveats

* Prices are dealer asking prices before tax, title and fees; CarMax and Tesla list no-haggle prices,
  others may negotiate.
* Medians are computed over the currently active listings in each year+trim bucket and move as inventory
  changes; buckets with fewer than 2 cars are flagged as thin.
* A listing can sell between refreshes — the dealer page is the source of truth.
