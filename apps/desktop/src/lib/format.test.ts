import { describe, expect, it } from 'vitest'
import {
  batchStatusMeta,
  formatBytes,
  formatPeriod,
  intakeStatusMeta,
  statementStatusMeta,
} from './format'

describe('formatPeriod', () => {
  it('collapses a single month', () => {
    expect(formatPeriod('2026-01-01', '2026-01-31')).toBe('Jan 2026')
  })
  it('shows a range across months', () => {
    expect(formatPeriod('2026-01-01', '2026-08-31')).toBe('Jan 2026 – Aug 2026')
  })
  it('is empty without both endpoints', () => {
    expect(formatPeriod(null, '2026-08-31')).toBe('')
  })
})

describe('formatBytes', () => {
  it('scales units', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(2048)).toBe('2.0 KB')
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB')
  })
})

describe('status meta — colour is never the only signal', () => {
  it('every batch status pairs a tone with a label and icon', () => {
    for (const s of [
      'PROCESSING',
      'COMPLETED',
      'COMPLETED_WITH_WARNINGS',
      'FAILED',
    ]) {
      const m = batchStatusMeta(s)
      expect(m.label.length).toBeGreaterThan(0)
      expect(m.icon).toBeTruthy()
    }
  })
  it('maps a warning statement to amber', () => {
    expect(statementStatusMeta('WARNING').tone).toBe('amber')
  })
  it('maps a rejected intake file to red', () => {
    expect(intakeStatusMeta('VALIDATION_FAILED').tone).toBe('red')
  })
  it('falls back for an unknown status', () => {
    expect(batchStatusMeta('WAT').label).toBe('Unknown')
  })
})
