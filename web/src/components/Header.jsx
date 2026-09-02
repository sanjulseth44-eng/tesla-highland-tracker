import { fmtDateTime, fmtDateTimeShort, fmtDay, relAge } from '../lib/format.js'

export default function Header({ model }) {
  const { generatedAt, kpis, sources, sourceColors, home, windowDays } = model
  const zip = home?.zip || '77479'
  const radius = home?.radius_mi ?? 100
  return (
    <header className="hdr">
      <div>
        <h1>
          Model 3 Highland Tracker <span className="sep">·</span> Sugar Land {zip}
        </h1>
        <p className="sub">
          Used {home?.min_year ?? 2024}+ Model 3 within {radius} mi of {zip}, plus CarMax nationwide. Last refresh{' '}
          <b>{fmtDateTime(generatedAt)}</b> <span className="mut">({relAge(generatedAt)})</span>
        </p>
      </div>
      <div className="kpis">
        <Kpi label="Active listings" value={kpis.active} sub={`${kpis.removedRecent} removed in the last ${windowDays} days`} />
        <Kpi
          label="Local vs CarMax"
          value={
            <>
              {kpis.local} <span className="kpi-sep">/</span> {kpis.carmax}
            </>
          }
          sub={`≤${radius} mi or local dealer / CarMax at any distance`}
        />
        <Kpi label="New since last refresh" value={kpis.newToday} sub={`first seen ${fmtDay(generatedAt)}`} accent="nw" />
        <Kpi label="Price drops, 7 days" value={kpis.drops7d} sub="distinct listings" accent="gd" />
      </div>
      <SourcesStrip sources={sources} colors={sourceColors} />
    </header>
  )
}

function Kpi({ label, value, sub, accent }) {
  return (
    <div className={`kpi ${accent ? `kpi-${accent}` : ''}`}>
      <div className="kpi-l">{label}</div>
      <div className="kpi-v">{value}</div>
      {sub && (
        <div className="kpi-s" title={sub}>
          {sub}
        </div>
      )}
    </div>
  )
}

function SourcesStrip({ sources, colors }) {
  if (!sources.length) return null
  return (
    <div className="srcs" aria-label="Source health">
      {sources.map((s) => {
        const err = s.ok === false
        const pending = s.ok == null && !s.last_run_at   // registered but never run yet
        const tip = [
          `${s.label} (${s.kind || 'local'})`,
          s.last_ok_at ? `last OK ${fmtDateTimeShort(s.last_ok_at)}` : 'no successful run yet',
          s.last_run_at ? `last run ${fmtDateTimeShort(s.last_run_at)}` : null,
          err ? `ERROR: ${s.error || 'unknown error'}` : null,
          pending ? 'pending: first scrape has not run yet' : s.stale ? 'stale: no successful run in 2+ days' : null,
          ...(s.notes || []),
        ]
          .filter(Boolean)
          .join('\n')
        return (
          <a className={`src ${err ? 'err' : pending ? 'pending' : 'ok'} ${s.stale && !pending ? 'stale' : ''}`} key={s.key} title={tip} href={s.homepage || undefined} target="_blank" rel="noopener noreferrer">
            <i className="dot" style={{ background: colors[s.key] }} />
            <span className="src-l">{s.label}</span>
            <b className="src-n">{s.count ?? '—'}</b>
            <em className={`pill ${err ? 'bad' : pending ? 'mut' : 'good'}`}>{err ? 'ERROR' : pending ? 'pending' : 'OK'}</em>
            {s.stale && !pending && <em className="pill warn">stale</em>}
          </a>
        )
      })}
    </div>
  )
}
