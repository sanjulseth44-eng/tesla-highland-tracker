// Pure statistics helpers for the dashboard. No React, no DOM.

// Canonical trim order used for sorting, legends and the market table.
export const TRIM_ORDER = ['RWD', 'Long Range RWD', 'Long Range AWD', 'Performance', 'Standard']

export function trimRank(trim) {
  const i = TRIM_ORDER.indexOf(trim)
  return i === -1 ? TRIM_ORDER.length : i
}

/** Median of the finite numbers in `values`; null when there are none. */
export function median(values) {
  const v = values.filter((x) => typeof x === 'number' && Number.isFinite(x)).sort((a, b) => a - b)
  if (!v.length) return null
  const mid = v.length >> 1
  return v.length % 2 ? v[mid] : (v[mid - 1] + v[mid]) / 2
}

export function min(values) {
  const v = values.filter((x) => typeof x === 'number' && Number.isFinite(x))
  return v.length ? Math.min(...v) : null
}

export function max(values) {
  const v = values.filter((x) => typeof x === 'number' && Number.isFinite(x))
  return v.length ? Math.max(...v) : null
}

/** Price used everywhere for a listing given the price mode ('list' | 'effective'). */
export function priceOf(listing, mode) {
  if (mode === 'effective') return listing.effective_price ?? listing.price ?? null
  return listing.price ?? null
}

export function bucketKey(year, trim) {
  return `${year}|${trim}`
}

/** Percent below MSRP (positive = discount, negative = above MSRP). */
export function discountPct(msrp, price) {
  if (!msrp || price == null || !Number.isFinite(price)) return null
  return ((msrp - price) / msrp) * 100
}

/**
 * Per year+trim market stats over `listings` (callers pass the ACTIVE listings).
 * Returns a Map keyed by bucketKey(year, trim) with:
 * { year, trim, n, median, min, max, medianMileage, medianDiscount, thin }
 */
export function bucketStats(listings, mode) {
  const groups = new Map()
  for (const l of listings) {
    if (l.year == null || !l.trim) continue
    const k = bucketKey(l.year, l.trim)
    if (!groups.has(k)) groups.set(k, { year: l.year, trim: l.trim, items: [] })
    groups.get(k).items.push(l)
  }
  const out = new Map()
  for (const [k, g] of groups) {
    const prices = g.items.map((l) => priceOf(l, mode))
    out.set(k, {
      key: k,
      year: g.year,
      trim: g.trim,
      n: g.items.length,
      median: median(prices),
      min: min(prices),
      max: max(prices),
      medianMileage: median(g.items.map((l) => l.mileage)),
      medianDiscount: median(g.items.map((l) => discountPct(l.msrp, priceOf(l, mode)))),
      thin: g.items.length < 2,
    })
  }
  return out
}

/** Sort bucket stats by year desc, then canonical trim order. */
export function sortedBuckets(buckets) {
  return [...buckets.values()].sort((a, b) => b.year - a.year || trimRank(a.trim) - trimRank(b.trim))
}

/** Delta of `price` against a bucket median: { abs, pct } (pct relative to the median). */
export function deltaVsMedian(price, med) {
  if (price == null || med == null || !Number.isFinite(price) || !Number.isFinite(med)) {
    return { abs: null, pct: null }
  }
  const abs = price - med
  return { abs, pct: med ? (abs / med) * 100 : null }
}

/** Sorted copy of a price history (oldest first). */
export function sortedHistory(history) {
  return [...(history || [])].sort((a, b) => String(a.at).localeCompare(String(b.at)))
}

/** Most recent price movement in a history: { kind: 'drop'|'up', at, from, to } or null. */
export function lastPriceChange(history) {
  const h = sortedHistory(history)
  if (h.length < 2) return null
  const prev = h[h.length - 2]
  const last = h[h.length - 1]
  if (prev.price == null || last.price == null || prev.price === last.price) return null
  return { kind: last.price < prev.price ? 'drop' : 'up', at: last.at, from: prev.price, to: last.price }
}

const HOUR = 3600 * 1000
const DAY = 24 * HOUR

export function hoursBetween(aIso, bIso) {
  const a = Date.parse(aIso)
  const b = Date.parse(bIso)
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null
  return (b - a) / HOUR
}

/** first_seen within the last `hours` of `generatedAt`. */
export function isNewListing(listing, generatedAt, hours = 24) {
  const h = hoursBetween(listing.first_seen, generatedAt)
  return h != null && h >= -1 && h <= hours
}

/** The last price change was a drop and it happened within `days` of `generatedAt`. */
export function recentPriceDrop(listing, generatedAt, days = 7) {
  const ch = lastPriceChange(listing.price_history)
  if (!ch || ch.kind !== 'drop') return null
  const h = hoursBetween(ch.at, generatedAt)
  if (h == null || h > days * 24 || h < -1) return null
  return ch
}

/** Attach computed fields (current price, deltas, badges, search blob) to a raw listing. */
export function enrich(listing, mode, buckets, generatedAt) {
  const p = priceOf(listing, mode)
  const bucket = buckets.get(bucketKey(listing.year, listing.trim)) || null
  const med = bucket ? bucket.median : null
  const { abs, pct } = deltaVsMedian(p, med)
  const drop = recentPriceDrop(listing, generatedAt, 7)
  return {
    ...listing,
    p,
    listPrice: listing.price,
    bucket,
    median: med,
    deltaAbs: abs,
    deltaPct: pct,
    discount: discountPct(listing.msrp, p),
    isNew: isNewListing(listing, generatedAt, 24),
    recentDrop: drop,
    lastChange: lastPriceChange(listing.price_history),
    isRemoved: listing.status !== 'active',
    trimLow: listing.trim_confidence === 'low',
    search: [listing.vin, listing.dealer, listing.city, listing.state, listing.source_label, listing.source_id, listing.trim_raw, listing.exterior_color]
      .filter(Boolean)
      .join(' ')
      .toLowerCase(),
  }
}

/** A "nice" step size for axis ticks covering `range` with about `target` ticks. */
export function niceStep(range, target = 6) {
  if (!(range > 0)) return 1
  const raw = range / target
  const mag = Math.pow(10, Math.floor(Math.log10(raw)))
  const norm = raw / mag
  const step = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10
  return step * mag
}

/** Rounded axis bounds and tick positions for [lo, hi]. */
export function niceTicks(lo, hi, target = 6) {
  if (lo == null || hi == null || !Number.isFinite(lo) || !Number.isFinite(hi)) return { min: 0, max: 1, ticks: [0, 1] }
  if (lo === hi) {
    lo -= 1
    hi += 1
  }
  const step = niceStep(hi - lo, target)
  const minV = Math.floor(lo / step) * step
  const maxV = Math.ceil(hi / step) * step
  const ticks = []
  for (let v = minV; v <= maxV + step / 2; v += step) ticks.push(Math.round(v * 1e6) / 1e6)
  return { min: minV, max: maxV, ticks }
}
