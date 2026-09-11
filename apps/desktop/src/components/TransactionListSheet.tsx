import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, type ListTransactionsParams } from '../lib/api'
import { formatDate, formatSignedCents } from '../lib/format'
import { Button } from './ui/button'
import { Sheet } from './ui/sheet'

const PAGE_SIZE = 25

/** The "click a number -> see the rows behind it" surface (design-notes
 *  principle 4). Filters come from the caller (a stat card, a chart segment,
 *  a merchant row); this sheet only owns its own pagination. A row opens the
 *  transaction drawer via `?txn=<id>`. */
export function TransactionListSheet({
  open,
  onOpenChange,
  title,
  filters,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  filters: Omit<ListTransactionsParams, 'page' | 'pageSize'>
}) {
  const [page, setPage] = useState(1)
  const [, setParams] = useSearchParams()

  const { data, isPending, isError } = useQuery({
    queryKey: ['transactions', 'list', filters, page],
    queryFn: () => api.listTransactions({ ...filters, page, pageSize: PAGE_SIZE }),
    enabled: open,
  })

  const openTxn = (id: string) => {
    setParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set('txn', id)
      return next
    })
  }

  return (
    <Sheet
      open={open}
      onOpenChange={(next) => {
        if (!next) setPage(1)
        onOpenChange(next)
      }}
      title={title}
      width="lg"
    >
      {isPending && <p className="text-sm text-slate-500">Loading…</p>}
      {isError && (
        <p className="text-sm text-rose-600">Could not load these transactions.</p>
      )}
      {data && data.items.length === 0 && (
        <p className="text-sm text-slate-500">No transactions match this filter.</p>
      )}
      {data && data.items.length > 0 && (
        <>
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-slate-500">
              <tr>
                <th className="py-1.5 font-medium">Date</th>
                <th className="py-1.5 font-medium">Merchant</th>
                <th className="py-1.5 font-medium">Category</th>
                <th className="py-1.5 text-right font-medium">Amount</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {data.items.map((t) => (
                <tr
                  key={t.id}
                  className="cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50"
                  onClick={() => openTxn(t.id)}
                >
                  <td className="tabular py-1.5 pr-2 text-slate-500">
                    {formatDate(t.transaction_date)}
                  </td>
                  <td className="py-1.5 pr-2">{t.merchant}</td>
                  <td className="py-1.5 pr-2 text-slate-500">{t.category}</td>
                  <td className="tabular py-1.5 text-right">
                    {formatSignedCents(t.amount_cents, t.direction)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {data.total > PAGE_SIZE && (
            <div className="mt-3 flex items-center justify-end gap-2 text-sm">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                Previous
              </Button>
              <span className="tabular text-slate-500">
                {page} / {Math.ceil(data.total / PAGE_SIZE)}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= Math.ceil(data.total / PAGE_SIZE)}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </Button>
            </div>
          )}
        </>
      )}
    </Sheet>
  )
}
