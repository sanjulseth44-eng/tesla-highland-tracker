// Formatting helpers. All dates render in Houston time (America/Chicago).
export const TZ = 'America/Chicago'

const money0 = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
const int0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })

const isNum = (n) => typeof n === 'number' && Number.isFinite(n)

export function fmtMoney(n) {
  return isNum(n) ? money0.format(n) : '—'
}

/** Signed money with a real minus sign: −$1,200 / +$800 / $0 */
export function fmtSignedMoney(n) {
  if (!isNum(n)) return '—'
  if (n === 0) return '$0'
  return (n < 0 ? '−' : '+') + money0.format(Math.abs(n))
}

export function fmtInt(n) {
  return isNum(n) ? int0.format(Math.round(n)) : '—'
}

export function fmtPct(n, digits = 1, signed = true) {
  if (!isNum(n)) return '—'
  const sign = n < 0 ? '−' : n > 0 && signed ? '+' : ''
  return `${sign}${Math.abs(n).toFixed(digits)}%`
}

export function fmtMiles(n) {
  return isNum(n) ? `${int0.format(Math.round(n))} mi` : '—'
}

export function fmtDist(n) {
  if (!isNum(n)) return '—'
  return n < 10 ? `${n.toFixed(1)} mi` : `${int0.format(Math.round(n))} mi`
}

/** Compact axis tick: 12k / $41k */
export function fmtK(n, prefix = '') {
  if (!isNum(n)) return ''
  if (Math.abs(n) >= 1000) {
    const k = n / 1000
    return `${prefix}${Number.isInteger(k) ? k : k.toFixed(1)}k`
  }
  return `${prefix}${int0.format(n)}`
}

function dtf(opts) {
  return new Intl.DateTimeFormat('en-US', { timeZone: TZ, ...opts })
}

const F_DATETIME = dtf({ month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' })
const F_DATETIME_SHORT = dtf({ month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
const F_DATE = dtf({ month: 'short', day: 'numeric' })
const F_DATE_YEAR = dtf({ month: 'short', day: 'numeric', year: 'numeric' })
const F_DAY = dtf({ weekday: 'short', month: 'short', day: 'numeric' })
const F_KEY = dtf({ year: 'numeric', month: '2-digit', day: '2-digit' })

function toDate(iso) {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : d
}

export function fmtDateTime(iso) {
  const d = toDate(iso)
  return d ? F_DATETIME.format(d) : '—'
}

export function fmtDateTimeShort(iso) {
  const d = toDate(iso)
  return d ? F_DATETIME_SHORT.format(d) : '—'
}

export function fmtDate(iso, withYear = false) {
  const d = toDate(iso)
  return d ? (withYear ? F_DATE_YEAR : F_DATE).format(d) : '—'
}

export function fmtDay(iso) {
  const d = toDate(iso)
  return d ? F_DAY.format(d) : '—'
}

/** Houston-local calendar day key, e.g. "2026-09-02". */
export function dayKey(iso) {
  const d = toDate(iso)
  if (!d) return ''
  const parts = Object.fromEntries(F_KEY.formatToParts(d).map((p) => [p.type, p.value]))
  return `${parts.year}-${parts.month}-${parts.day}`
}

/** "just now" / "35m ago" / "2h ago" / "3d ago" */
export function relAge(iso, now = Date.now()) {
  const d = toDate(iso)
  if (!d) return ''
  const s = Math.max(0, (now - d.getTime()) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  return `${Math.round(s / 86400)}d ago`
}

export function ageDays(iso, now = Date.now()) {
  const d = toDate(iso)
  return d ? (now - d.getTime()) / 86400000 : null
}

const F_TIME = dtf({ hour: 'numeric', minute: '2-digit' })

/** Time of day only, Houston time: "3:06 PM" */
export function fmtTime(iso) {
  const d = toDate(iso)
  return d ? F_TIME.format(d) : '—'
}
