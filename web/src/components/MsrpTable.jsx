import { trimRank } from '../lib/stats.js'
import { fmtMoney } from '../lib/format.js'

export default function MsrpTable({ msrp, notes }) {
  const years = [...new Set(msrp.map((m) => m.year))].sort((a, b) => a - b)
  const trims = [...new Set(msrp.map((m) => m.trim))].sort((a, b) => trimRank(a) - trimRank(b) || a.localeCompare(b))
  const lookup = new Map(msrp.map((m) => [`${m.year}|${m.trim}`, m.msrp]))
  const noteKeys = Object.keys(notes || {})
  const idx = new Map(noteKeys.map((k, i) => [k, i + 1]))
  const cellNotes = new Set(years.flatMap((y) => trims.map((t) => `${y} ${t}`)))
  const yearNotes = (y) => noteKeys.filter((k) => k.startsWith(`${y} `) && !cellNotes.has(k))
  const Sup = ({ k }) => (
    <sup title={notes[k]}>
      <a href={`#msrp-note-${idx.get(k)}`}>{idx.get(k)}</a>
    </sup>
  )
  return (
    <section className="card panel">
      <div className="panel-hd">
        <h2>MSRP reference</h2>
        <p className="cap">Base MSRP by model year and trim; the discount column compares each listing to its bucket's MSRP.</p>
      </div>
      {years.length === 0 ? (
        <p className="empty">No MSRP data.</p>
      ) : (
        <div className="tablewrap">
          <table className="tbl compact">
            <thead>
              <tr>
                <th>Year</th>
                {trims.map((t) => (
                  <th className="num" key={t}>
                    {t}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {years.map((y) => (
                <tr key={y}>
                  <td className="num">
                    {y}
                    {yearNotes(y).map((k) => (
                      <Sup key={k} k={k} />
                    ))}
                  </td>
                  {trims.map((t) => {
                    const v = lookup.get(`${y}|${t}`)
                    const nk = `${y} ${t}`
                    return (
                      <td className="num" key={t}>
                        {v == null ? <span className="mut">—</span> : fmtMoney(v)}
                        {idx.has(nk) && <Sup k={nk} />}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {noteKeys.length > 0 && (
        <ol className="notes">
          {noteKeys.map((k) => (
            <li key={k} id={`msrp-note-${idx.get(k)}`}>
              <b>{k}:</b> {notes[k]}
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
