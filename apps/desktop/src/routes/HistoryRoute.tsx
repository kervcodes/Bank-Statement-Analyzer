import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Button } from '../components/ui/button'
import { Card } from '../components/ui/card'
import { StatusBadge } from '../components/ui/StatusBadge'
import {
  api,
  BATCH_TERMINAL,
  type BatchListItem,
} from '../lib/api'
import {
  batchStatusMeta,
  formatDate,
  formatPeriod,
  statementStatusMeta,
} from '../lib/format'

const PAGE_SIZE = 20

export function HistoryRoute() {
  // page + expanded batch live in the URL (navigation/filter state).
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const page = Math.max(1, Number(params.get('page') ?? '1'))
  const expanded = params.get('batch')

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params)
    if (value === null) next.delete(key)
    else next.set(key, value)
    setParams(next, { replace: true })
  }

  const { data, isPending, isError } = useQuery({
    queryKey: ['batches', 'list', page],
    queryFn: () => api.listBatches(page, PAGE_SIZE),
    // keep polling while any batch on this page is still processing
    refetchInterval: (q) =>
      q.state.data?.items.some((b) => !BATCH_TERMINAL.has(b.status))
        ? 3000
        : false,
  })

  if (isPending) return <p className="text-sm text-slate-500">Loading…</p>
  if (isError)
    return <p className="text-sm text-rose-600">Could not load history.</p>

  if (data.total === 0) {
    return (
      <div className="mx-auto max-w-md pt-24 text-center">
        <h1 className="text-lg font-semibold">No imports yet</h1>
        <p className="mt-2 text-sm text-slate-500">
          Add your first bank statements to get started.
        </p>
        <Button className="mt-4" onClick={() => navigate('/import')}>
          Import statements
        </Button>
      </div>
    )
  }

  const pages = Math.ceil(data.total / PAGE_SIZE)

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">History</h1>

      <Card className="overflow-hidden p-0">
        <table className="w-full text-sm">
          <thead className="border-b border-slate-100 text-left text-xs text-slate-500 dark:border-slate-800">
            <tr>
              <th className="w-8" />
              <th className="px-3 py-2 font-medium">Batch</th>
              <th className="px-3 py-2 font-medium">Imported</th>
              <th className="px-3 py-2 font-medium">Statements</th>
              <th className="px-3 py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {data.items.map((b) => (
              <BatchRow
                key={b.id}
                batch={b}
                open={expanded === b.id}
                onToggle={() =>
                  setParam('batch', expanded === b.id ? null : b.id)
                }
              />
            ))}
          </tbody>
        </table>
      </Card>

      {pages > 1 && (
        <div className="flex items-center justify-end gap-2 text-sm">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1}
            onClick={() => setParam('page', String(page - 1))}
          >
            Previous
          </Button>
          <span className="tabular text-slate-500">
            {page} / {pages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= pages}
            onClick={() => setParam('page', String(page + 1))}
          >
            Next
          </Button>
        </div>
      )}
    </div>
  )
}

function BatchRow({
  batch,
  open,
  onToggle,
}: {
  batch: BatchListItem
  open: boolean
  onToggle: () => void
}) {
  const label =
    formatPeriod(batch.period_start, batch.period_end) ||
    `Batch ${batch.id.slice(0, 8)}`
  return (
    <>
      <tr
        className="cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50"
        onClick={onToggle}
      >
        <td className="pl-3 text-slate-400">
          {open ? (
            <ChevronDown className="h-4 w-4" />
          ) : (
            <ChevronRight className="h-4 w-4" />
          )}
        </td>
        <td className="px-3 py-2 font-medium">{label}</td>
        <td className="tabular px-3 py-2 text-slate-500">
          {formatDate(batch.created_at)}
        </td>
        <td className="tabular px-3 py-2">
          {batch.processed} / {batch.selected}
        </td>
        <td className="px-3 py-2">
          <StatusBadge meta={batchStatusMeta(batch.status)} />
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={5} className="bg-slate-50 px-3 py-2 dark:bg-slate-800/30">
            <BatchDetail id={batch.id} />
          </td>
        </tr>
      )}
    </>
  )
}

function BatchDetail({ id }: { id: string }) {
  const { data, isPending, isError } = useQuery({
    queryKey: ['batches', 'detail', id],
    queryFn: () => api.getBatch(id),
  })
  if (isPending) return <p className="text-xs text-slate-500">Loading…</p>
  if (isError)
    return <p className="text-xs text-rose-600">Could not load details.</p>

  return (
    <div className="space-y-1">
      {data.validation_failed > 0 && (
        <p className="text-xs text-amber-700 dark:text-amber-400">
          {data.validation_failed} file
          {data.validation_failed > 1 ? 's were' : ' was'} rejected at intake.
        </p>
      )}
      {data.statements.length === 0 ? (
        <p className="text-xs text-slate-500">No statements produced.</p>
      ) : (
        <table className="w-full text-xs">
          <tbody>
            {data.statements.map((s) => (
              <tr key={s.id}>
                <td className="py-1 pr-3">
                  {s.bank} {s.account_type} ••{s.account_identifier_masked}
                </td>
                <td className="py-1 pr-3">
                  <StatusBadge meta={statementStatusMeta(s.validation_result)} />
                </td>
                <td className="py-1 text-slate-400">
                  {s.dedup_status !== 'UNIQUE' && s.dedup_status}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
