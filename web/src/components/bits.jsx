// Small presentational pieces shared by the table, cards, chart tooltip and change log.
import { trimColor } from '../lib/colors.js'
import { fmtMoney, fmtPct, fmtSignedMoney } from '../lib/format.js'

export function OpenLink({ url, className = 'btn sm', children = 'Open listing ↗', title }) {
  if (!url) return <span className={`${className} disabled`}>{children}</span>
  return (
    <a className={className} href={url} target="_blank" rel="noopener noreferrer" title={title || 'Opens the dealer page in a new tab'}>
      {children}
    </a>
  )
}

export function SourceTag({ source, label, colors }) {
  const c = (colors && colors[source]) || '#9aa0b0'
  return (
    <span className="tag" style={{ '--c': c }}>
      <i className="dot" />
      {label || source || '—'}
    </span>
  )
}

export function TrimTag({ trim, confidence, raw }) {
  const low = confidence === 'low'
  return (
    <span className="trim" style={{ '--c': trimColor(trim) }}>
      <i className="dot" />
      {trim || 'Unknown trim'}
      {low && (
        <abbr className="q" title={`Trim is a low-confidence guess${raw ? ` (listing says "${raw}")` : ''}`}>
          ?
        </abbr>
      )}
    </span>
  )
}

export function Badges({ l }) {
  const any = l.isRemoved || l.isNew || l.recentDrop
  if (!any) return null
  return (
    <span className="badges">
      {l.isRemoved && (
        <span className="badge removed" title={l.removed_at ? `No longer listed (removed ${l.removed_at})` : 'No longer listed'}>
          Removed
        </span>
      )}
      {l.isNew && !l.isRemoved && (
        <span className="badge new" title="First seen within 24h of this refresh">
          New
        </span>
      )}
      {l.recentDrop && (
        <span className="badge drop" title={`${fmtMoney(l.recentDrop.from)} → ${fmtMoney(l.recentDrop.to)} in the last 7 days`}>
          Price drop
        </span>
      )}
    </span>
  )
}

/** Delta vs the year+trim median: green below, red above. */
export function Delta({ abs, pct, n }) {
  if (abs == null) return <span className="mut">—</span>
  const cls = abs < 0 ? 'good' : abs > 0 ? 'bad' : 'zero'
  const thin = n != null && n < 2
  const title = thin ? 'Only active listing in its year+trim bucket, so the median is itself' : 'Versus the median of active listings with the same year and trim'
  return (
    <span className={`delta ${cls}`} title={title}>
      {fmtSignedMoney(abs)} <small>({fmtPct(pct)})</small>
      {thin && <small className="mut"> thin</small>}
    </span>
  )
}

/** MSRP discount: positive = below MSRP (green). */
export function Discount({ pct }) {
  if (pct == null) return <span className="mut">—</span>
  const cls = pct > 0 ? 'good' : pct < 0 ? 'bad' : 'zero'
  return <span className={`delta ${cls}`}>{pct >= 0 ? `${fmtPct(pct, 1, false)} off` : `${fmtPct(-pct, 1, false)} over`}</span>
}

/** The price in the current mode, with the other basis as a secondary line when they differ. */
export function PriceCell({ l, mode, big }) {
  const eff = l.effective_price
  const list = l.price
  const differs = typeof eff === 'number' && typeof list === 'number' && eff !== list
  return (
    <span className={`price ${big ? 'big' : ''}`}>
      <b>{fmtMoney(l.p)}</b>
      {mode === 'effective' && <small className="mut">effective{differs ? ` · list ${fmtMoney(list)}` : ''}</small>}
      {mode !== 'effective' && differs && <small className="mut">{fmtMoney(eff)} incl. shipping</small>}
    </span>
  )
}

const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1)

export function shippingText(l) {
  const c = l.shipping_cost
  const note = l.shipping_note
  if (typeof c === 'number' && Number.isFinite(c)) {
    if (c === 0) return note ? cap(note) : 'Free'
    return `${fmtMoney(c)}${note ? ` ${note}` : ''}`
  }
  return note ? cap(note) : '—'
}
