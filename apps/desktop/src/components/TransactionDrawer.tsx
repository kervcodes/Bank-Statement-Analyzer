import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil } from 'lucide-react'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { CATEGORIES, api } from '../lib/api'
import {
  categorySourceLabel,
  formatDate,
  formatSignedCents,
} from '../lib/format'
import { Select } from './ui/select'
import { Sheet } from './ui/sheet'

/** Mounted once in the app shell (design-notes §3.6: a Sheet over whatever
 *  screen triggered it, so the user never loses their place). Opened by
 *  setting `?txn=<id>` -- linkable, and shareable/refreshable like any URL. */
export function TransactionDrawer() {
  const [params, setParams] = useSearchParams()
  const id = params.get('txn')

  const close = () => {
    const next = new URLSearchParams(params)
    next.delete('txn')
    setParams(next, { replace: true })
  }

  return (
    <Sheet open={id !== null} onOpenChange={(open) => !open && close()} title="Transaction">
      {id && <DrawerBody id={id} />}
    </Sheet>
  )
}

function DrawerBody({ id }: { id: string }) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)

  const { data, isPending, isError } = useQuery({
    queryKey: ['transactions', 'detail', id],
    queryFn: () => api.getTransaction(id),
  })

  if (isPending) return <p className="text-sm text-slate-500">Loading…</p>
  if (isError)
    return <p className="text-sm text-rose-600">Could not load this transaction.</p>

  const merchant = data.merchant_normalized || data.description_normalized

  const onCategoryChange = async (category: string) => {
    await api.setTransactionCategory(id, category)
    setEditing(false)
    await queryClient.invalidateQueries({ queryKey: ['transactions'] })
    await queryClient.invalidateQueries({ queryKey: ['analytics'] })
    // A per-transaction fix can be the last uncategorized row for a merchant --
    // Review's count needs to drop too.
    await queryClient.invalidateQueries({ queryKey: ['review'] })
  }

  return (
    <div className="space-y-5 text-sm">
      <div>
        <h2 className="text-base font-semibold">{merchant}</h2>
        <p className="tabular mt-1 text-slate-500">
          {formatSignedCents(data.amount_cents, data.direction)} ·{' '}
          {formatDate(data.transaction_date)}
        </p>
      </div>

      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <span className="text-slate-500">Category:</span>
          {editing ? (
            <Select
              autoFocus
              defaultValue={data.category}
              onChange={(e) => onCategoryChange(e.target.value)}
              onBlur={() => setEditing(false)}
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </Select>
          ) : (
            <>
              <span className="font-medium">{data.category}</span>
              <button
                className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
                onClick={() => setEditing(true)}
                aria-label="Edit category"
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
            </>
          )}
        </div>
        <p className="text-xs text-slate-500">
          {categorySourceLabel(data.category_source)}
        </p>
      </div>

      <div>
        <p className="text-slate-500">
          Account: {data.source.bank} {data.source.account_type} ••
          {data.source.account_identifier_masked}
        </p>
      </div>

      <div className="rounded-md border border-slate-200 p-3 dark:border-slate-800">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          Source
        </h3>
        <p className="mt-1">
          Statement: {data.source.bank} · {formatDate(data.source.period_start)} –{' '}
          {formatDate(data.source.period_end)}
        </p>
        <p className="text-xs text-slate-500">
          Page {data.source.source_page} · Parser {data.source.parser_version}
        </p>
      </div>

      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          Raw text
        </h3>
        <p className="mt-1 whitespace-pre-wrap font-mono text-xs text-slate-600 dark:text-slate-400">
          {data.description_raw}
        </p>
      </div>
    </div>
  )
}
