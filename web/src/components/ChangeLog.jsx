import { useMemo, useState } from 'react'
import { dayKey, fmtDay, fmtDist, fmtMiles, fmtMoney, fmtPct, fmtSignedMoney, fmtTime } from '../lib/format.js'
import { OpenLink, SourceTag } from './bits.jsx'

const KINDS = {
  new: ['New', 'k-new'],
  price_drop: ['Price drop', 'k-drop'],
  price_up: ['Price up', 'k-up'],
  removed: ['Removed', 'k-rem'],
  returned: ['Returned', 'k-ret'],
}
const LIMIT = 12

export default function ChangeLog({ model }) {
  const { changes, generatedAt, genDay, windowDays, sourceColors, byId } = model
  const groups = useMemo(() => {
    const m = new Map()
    for (const c of changes) {
      const k = dayKey(c.at)
      if (!m.has(k)) m.set(k, { key: k, at: c.at, items: [] })
      m.get(k).items.push(c)
    }
    if (!m.has(genDay)) m.set(genDay, { key: genDay, at: generatedAt, items: [] })
    return [...m.values()].sort((a, b) => b.key.localeCompare(a.key))
  }, [changes, genDay, generatedAt])
  const [expanded, setExpanded] = useState(() => new Set())

  return (
    <section className="card panel">
      <div className="panel-hd">
        <h2>Change log</h2>
        <p className="cap">Last {windowDays} days · grouped by day in Houston time</p>
      </div>
      {groups.map((g) => {
        const today = g.key === genDay
        const isX = expanded.has(g.key)
        const shown = isX ? g.items : g.items.slice(0, LIMIT)
        return (
          <div className="cg" key={g.key}>
            <h3>
              {today ? 'Since last refresh' : fmtDay(g.at)}
              <span className="mut">
                {today ? `${fmtDay(g.at)} · ` : ''}
                {summary(g.items)}
              </span>
            </h3>
            {g.items.length === 0 ? (
              <p className="mut" style={{ margin: '4px 0' }}>
                No changes.
              </p>
            ) : (
              <ul className="clog">
                {shown.map((c) => (
                  <Entry key={c.id ?? `${c.listing_id}-${c.at}-${c.kind}`} c={c} colors={sourceColors} byId={byId} />
                ))}
              </ul>
            )}
            {g.items.length > LIMIT && (
              <button
                type="button"
                className="btn ghost sm"
                onClick={() =>
                  setExpanded((prev) => {
                    const n = new Set(prev)
                    if (n.has(g.key)) n.delete(g.key)
                    else n.add(g.key)
                    return n
                  })
                }
              >
                {isX ? 'Show fewer' : `Show all ${g.items.length}`}
              </button>
            )}
          </div>
        )
      })}
    </section>
  )
}

function summary(items) {
  if (!items.length) return 'no changes'
  const counts = {}
  for (const c of items) counts[c.kind] = (counts[c.kind] || 0) + 1
  return Object.entries(counts)
    .map(([k, n]) => `${n} ${(KINDS[k] || [k])[0].toLowerCase()}`)
    .join(' · ')
}

function priceText(c) {
  const oldP = c.old_price
  const newP = c.new_price
  switch (c.kind) {
    case 'price_drop':
    case 'price_up': {
      const d = oldP != null && newP != null ? newP - oldP : null
      const pct = d != null && oldP ? (d / oldP) * 100 : null
      return (
        <>
          <span className="mut">{fmtMoney(oldP)}</span> → <b>{fmtMoney(newP)}</b>{' '}
          {d != null && (
            <span className={`delta ${d < 0 ? 'good' : 'bad'}`}>
              {fmtSignedMoney(d)} ({fmtPct(pct)})
            </span>
          )}
        </>
      )
    }
    case 'removed':
      return (
        <>
          <span className="mut">last</span> <b>{fmtMoney(oldP ?? c.current_price ?? newP)}</b>
        </>
      )
    default:
      return <b>{fmtMoney(newP ?? c.current_price ?? oldP)}</b>
  }
}

function Entry({ c, colors, byId }) {
  const [label, cls] = KINDS[c.kind] || [c.kind, 'k-other']
  const url = c.url || byId.get(c.listing_id)?.url
  const loc = [c.city, c.state].filter(Boolean).join(', ')
  return (
    <li className={`ce ${cls}`}>
      <span className="ce-time">{fmtTime(c.at)}</span>
      <span className={`badge ${cls}`}>{label}</span>
      <span className="ce-car" title={c.vin || ''}>
        <b>
          {c.year} {c.trim || 'Model 3'}
        </b>{' '}
        · {fmtMiles(c.mileage)} · <SourceTag source={c.source} label={c.source_label} colors={colors} /> {c.dealer || ''}
        {loc ? ` · ${loc}` : ''}
        {c.distance_mi != null ? ` · ${fmtDist(c.distance_mi)}` : ''}
        {typeof c.shipping_cost === 'number' && c.shipping_cost > 0 ? ` · +${fmtMoney(c.shipping_cost)} ship` : ''}
      </span>
      <span className="ce-price">{priceText(c)}</span>
      <OpenLink url={url} className="btn ghost sm">
        Open ↗
      </OpenLink>
    </li>
  )
}
