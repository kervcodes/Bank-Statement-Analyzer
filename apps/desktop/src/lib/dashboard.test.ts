import { describe, expect, it } from 'vitest'
import {
  computeRangeDates,
  latestFullMonthComparison,
  monthBounds,
  percentDelta,
} from './dashboard'

const TODAY = new Date(2026, 8, 15) // Sep 15, 2026 (mid-month, local)

describe('computeRangeDates', () => {
  it('12m is a rolling 12-month window ending today', () => {
    expect(computeRangeDates('12m', TODAY)).toEqual({
      start: '2025-09-15',
      end: '2026-09-15',
    })
  })

  it('ytd starts Jan 1 of the current year', () => {
    expect(computeRangeDates('ytd', TODAY)).toEqual({
      start: '2026-01-01',
      end: '2026-09-15',
    })
  })

  it('all has no bounds', () => {
    expect(computeRangeDates('all', TODAY)).toEqual({ start: null, end: null })
  })
})

function flow(period: string, spending: number) {
  return {
    period,
    credits_cents: 0,
    debits_cents: spending,
    net_cents: -spending,
    spending_cents: spending,
    transfers_cents: 0,
  }
}

describe('latestFullMonthComparison', () => {
  it('excludes the current partial month', () => {
    const result = latestFullMonthComparison(
      [flow('2026-07', 100), flow('2026-08', 200), flow('2026-09', 999)],
      TODAY, // "today" is in September
    )
    expect(result?.current.period).toBe('2026-08')
    expect(result?.previous?.period).toBe('2026-07')
  })

  it('fewer than two full months -> no previous', () => {
    const result = latestFullMonthComparison([flow('2026-08', 200)], TODAY)
    expect(result?.current.period).toBe('2026-08')
    expect(result?.previous).toBeNull()
  })

  it('no full months at all -> null', () => {
    expect(latestFullMonthComparison([flow('2026-09', 999)], TODAY)).toBeNull()
  })
})

describe('percentDelta', () => {
  it('signed percent change', () => {
    expect(percentDelta(120, 100)).toBeCloseTo(20)
    expect(percentDelta(80, 100)).toBeCloseTo(-20)
  })

  it('null when there is no base to compare against', () => {
    expect(percentDelta(100, 0)).toBeNull()
  })
})

describe('monthBounds', () => {
  it('first and last calendar day of the period', () => {
    expect(monthBounds('2026-02')).toEqual({ start: '2026-02-01', end: '2026-02-28' })
    expect(monthBounds('2026-12')).toEqual({ start: '2026-12-01', end: '2026-12-31' })
  })
})
