import { useState } from 'react'
import { activeFilterCount } from '../lib/urlState.js'

const SCOPES = [
  ['all', 'All'],
  ['local', 'Local only'],
  ['carmax', 'CarMax only'],
]

export default function Filters({ state, patch, reset, model, shown, total }) {
  const [open, setOpen] = useState(false)
  const n = activeFilterCount(state)
  const toggleIn = (key, v) =>
    patch((s) => {
      const arr = s[key]
      return { [key]: arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v] }
    })

  return (
    <section className={`filters card ${open ? 'open' : ''}`} aria-label="Filters">
      <div className="frow">
        <input
          className="search"
          type="search"
          placeholder="Search VIN, dealer, city…"
          value={state.q}
          onChange={(e) => patch({ q: e.target.value })}
          aria-label="Search VIN, dealer or city"
        />
        <div className="seg" role="group" aria-label="Scope">
          {SCOPES.map(([v, label]) => (
            <button key={v} type="button" className={state.scope === v ? 'on' : ''} aria-pressed={state.scope === v} onClick={() => patch({ scope: v })}>
              {label}
            </button>
          ))}
        </div>
        <label className={`switch ${state.eff ? 'on' : ''}`} title="Show, compare and sort every price as list price + CarMax's shipping quote to 77479. Local listings are unchanged.">
          <input type="checkbox" checked={state.eff} onChange={(e) => patch({ eff: e.target.checked })} />
          <span>
            Effective price <small>(incl. CarMax shipping)</small>
          </span>
        </label>
        <button type="button" className="btn ghost more" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          {open ? 'Fewer filters' : 'More filters'}
          {n ? ` (${n})` : ''}
        </button>
        <button type="button" className="btn ghost" onClick={reset} disabled={!n} title="Clear all filters">
          Reset
        </button>
        <span className="count">
          {shown} / {total} listings shown
        </span>
      </div>
      <div className="frow frow-more">
        <Chips label="Year" items={model.years.map((y) => ({ value: y, label: String(y) }))} selected={state.years} onToggle={(v) => toggleIn('years', v)} />
        <Chips label="Trim" items={model.trims.map((t) => ({ value: t, label: t }))} selected={state.trims} onToggle={(v) => toggleIn('trims', v)} />
        <Chips
          label="Source"
          items={model.sources.map((s) => ({ value: s.key, label: s.label, color: model.sourceColors[s.key] }))}
          selected={state.sources}
          onToggle={(v) => toggleIn('sources', v)}
        />
        <label className="field">
          Max mileage
          <input type="number" inputMode="numeric" min="0" step="1000" placeholder="any" value={state.maxMi} onChange={(e) => patch({ maxMi: e.target.value })} />
        </label>
        <label className="field">
          Max price{state.eff ? ' (effective)' : ''}
          <input type="number" inputMode="numeric" min="0" step="500" placeholder="any" value={state.maxPrice} onChange={(e) => patch({ maxPrice: e.target.value })} />
        </label>
        <label className="check">
          <input type="checkbox" checked={state.removed} onChange={(e) => patch({ removed: e.target.checked })} />
          Include removed (sold)
        </label>
      </div>
    </section>
  )
}

function Chips({ label, items, selected, onToggle }) {
  if (!items.length) return null
  return (
    <div className="fgroup">
      <span className="flabel">{label}</span>
      <div className="chips">
        {items.map((it) => {
          const on = selected.includes(it.value)
          return (
            <button
              key={String(it.value)}
              type="button"
              className={`chip ${on ? 'on' : ''}`}
              aria-pressed={on}
              onClick={() => onToggle(it.value)}
              style={it.color ? { '--c': it.color } : undefined}
            >
              {it.color && <i className="dot" />}
              {it.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}
