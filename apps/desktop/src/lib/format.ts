/** Display formatting + the status colour/icon/label map (design-notes §4:
 *  colour is never the only signal). Pure functions, unit-tested. */

/** Parse a backend date/datetime. A bare `YYYY-MM-DD` is a calendar date — pin
 *  it to local midnight so it doesn't slide a day in a negative-offset zone. */
function parse(iso: string): Date {
  return new Date(/^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T00:00:00` : iso)
}

export function formatDate(iso: string): string {
  const d = parse(iso)
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      })
}

/** "Jan 2026 – Aug 2026", or a single month, or "" when no range. */
export function formatPeriod(
  start: string | null,
  end: string | null,
): string {
  if (!start || !end) return ''
  const fmt = (iso: string) =>
    parse(iso).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
    })
  const a = fmt(start)
  const b = fmt(end)
  return a === b ? a : `${a} – ${b}`
}

export type Tone = 'gray' | 'blue' | 'green' | 'amber' | 'red'

export interface StatusMeta {
  tone: Tone
  label: string
  /** lucide-react icon name — kept as a string so this module stays icon-free */
  icon: 'clock' | 'loader' | 'check' | 'triangle-alert' | 'x'
}

const BATCH_STATUS: Record<string, StatusMeta> = {
  PROCESSING: { tone: 'blue', label: 'Processing', icon: 'loader' },
  COMPLETED: { tone: 'green', label: 'Completed', icon: 'check' },
  COMPLETED_WITH_WARNINGS: {
    tone: 'amber',
    label: 'Completed with warnings',
    icon: 'triangle-alert',
  },
  FAILED: { tone: 'red', label: 'Failed', icon: 'x' },
}

const STATEMENT_STATUS: Record<string, StatusMeta> = {
  VALID: { tone: 'green', label: 'Valid', icon: 'check' },
  WARNING: { tone: 'amber', label: 'Warning', icon: 'triangle-alert' },
  FAILED: { tone: 'red', label: 'Failed', icon: 'x' },
  UNSUPPORTED: { tone: 'gray', label: 'Unsupported', icon: 'triangle-alert' },
}

const INTAKE_STATUS: Record<string, StatusMeta> = {
  ACCEPTED: { tone: 'green', label: 'Ready', icon: 'check' },
  UPLOAD_FAILED: { tone: 'red', label: 'Upload failed', icon: 'x' },
  VALIDATION_FAILED: { tone: 'red', label: 'Rejected', icon: 'x' },
}

const UNKNOWN: StatusMeta = { tone: 'gray', label: 'Unknown', icon: 'clock' }

export const batchStatusMeta = (s: string): StatusMeta =>
  BATCH_STATUS[s] ?? UNKNOWN
export const statementStatusMeta = (s: string | null): StatusMeta =>
  (s && STATEMENT_STATUS[s]) || UNKNOWN
export const intakeStatusMeta = (s: string): StatusMeta =>
  INTAKE_STATUS[s] ?? UNKNOWN

/** kilobytes / megabytes for the file list. */
export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}
