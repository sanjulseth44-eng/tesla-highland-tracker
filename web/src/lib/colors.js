// Color tokens for data marks. Palette fixed by the user (see styles.css for the UI tokens).
// Text never wears these colors; they go on dots, tags, borders and chart marks.

export const TRIM_COLORS = {
  'Long Range AWD': '#4f8ef7',
  Performance: '#f76d6d',
  'Long Range RWD': '#b57ef7',
  RWD: '#e8b53a',
  Standard: '#38c172',
}

// Secondary (shape) encoding for trims: the fixed palette's blue and purple collapse under
// protanopia, so each trim also gets its own symbol in the scatter chart and legend.
export const TRIM_SHAPES = {
  'Long Range AWD': 'circle',
  Performance: 'triangle',
  'Long Range RWD': 'diamond',
  RWD: 'square',
  Standard: 'hexagon',
}

export const FALLBACK_TRIM_COLOR = '#9aa0b0'

export function trimColor(trim) {
  return TRIM_COLORS[trim] || FALLBACK_TRIM_COLOR
}

export function trimShape(trim) {
  return TRIM_SHAPES[trim] || 'circle'
}

export const SOURCE_FIXED = {
  carmax: '#f3b23e', // amber
  tesla: '#e82127', // Tesla red
}
export const SOURCE_CYCLE = ['#38c172', '#4f8ef7', '#b57ef7', '#f76d6d', '#9aa0b0']

function hashKey(s) {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619) >>> 0
  }
  return h
}

/**
 * Deterministic source -> color map. Fixed colors for CarMax and Tesla; every other source
 * key hashes to a slot in SOURCE_CYCLE, taking the next free slot on collision (keys are
 * processed in sorted order, so the result depends only on the set of keys).
 */
export function buildSourceColors(keys) {
  const map = {}
  const taken = new Set()
  const others = [...new Set(keys)].filter((k) => k && !SOURCE_FIXED[k]).sort()
  for (const k of keys) if (SOURCE_FIXED[k]) map[k] = SOURCE_FIXED[k]
  for (const k of others) {
    let i = hashKey(k) % SOURCE_CYCLE.length
    let tries = 0
    while (taken.has(i) && tries < SOURCE_CYCLE.length) {
      i = (i + 1) % SOURCE_CYCLE.length
      tries++
    }
    taken.add(i)
    map[k] = SOURCE_CYCLE[i]
  }
  return map
}

/** rgba() string from a hex color. */
export function alpha(hex, a) {
  const h = hex.replace('#', '')
  const n = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16)
  const r = (n >> 16) & 255
  const g = (n >> 8) & 255
  const b = n & 255
  return `rgba(${r},${g},${b},${a})`
}
