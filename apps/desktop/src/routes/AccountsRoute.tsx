import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { Button } from '../components/ui/button'
import { Card } from '../components/ui/card'
import { api } from '../lib/api'
import { formatPeriod } from '../lib/format'

const PAGE_SIZE = 20

/** design-notes §3.5: the resolved account list -- mainly exists so a mis-read
 *  account is easy to spot. Read-only: `Account` identity is unique-constrained
 *  in the backend, so there is no "merge" case to handle here. */
export function AccountsRoute() {
  const [params, setParams] = useSearchParams()
  const page = Math.max(1, Number(params.get('page') ?? '1'))

  const { data, isPending, isError } = useQuery({
    queryKey: ['accounts', 'list', page],
    queryFn: () => api.listAccounts(page, PAGE_SIZE),
  })

  if (isPending) return <p className="text-sm text-slate-500">Loading…</p>
  if (isError)
    return <p className="text-sm text-rose-600">Could not load accounts.</p>

  if (data.total === 0) {
    return (
      <div className="mx-auto max-w-md pt-24 text-center">
        <h1 className="text-lg font-semibold">No accounts yet</h1>
        <p className="mt-2 text-sm text-slate-500">
          Accounts are created automatically as statements are imported.
        </p>
      </div>
    )
  }

  const pages = Math.ceil(data.total / PAGE_SIZE)

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Accounts</h1>

      <Card className="overflow-hidden p-0">
        <table className="w-full text-sm">
          <thead className="border-b border-slate-100 text-left text-xs text-slate-500 dark:border-slate-800">
            <tr>
              <th className="px-3 py-2 font-medium">Account</th>
              <th className="px-3 py-2 font-medium">Period</th>
              <th className="px-3 py-2 font-medium">Statements</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {data.items.map((a) => (
              <tr key={a.id}>
                <td className="px-3 py-2 font-medium">
                  {a.bank} {a.account_type} ••{a.account_identifier_masked}
                </td>
                <td className="px-3 py-2 text-slate-500">
                  {formatPeriod(a.period_start, a.period_end) || '—'}
                </td>
                <td className="tabular px-3 py-2">{a.statement_count}</td>
              </tr>
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
            onClick={() =>
              setParams((prev) => {
                const next = new URLSearchParams(prev)
                next.set('page', String(page - 1))
                return next
              })
            }
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
            onClick={() =>
              setParams((prev) => {
                const next = new URLSearchParams(prev)
                next.set('page', String(page + 1))
                return next
              })
            }
          >
            Next
          </Button>
        </div>
      )}
    </div>
  )
}
