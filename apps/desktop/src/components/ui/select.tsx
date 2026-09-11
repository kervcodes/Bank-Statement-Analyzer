import type { SelectHTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

/** A native <select>, styled to match the rest of the primitives. A category
 *  picker over a fixed, short taxonomy doesn't need a combobox. */
export function Select({
  className,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        'h-8 rounded-md border border-slate-300 bg-white px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 dark:border-slate-700 dark:bg-slate-900',
        className,
      )}
      {...props}
    />
  )
}
