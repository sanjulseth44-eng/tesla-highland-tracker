// Pure filter + sort over enriched listings (see stats.enrich).
import { trimRank } from './stats.js'

export function applyFilters(listings, f) {
  const q = f.q.trim().toLowerCase()
  const maxMi = f.maxMi ? Number(f.maxMi) : null
  const maxPrice = f.maxPrice ? Number(f.maxPrice) : null
  return listings.filter((l) => {
    if (!f.removed && l.isRemoved) return false
    if (f.years.length && !f.years.includes(l.year)) return false
    if (f.trims.length && !f.trims.includes(l.trim)) return false
    if (f.sources.length && !f.sources.includes(l.source)) return false
    if (f.scope === 'local' && !l.is_local) return false
    if (f.scope === 'carmax' && l.source_kind !== 'carmax') return false
    if (maxMi != null && l.mileage != null && l.mileage > maxMi) return false
    if (maxPrice != null && l.p != null && l.p > maxPrice) return false
    if (q && !l.search.includes(q)) return false
    return true
  })
}

const SORTERS = {
  year: (l) => l.year,
  trim: (l) => trimRank(l.trim),
  price: (l) => l.p,
  mileage: (l) => l.mileage,
  delta: (l) => l.deltaAbs,
  deltaPct: (l) => l.deltaPct,
  discount: (l) => l.discount,
  distance: (l) => l.distance_mi,
  source: (l) => (l.source_label || l.source || '').toLowerCase(),
  first_seen: (l) => l.first_seen || '',
  dealer: (l) => (l.dealer || '').toLowerCase(),
}

export const SORT_KEYS = Object.keys(SORTERS)

export function sortListings(listings, sortKey, dir) {
  const get = SORTERS[sortKey] || SORTERS.price
  const sign = dir === 'desc' ? -1 : 1
  return [...listings].sort((a, b) => {
    const va = get(a)
    const vb = get(b)
    const na = va == null || va === ''
    const nb = vb == null || vb === ''
    if (na && nb) return 0
    if (na) return 1 // nulls last regardless of direction
    if (nb) return -1
    let c = 0
    if (typeof va === 'string' || typeof vb === 'string') c = String(va).localeCompare(String(vb))
    else c = va - vb
    if (c === 0) c = (a.p ?? 0) - (b.p ?? 0) // stable tiebreak on price
    return c * sign
  })
}
