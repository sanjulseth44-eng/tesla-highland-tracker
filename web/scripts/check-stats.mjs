// Sanity checks for the pure stats helpers. Run: node scripts/check-stats.mjs
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { bucketStats, deltaVsMedian, discountPct, enrich, median, sortedBuckets } from '../src/lib/stats.js'
import { buildModel } from '../src/lib/model.js'

assert.equal(median([1, 2, 3, 4]), 2.5, 'even-length median')
assert.equal(median([3, 1, 2]), 2, 'odd-length median')
assert.equal(median([]), null, 'empty median')
assert.equal(median([null, undefined, NaN, 5]), 5, 'median ignores non-numbers')

const gen = '2026-09-02T20:00:00+00:00'
const fake = [
  { id: 1, year: 2025, trim: 'Long Range AWD', price: 40000, effective_price: 41000, msrp: 47490, mileage: 10000, status: 'active', first_seen: gen, price_history: [{ at: gen, price: 40000 }] },
  {
    id: 2, year: 2025, trim: 'Long Range AWD', price: 44000, effective_price: 44000, msrp: 47490, mileage: 20000, status: 'active', first_seen: '2026-08-20T00:00:00+00:00',
    price_history: [{ at: '2026-08-20T00:00:00+00:00', price: 45000 }, { at: '2026-09-01T00:00:00+00:00', price: 44000 }],
  },
  { id: 3, year: 2024, trim: 'RWD', price: 30000, effective_price: null, msrp: null, mileage: null, shipping_cost: null, status: 'active', first_seen: '2026-08-01T00:00:00+00:00', price_history: [] },
]

const b = bucketStats(fake, 'list')
const lr = b.get('2025|Long Range AWD')
assert.equal(lr.n, 2)
assert.equal(lr.median, 42000)
assert.equal(lr.min, 40000)
assert.equal(lr.max, 44000)
assert.equal(lr.medianMileage, 15000)
assert.equal(lr.thin, false)
assert.ok(Math.abs(lr.medianDiscount - ((47490 - 42000) / 47490) * 100) < 1e-9, 'median discount')
const rwd = b.get('2024|RWD')
assert.equal(rwd.n, 1)
assert.equal(rwd.thin, true)
assert.equal(rwd.median, 30000)
assert.equal(rwd.medianMileage, null, 'null mileage -> null median, not NaN')
assert.equal(rwd.medianDiscount, null, 'null msrp -> null discount, not NaN')
assert.equal(bucketStats([], 'list').size, 0, 'empty input -> no buckets')

const be = bucketStats(fake, 'effective')
assert.equal(be.get('2025|Long Range AWD').median, 42500, 'effective-mode median')
assert.equal(be.get('2024|RWD').median, 30000, 'null effective_price falls back to price')

assert.deepEqual(deltaVsMedian(null, 1), { abs: null, pct: null })
assert.deepEqual(deltaVsMedian(41000, 42000), { abs: -1000, pct: (-1000 / 42000) * 100 })
assert.equal(discountPct(null, 30000), null)
assert.equal(discountPct(40000, null), null)

const e = fake.map((l) => enrich(l, 'list', b, gen))
assert.equal(e[0].isNew, true)
assert.equal(e[1].isNew, false)
assert.equal(e[1].recentDrop?.kind, 'drop')
assert.equal(e[0].recentDrop, null)
assert.equal(e[2].discount, null)
assert.equal(e[2].deltaAbs, 0)
for (const l of e) for (const k of ['p', 'deltaAbs', 'deltaPct', 'discount']) assert.ok(l[k] === null || Number.isFinite(l[k]), `${k} must be finite or null`)
assert.deepEqual(sortedBuckets(b).map((x) => x.key), ['2025|Long Range AWD', '2024|RWD'])

// Whole-model build against the real export when present: no NaN anywhere that the UI reads.
const dataPath = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', 'data', 'latest.json')
if (existsSync(dataPath)) {
  const data = JSON.parse(readFileSync(dataPath, 'utf8'))
  for (const mode of ['list', 'effective']) {
    const m = buildModel(data, mode)
    assert.equal(m.listings.length, data.listings.length)
    for (const l of m.listings) for (const k of ['p', 'deltaAbs', 'deltaPct', 'discount']) assert.ok(l[k] === null || Number.isFinite(l[k]), `${mode}: ${k} NaN on listing ${l.id}`)
    for (const bk of m.buckets.values()) for (const k of ['median', 'min', 'max', 'medianMileage', 'medianDiscount']) assert.ok(bk[k] === null || Number.isFinite(bk[k]), `${mode}: bucket ${bk.key} ${k} NaN`)
    for (const [k, v] of Object.entries(m.kpis)) assert.ok(Number.isInteger(v), `kpi ${k} must be an integer`)
    assert.ok(m.sources.every((s) => m.sourceColors[s.key]), 'every source has a colour')
  }
  console.log(`check-stats: real data OK (${data.listings.length} listings, ${new Set(data.listings.map((l) => `${l.year}|${l.trim}`)).size} buckets)`)
} else {
  console.log('check-stats: data/latest.json not found, skipped real-data checks')
}
console.log('check-stats: all assertions passed')
