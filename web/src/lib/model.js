// Builds everything the UI needs from a latest.json payload and a price mode. Pure (no React).
import { bucketStats, enrich, hoursBetween, trimRank } from './stats.js'
import { buildSourceColors } from './colors.js'
import { ageDays, dayKey } from './format.js'

export const STALE_DAYS = 2

export function buildModel(data, mode = 'list', now = Date.now()) {
  const generatedAt = data.generated_at
  const raw = Array.isArray(data.listings) ? data.listings : []

  // Medians come from ACTIVE listings only, in the current price mode, ignoring UI filters.
  const buckets = bucketStats(raw.filter((l) => l.status === 'active'), mode)
  const listings = raw.map((l) => enrich(l, mode, buckets, generatedAt))
  const active = listings.filter((l) => !l.isRemoved)

  const years = [...new Set(raw.map((l) => l.year).filter((y) => y != null))].sort((a, b) => b - a)
  const trims = [...new Set(raw.map((l) => l.trim).filter(Boolean))].sort((a, b) => trimRank(a) - trimRank(b) || a.localeCompare(b))

  // Sources: whatever the scraper reports, plus any source key that only shows up on listings.
  const srcMap = new Map()
  for (const s of data.sources || []) if (s && s.key) srcMap.set(s.key, { ...s })
  for (const l of raw) {
    if (l.source && !srcMap.has(l.source)) {
      srcMap.set(l.source, { key: l.source, label: l.source_label || l.source, kind: l.source_kind || 'local', ok: null, count: null, notes: [] })
    }
  }
  const sources = [...srcMap.values()].map((s) => {
    const age = s.last_ok_at ? ageDays(s.last_ok_at, now) : null
    return { ...s, stale: age == null || age > STALE_DAYS }
  })
  const sourceColors = buildSourceColors(sources.map((s) => s.key))

  const changes = [...(data.changes || [])].sort((a, b) => String(b.at).localeCompare(String(a.at)) || (b.id ?? 0) - (a.id ?? 0))
  const genDay = dayKey(generatedAt)

  const dropIds = new Set()
  for (const c of changes) {
    if (c.kind !== 'price_drop') continue
    const h = hoursBetween(c.at, generatedAt)
    if (h != null && h >= -1 && h <= 7 * 24) dropIds.add(c.listing_id ?? c.vin ?? c.id)
  }

  const kpis = {
    active: active.length,
    local: active.filter((l) => l.is_local).length,
    carmax: active.filter((l) => l.source_kind === 'carmax').length,
    newToday: listings.filter((l) => dayKey(l.first_seen) === genDay).length,
    drops7d: dropIds.size,
    removedRecent: data.stats?.removed_recent ?? listings.filter((l) => l.isRemoved).length,
  }

  return {
    generatedAt,
    genDay,
    mode,
    home: data.home || { zip: '77479', radius_mi: 100, min_year: 2024 },
    windowDays: data.change_window_days ?? 14,
    listings,
    active,
    byId: new Map(listings.map((l) => [l.id, l])),
    buckets,
    years,
    trims,
    sources,
    sourceColors,
    changes,
    kpis,
    msrp: Array.isArray(data.msrp) ? data.msrp : [],
    msrpNotes: data.msrp_notes || {},
  }
}
