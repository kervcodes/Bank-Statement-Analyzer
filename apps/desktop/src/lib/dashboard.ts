import type { PeriodCashFlow } from './api'

export type RangePreset = '12m' | 'ytd' | 'all' | 'custom'

/** Local-calendar-date -> "YYYY-MM-DD". Never `toISOString()` here -- that's
 *  UTC and slides a day in a negative-offset zone (same bug format.ts's
 *  `parse()` guards against). */
function toIso(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

/** Boundary dates for a range preset, anchored to "today" (injectable for
 *  tests). `all` means no filter -- both null. */
export function computeRangeDates(
  preset: RangePreset,
  today: Date = new Date(),
): { start: string | null; end: string | null } {
  const end = toIso(today)
  if (preset === 'all') return { start: null, end: null }
  if (preset === 'ytd') {
    return { start: toIso(new Date(today.getFullYear(), 0, 1)), end }
  }
  const start = new Date(today)
  start.setMonth(start.getMonth() - 12)
  return { start: toIso(start), end }
}

export interface FullMonthComparison {
  current: PeriodCashFlow
  previous: PeriodCashFlow | null
}

/** The latest FULL calendar month vs the one before it (owner correction,
 *  2026-09-08): the Spending stat card excludes the current partial month, so
 *  a mid-month glance never reads as "spending collapsed." `cashFlow` is
 *  assumed sorted ascending by period, as `GET /analytics` returns it. Fewer
 *  than one full month of data -> null (nothing to show). */
export function latestFullMonthComparison(
  cashFlow: PeriodCashFlow[],
  today: Date = new Date(),
): FullMonthComparison | null {
  const currentMonthKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}`
  const fullMonths = cashFlow.filter((p) => p.period !== currentMonthKey)
  if (fullMonths.length === 0) return null
  const current = fullMonths[fullMonths.length - 1]
  const previous = fullMonths.length >= 2 ? fullMonths[fullMonths.length - 2] : null
  return { current, previous }
}

/** Signed percent change, or null when there's no meaningful base to compare
 *  against (division by zero). */
export function percentDelta(current: number, previous: number): number | null {
  if (previous === 0) return null
  return ((current - previous) / Math.abs(previous)) * 100
}

/** First/last day of a "YYYY-MM" period, as ISO date strings -- the exact
 *  date_from/date_to a drill-through needs to show that month's rows. */
export function monthBounds(period: string): { start: string; end: string } {
  const [year, month] = period.split('-').map(Number)
  const start = new Date(year, month - 1, 1)
  const end = new Date(year, month, 0) // day 0 of next month = last day of this one
  return { start: toIso(start), end: toIso(end) }
}
