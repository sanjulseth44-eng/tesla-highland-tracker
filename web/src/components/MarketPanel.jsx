import { sortedBuckets } from '../lib/stats.js'
import { fmtInt, fmtMoney, fmtPct } from '../lib/format.js'
import { TrimTag } from './bits.jsx'

export default function MarketPanel({ buckets, mode }) {
  const rows = sortedBuckets(buckets)
  const basis = mode === 'effective' ? 'effective price (list + CarMax shipping to 77479)' : 'list price'
  return (
    <section className="card panel">
      <div className="panel-hd">
        <h2>Market medians by year + trim</h2>
        <p className="cap">
          Active listings only · <b>ignores the filters above</b> · basis: {basis} · n&lt;2 flagged thin
        </p>
      </div>
      {rows.length === 0 ? (
        <p className="empty">No active listings.</p>
      ) : (
        <div className="tablewrap">
          <table className="tbl compact">
            <thead>
              <tr>
                <th>Year</th>
                <th>Trim</th>
                <th className="num">n</th>
                <th className="num">Median</th>
                <th className="num">Min</th>
                <th className="num">Max</th>
                <th className="num">Median mi</th>
                <th className="num" title="Median of (MSRP − price) / MSRP across the bucket">
                  Med. MSRP disc.
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((b) => (
                <tr key={b.key} className={b.thin ? 'thin' : ''}>
                  <td className="num">{b.year}</td>
                  <td>
                    <TrimTag trim={b.trim} />
                    {b.thin && (
                      <span className="thinflag" title="Fewer than 2 active listings; median is not meaningful">
                        thin
                      </span>
                    )}
                  </td>
                  <td className="num">{b.n}</td>
                  <td className="num">
                    <b>{fmtMoney(b.median)}</b>
                  </td>
                  <td className="num">{fmtMoney(b.min)}</td>
                  <td className="num">{fmtMoney(b.max)}</td>
                  <td className="num">{b.medianMileage == null ? '—' : `${fmtInt(b.medianMileage)} mi`}</td>
                  <td className="num">{b.medianDiscount == null ? '—' : fmtPct(b.medianDiscount, 1, false)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
