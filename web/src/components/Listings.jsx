import { useState } from 'react'
import { fmtDate, fmtDateTimeShort, fmtDist, fmtMiles, fmtMoney, fmtSignedMoney } from '../lib/format.js'
import { sortedHistory } from '../lib/stats.js'
import { Badges, Delta, Discount, OpenLink, PriceCell, SourceTag, TrimTag, shippingText } from './bits.jsx'

const SORT_OPTS = [
  ['price', 'Price'],
  ['delta', 'Δ vs median ($)'],
  ['deltaPct', 'Δ vs median (%)'],
  ['discount', 'MSRP discount'],
  ['mileage', 'Mileage'],
  ['year', 'Year'],
  ['trim', 'Trim'],
  ['distance', 'Distance'],
  ['source', 'Source'],
  ['first_seen', 'First seen'],
  ['dealer', 'Dealer'],
]
const DEFAULT_DIR = { year: 'desc', first_seen: 'desc', discount: 'desc' }

export default function Listings({ rows, view, state, patch, mode, sourceColors, home }) {
  const [open, setOpen] = useState(() => new Set())
  const toggle = (id) =>
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  const sortBy = (key) => patch((s) => (s.sort === key ? { dir: s.dir === 'asc' ? 'desc' : 'asc' } : { sort: key, dir: DEFAULT_DIR[key] || 'asc' }))
  const zip = home?.zip || '77479'
  const shared = { rows, mode, sourceColors, zip, open, toggle, state, sortBy }

  return (
    <section className="card panel">
      <div className="list-hd">
        <h2>
          Listings <span className="mut">({rows.length})</span>
        </h2>
        <label className="field">
          Sort
          <select className="select" value={state.sort} onChange={(e) => patch({ sort: e.target.value, dir: DEFAULT_DIR[e.target.value] || 'asc' })}>
            {SORT_OPTS.map(([k, l]) => (
              <option key={k} value={k}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="btn ghost sm" onClick={() => patch({ dir: state.dir === 'asc' ? 'desc' : 'asc' })} title="Toggle sort direction">
          {state.dir === 'asc' ? '↑ ascending' : '↓ descending'}
        </button>
        <div className="seg" role="group" aria-label="View">
          <button type="button" className={view === 'table' ? 'on' : ''} onClick={() => patch({ view: 'table' })}>
            Table
          </button>
          <button type="button" className={view === 'cards' ? 'on' : ''} onClick={() => patch({ view: 'cards' })}>
            Cards
          </button>
        </div>
      </div>
      {mode === 'effective' && (
        <p className="cap notice">
          Prices below are <b>effective prices</b>: list price + CarMax's shipping quote to {zip}. Deltas, medians and sorting use the same basis.
        </p>
      )}
      {rows.length === 0 ? <p className="empty">No listings match the current filters.</p> : view === 'table' ? <Table {...shared} /> : <Cards {...shared} />}
    </section>
  )
}

function Th({ k, label, state, sortBy, num, title }) {
  const on = state.sort === k
  return (
    <th className={`sortable ${num ? 'num' : ''} ${on ? 'on' : ''}`} onClick={() => sortBy(k)} aria-sort={on ? (state.dir === 'asc' ? 'ascending' : 'descending') : 'none'} title={title}>
      {label}
      <i className="arr">{on ? (state.dir === 'asc' ? '▲' : '▼') : ''}</i>
    </th>
  )
}

function Table({ rows, mode, sourceColors, zip, open, toggle, state, sortBy }) {
  const priceLabel = mode === 'effective' ? 'Effective price' : 'Price'
  return (
    <div className="tablewrap">
      <table className="tbl listtable">
        <thead>
          <tr>
            <th aria-label="Expand" />
            <Th k="year" label="Year" state={state} sortBy={sortBy} num />
            <Th k="trim" label="Trim" state={state} sortBy={sortBy} />
            <Th k="price" label={priceLabel} state={state} sortBy={sortBy} num title={mode === 'effective' ? 'List price + CarMax shipping to 77479' : 'Advertised list price'} />
            <Th k="mileage" label="Mileage" state={state} sortBy={sortBy} num />
            <Th k="delta" label="Δ vs median" state={state} sortBy={sortBy} num title="Versus the median of active listings with the same year + trim (click again for %)" />
            <Th k="discount" label="MSRP · disc." state={state} sortBy={sortBy} num />
            <Th k="source" label="Source" state={state} sortBy={sortBy} />
            <Th k="dealer" label="Dealer" state={state} sortBy={sortBy} />
            <Th k="distance" label={`Location · from ${zip}`} state={state} sortBy={sortBy} />
            <th>Shipping</th>
            <Th k="first_seen" label="First seen" state={state} sortBy={sortBy} num />
            <th>Link</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((l) => {
            const isOpen = open.has(l.id)
            return [
              <tr key={l.id} className={`${l.isRemoved ? 'removed' : ''} ${isOpen ? 'open' : ''}`}>
                <td className="exp">
                  <button type="button" className="xbtn" onClick={() => toggle(l.id)} aria-expanded={isOpen} title="Price history">
                    {isOpen ? '−' : '+'}
                  </button>
                </td>
                <td className="num">{l.year}</td>
                <td>
                  <TrimTag trim={l.trim} confidence={l.trim_confidence} raw={l.trim_raw} />
                  <Badges l={l} />
                </td>
                <td className="num">
                  <PriceCell l={l} mode={mode} />
                </td>
                <td className="num">{fmtMiles(l.mileage)}</td>
                <td className="num">
                  <Delta abs={l.deltaAbs} pct={l.deltaPct} n={l.bucket?.n} />
                </td>
                <td className="num">
                  {fmtMoney(l.msrp)}
                  <div className="sub2">
                    <Discount pct={l.discount} />
                  </div>
                </td>
                <td>
                  <SourceTag source={l.source} label={l.source_label} colors={sourceColors} />
                </td>
                <td className="dealer">{l.dealer || '—'}</td>
                <td>
                  {[l.city, l.state].filter(Boolean).join(', ') || '—'}
                  <div className="sub2">{fmtDist(l.distance_mi)}</div>
                </td>
                <td>{shippingText(l)}</td>
                <td className="num" title={fmtDateTimeShort(l.first_seen)}>
                  {fmtDate(l.first_seen)}
                </td>
                <td>
                  <OpenLink url={l.url} />
                </td>
              </tr>,
              isOpen && (
                <tr key={`${l.id}-h`} className="hist-row">
                  <td colSpan={13}>
                    <PriceHistory history={l.price_history} />
                  </td>
                </tr>
              ),
            ]
          })}
        </tbody>
      </table>
    </div>
  )
}

function Cards({ rows, mode, sourceColors, zip, open, toggle }) {
  return (
    <div className="cards">
      {rows.map((l) => {
        const isOpen = open.has(l.id)
        return (
          <article className={`lcard ${l.isRemoved ? 'removed' : ''}`} key={l.id}>
            <div className="lc-hd">
              <div>
                <span className="yr">{l.year}</span>
                <TrimTag trim={l.trim} confidence={l.trim_confidence} raw={l.trim_raw} />
              </div>
              <Badges l={l} />
            </div>
            <div className="lc-price">
              <PriceCell l={l} mode={mode} big />
              <Delta abs={l.deltaAbs} pct={l.deltaPct} n={l.bucket?.n} />
            </div>
            <div className="lc-grid">
              <div>
                <small>Mileage</small>
                {fmtMiles(l.mileage)}
              </div>
              <div>
                <small>MSRP</small>
                {fmtMoney(l.msrp)}
              </div>
              <div>
                <small>Discount</small>
                <Discount pct={l.discount} />
              </div>
              <div>
                <small>From {zip}</small>
                {fmtDist(l.distance_mi)}
              </div>
              <div title={shippingText(l)}>
                <small>Shipping</small>
                {shippingText(l)}
              </div>
              <div title={fmtDateTimeShort(l.first_seen)}>
                <small>First seen</small>
                {fmtDate(l.first_seen)}
              </div>
            </div>
            <div className="lc-ft">
              <SourceTag source={l.source} label={l.source_label} colors={sourceColors} />
              <span>
                {l.dealer || '—'} · {[l.city, l.state].filter(Boolean).join(', ')}
              </span>
            </div>
            <div className="lc-actions">
              <button type="button" className="btn ghost sm" onClick={() => toggle(l.id)} aria-expanded={isOpen}>
                {isOpen ? 'Hide history' : 'Price history'}
              </button>
              <OpenLink url={l.url} />
            </div>
            {isOpen && <PriceHistory history={l.price_history} className="lc-hist" />}
          </article>
        )
      })}
    </div>
  )
}

export function PriceHistory({ history, className = '' }) {
  const h = sortedHistory(history)
  if (!h.length) {
    return (
      <div className={className}>
        <span className="mut">No price history recorded.</span>
      </div>
    )
  }
  return (
    <div className={className}>
      <div className="hist-t">
        Price history · {h.length} {h.length === 1 ? 'observation' : 'observations'}
      </div>
      <ul className="hist">
        {h.map((x, i) => {
          const prev = i ? h[i - 1].price : null
          const d = prev != null && x.price != null ? x.price - prev : null
          return (
            <li key={`${x.at}-${i}`}>
              <span className="h-at">{fmtDateTimeShort(x.at)}</span>
              <span className="mut">→</span>
              <b>{fmtMoney(x.price)}</b>
              {d != null && d !== 0 && <span className={`h-d delta ${d < 0 ? 'good' : 'bad'}`}>{fmtSignedMoney(d)}</span>}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
