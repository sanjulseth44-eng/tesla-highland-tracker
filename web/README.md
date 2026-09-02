# Model 3 Highland Tracker — web dashboard

Static React + Vite front end for the used-Tesla listings scraper in this repo. It reads one file,
`data/latest.json` (produced by the scraper), and renders KPIs, market medians, a sortable listing
table / card grid, a price-vs-mileage scatter, a change log and an MSRP reference. No server, no login;
it deploys to GitHub Pages under `/tesla-highland-tracker/`.

## Run locally

```sh
# 1. produce data/latest.json (repo root)
./.venv/bin/python scraper/run.py

# 2. install and start the dev server (this directory)
cd web
npm install
npm run dev          # http://localhost:5173/tesla-highland-tracker/
```

`predev` / `prebuild` copy `../data/latest.json` into `public/data/` (gitignored) so Vite serves it at
`<base>/data/latest.json`. Re-run the scraper and reload to pick up fresh data.

## Build and preview

```sh
npm run build                                   # -> web/dist
npm run preview -- --port 4173 --strictPort     # http://localhost:4173/tesla-highland-tracker/
```

Set `VITE_BASE=/` to build for a root deploy (`VITE_BASE=/ npm run build`).

## Checks

```sh
node scripts/check-stats.mjs   # asserts on the pure stats helpers + a NaN sweep over real data
```

## Layout

- `src/lib/stats.js` — medians, year+trim bucket stats, deltas, badges (pure, no React)
- `src/lib/model.js` — builds the view model (enriched listings, KPIs, source health, colours)
- `src/lib/filters.js`, `src/lib/urlState.js` — filter/sort logic and URL query-string persistence
- `src/lib/format.js` — money/percent/date formatting, all dates in America/Chicago
- `src/components/*` — Header (KPIs + source health), Filters, MarketPanel, PriceScatter (Recharts),
  Listings (table + cards + price history), ChangeLog, MsrpTable, Footer
- `src/styles.css` — dark instrument-cluster theme, mobile-first

Filter state (year, trim, source, scope, max mileage/price, include removed, search, effective-price
mode, view, sort) lives in the URL, so a filtered view is a shareable link.
