import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'

/** A right-side panel (design-notes §3.6: the drawer is a Sheet, not a page).
 *  Radix Dialog underneath for the focus trap + Esc handling. */
export function Sheet({
  open,
  onOpenChange,
  title,
  width = 'md',
  children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  width?: 'md' | 'lg'
  children: ReactNode
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/30" />
        <Dialog.Content
          className={cn(
            'fixed inset-y-0 right-0 z-50 flex flex-col border-l border-slate-200 bg-white shadow-xl outline-none dark:border-slate-800 dark:bg-slate-900',
            width === 'lg' ? 'w-full max-w-2xl' : 'w-full max-w-md',
          )}
        >
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3 dark:border-slate-800">
            <Dialog.Title className="text-sm font-semibold">
              {title}
            </Dialog.Title>
            <Dialog.Close asChild>
              <button
                className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800"
                aria-label="Close"
              >
                <X className="h-4 w-4" />
              </button>
            </Dialog.Close>
          </div>
          <div className="flex-1 overflow-y-auto p-4">{children}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
