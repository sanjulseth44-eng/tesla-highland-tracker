import { CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from 'recharts'
import { trimColor, trimShape } from '../lib/colors.js'
import { max, min, niceTicks, trimRank } from '../lib/stats.js'
import { fmtDist, fmtK, fmtMiles, fmtMoney, fmtPct, fmtSignedMoney } from '../lib/format.js'

const SURFACE = '#1a1d27'
const GRID = '#2a2f3f'
const MUTED = '#9aa0b0'

/** SVG path for a symbol centred at (0,0) with "radius" r. Trims get distinct symbols as a colour-independent cue. */
export function shapePath(kind, r) {
  switch (kind) {
    case 'square':
      return `M${-r},${-r}h${2 * r}v${2 * r}h${-2 * r}Z`
    case 'diamond':
      return `M0,${-r * 1.25}L${r * 1.25},0L0,${r * 1.25}L${-r * 1.25},0Z`
    case 'triangle':
      return `M0,${-r * 1.2}L${r * 1.15},${r * 0.85}L${-r * 1.15},${r * 0.85}Z`
    case 'hexagon': {
      const pts = []
      for (let i = 0; i < 6; i++) {
        const a = (Math.PI / 3) * i - Math.PI / 6
        pts.push(`${(r * 1.1 * Math.cos(a)).toFixed(2)},${(r * 1.1 * Math.sin(a)).toFixed(2)}`)
      }
      return `M${pts.join('L')}Z`
    }
    default:
      return `M${-r},0a${r},${r} 0 1,0 ${2 * r},0a${r},${r} 0 1,0 ${-2 * r},0Z`
  }
}

/** Ring = CarMax, filled = local dealer. Removed listings are dimmed. */
function Mark(props) {
  const { cx, cy, payload } = props
  if (cx == null || cy == null || !payload) return null
  const color = trimColor(payload.trim)
  const ring = payload.source_kind === 'carmax'
  const d = shapePath(trimShape(payload.trim), 5.5)
  return (
    <path
      d={d}
      transform={`translate(${cx},${cy})`}
      style={{
        fill: ring ? SURFACE : color,
        stroke: ring ? color : SURFACE,
        strokeWidth: ring ? 2 : 1.25,
        opacity: payload.isRemoved ? 0.4 : 0.95,
        cursor: payload.url ? 'pointer' : 'default',
      }}
    />
  )
}

function Tip({ active, payload, mode }) {
  if (!active || !payload || !payload.length) return null
  const l = payload[0].payload
  if (!l) return null
  return (
    <div className="tip">
      <b>
        {l.year} {l.trim}
      </b>
      <div>
        {fmtMoney(l.p)} {mode === 'effective' ? 'effective' : 'list'}
        {mode === 'effective' && l.effective_price !== l.price ? ` · list ${fmtMoney(l.price)}` : ''}
        {mode !== 'effective' && typeof l.effective_price === 'number' && l.effective_price !== l.price ? ` · ${fmtMoney(l.effective_price)} incl. ship` : ''}
      </div>
      <div>
        {fmtMiles(l.mileage)}
        {l.deltaAbs != null ? ` · ${fmtSignedMoney(l.deltaAbs)} (${fmtPct(l.deltaPct)}) vs median` : ''}
      </div>
      <div className="mut">
        {l.source_label || l.source} · {l.dealer}
      </div>
      <div className="mut">
        {[l.city, l.state].filter(Boolean).join(', ')} · {fmtDist(l.distance_mi)}
        {l.isRemoved ? ' · removed' : ''}
      </div>
      {l.url && <div className="mut">click to open listing ↗</div>}
    </div>
  )
}

export default function PriceScatter({ rows, mode }) {
  const pts = rows.filter((l) => typeof l.mileage === 'number' && typeof l.p === 'number')
  const trims = [...new Set(pts.map((l) => l.trim || 'Unknown'))].sort((a, b) => trimRank(a) - trimRank(b) || a.localeCompare(b))
  const x = niceTicks(min(pts.map((l) => l.mileage)), max(pts.map((l) => l.mileage)), 6)
  const y = niceTicks(min(pts.map((l) => l.p)), max(pts.map((l) => l.p)), 6)
  const openListing = (d) => {
    const p = d?.payload ?? d
    if (p?.url) window.open(p.url, '_blank', 'noopener,noreferrer')
  }
  const yLabel = mode === 'effective' ? 'Effective price (incl. CarMax shipping)' : 'List price'

  return (
    <section className="card panel">
      <div className="panel-hd">
        <h2>{yLabel} vs mileage</h2>
        <p className="cap">Follows the filters above · click a point to open the listing</p>
      </div>
      <div className="legend" aria-label="Legend">
        {trims.map((t) => (
          <span className="lg" key={t}>
            <svg width="14" height="14" aria-hidden="true">
              <path d={shapePath(trimShape(t), 5)} transform="translate(7,7)" fill={trimColor(t)} />
            </svg>
            {t}
          </span>
        ))}
        <span className="lg sep-l">
          <svg width="14" height="14" aria-hidden="true">
            <circle cx="7" cy="7" r="4.5" fill={SURFACE} stroke={MUTED} strokeWidth="2" />
          </svg>
          CarMax (ring)
        </span>
        <span className="lg">
          <svg width="14" height="14" aria-hidden="true">
            <circle cx="7" cy="7" r="5" fill={MUTED} />
          </svg>
          Local dealer (filled)
        </span>
      </div>
      {pts.length === 0 ? (
        <p className="empty">Nothing to plot with the current filters.</p>
      ) : (
        <div className="chart">
          <ResponsiveContainer width="100%" height="100%">
            <ScatterChart margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
              <CartesianGrid stroke={GRID} strokeDasharray="2 4" />
              <XAxis
                type="number"
                dataKey="mileage"
                name="Mileage"
                domain={[x.min, x.max]}
                ticks={x.ticks}
                tickFormatter={(v) => fmtK(v)}
                tick={{ fill: MUTED, fontSize: 11 }}
                axisLine={{ stroke: GRID }}
                tickLine={false}
                label={{ value: 'miles', position: 'insideBottomRight', offset: -2, fill: MUTED, fontSize: 11 }}
              />
              <YAxis
                type="number"
                dataKey="p"
                name={yLabel}
                domain={[y.min, y.max]}
                ticks={y.ticks}
                tickFormatter={(v) => fmtK(v, '$')}
                width={54}
                tick={{ fill: MUTED, fontSize: 11 }}
                axisLine={false}
                tickLine={false}
              />
              <ZAxis range={[90, 90]} />
              <Tooltip content={<Tip mode={mode} />} cursor={{ stroke: MUTED, strokeDasharray: '3 3' }} isAnimationActive={false} wrapperStyle={{ outline: 'none', zIndex: 5 }} />
              {trims.map((t) => (
                <Scatter
                  key={t}
                  name={t}
                  data={pts.filter((l) => (l.trim || 'Unknown') === t)}
                  fill={trimColor(t)}
                  shape={(p) => <Mark {...p} />}
                  onClick={openListing}
                  isAnimationActive={false}
                />
              ))}
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  )
}
