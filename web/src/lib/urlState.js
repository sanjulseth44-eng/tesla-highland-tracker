// Filter state persisted in the URL query string (shareable links, back/forward safe).
import { useCallback, useEffect, useState } from 'react'

export const DEFAULT_STATE = {
  years: [], // [2024, 2025]
  trims: [], // ['Long Range AWD']
  sources: [], // ['carmax']
  scope: 'all', // 'all' | 'local' | 'carmax'
  maxMi: '', // number as string, '' = any
  maxPrice: '',
  removed: false, // include removed/sold cars
  q: '', // search text
  eff: false, // effective price mode
  view: '', // '' = auto by screen width, 'table' | 'cards'
  sort: 'price',
  dir: 'asc',
}

const SCOPES = new Set(['all', 'local', 'carmax'])
const VIEWS = new Set(['', 'table', 'cards'])

function list(v) {
  return v ? v.split(',').map((s) => s.trim()).filter(Boolean) : []
}

function numStr(v) {
  if (v == null || v === '') return ''
  const n = Number(v)
  return Number.isFinite(n) && n > 0 ? String(Math.round(n)) : ''
}

export function parseState(search) {
  const p = new URLSearchParams(search)
  const s = { ...DEFAULT_STATE }
  s.years = list(p.get('year')).map(Number).filter(Number.isFinite)
  s.trims = list(p.get('trim'))
  s.sources = list(p.get('src'))
  s.scope = SCOPES.has(p.get('scope')) ? p.get('scope') : 'all'
  s.maxMi = numStr(p.get('maxmi'))
  s.maxPrice = numStr(p.get('maxprice'))
  s.removed = p.get('removed') === '1'
  s.q = p.get('q') || ''
  s.eff = p.get('eff') === '1'
  s.view = VIEWS.has(p.get('view')) ? p.get('view') : ''
  s.sort = p.get('sort') || DEFAULT_STATE.sort
  s.dir = p.get('dir') === 'desc' ? 'desc' : 'asc'
  return s
}

export function serializeState(s) {
  const p = new URLSearchParams()
  if (s.years.length) p.set('year', s.years.join(','))
  if (s.trims.length) p.set('trim', s.trims.join(','))
  if (s.sources.length) p.set('src', s.sources.join(','))
  if (s.scope !== 'all') p.set('scope', s.scope)
  if (s.maxMi) p.set('maxmi', s.maxMi)
  if (s.maxPrice) p.set('maxprice', s.maxPrice)
  if (s.removed) p.set('removed', '1')
  if (s.q) p.set('q', s.q)
  if (s.eff) p.set('eff', '1')
  if (s.view) p.set('view', s.view)
  if (s.sort !== DEFAULT_STATE.sort || s.dir !== DEFAULT_STATE.dir) {
    p.set('sort', s.sort)
    p.set('dir', s.dir)
  }
  return p.toString()
}

/** Count of active (non-default) filter facets, for the "Filters (n)" badge. */
export function activeFilterCount(s) {
  let n = 0
  if (s.years.length) n++
  if (s.trims.length) n++
  if (s.sources.length) n++
  if (s.scope !== 'all') n++
  if (s.maxMi) n++
  if (s.maxPrice) n++
  if (s.removed) n++
  if (s.q) n++
  return n
}

export function useUrlState() {
  const [state, setState] = useState(() => parseState(window.location.search))

  useEffect(() => {
    const qs = serializeState(state)
    const url = window.location.pathname + (qs ? `?${qs}` : '') + window.location.hash
    const current = window.location.pathname + window.location.search + window.location.hash
    if (url !== current) window.history.replaceState(null, '', url)
  }, [state])

  useEffect(() => {
    const onPop = () => setState(parseState(window.location.search))
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const patch = useCallback((partial) => setState((prev) => ({ ...prev, ...(typeof partial === 'function' ? partial(prev) : partial) })), [])
  const reset = useCallback(() => setState((prev) => ({ ...DEFAULT_STATE, eff: prev.eff, view: prev.view })), [])

  return [state, patch, reset]
}
