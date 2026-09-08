import {
  Check,
  Clock,
  Loader,
  TriangleAlert,
  X,
} from 'lucide-react'
import type { StatusMeta, Tone } from '../../lib/format'
import { cn } from '../../lib/cn'

const TONE: Record<Tone, string> = {
  gray: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
  blue: 'bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300',
  green:
    'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300',
  amber:
    'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300',
  red: 'bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300',
}

const ICON = {
  clock: Clock,
  loader: Loader,
  check: Check,
  'triangle-alert': TriangleAlert,
  x: X,
}

/** A status pill that always pairs colour with an icon and a word
 *  (design-notes §4: never colour alone). */
export function StatusBadge({
  meta,
  className,
}: {
  meta: StatusMeta
  className?: string
}) {
  const Icon = ICON[meta.icon]
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium',
        TONE[meta.tone],
        className,
      )}
    >
      <Icon
        className={cn('h-3 w-3', meta.icon === 'loader' && 'animate-spin')}
        aria-hidden
      />
      {meta.label}
    </span>
  )
}
