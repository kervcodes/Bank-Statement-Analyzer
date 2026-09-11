import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Button } from '../components/ui/button'
import { Card } from '../components/ui/card'
import { Select } from '../components/ui/select'
import {
  api,
  CATEGORIES,
  type BatchListItem,
  type DuplicateAction,
  type PossibleDuplicate,
  type ReviewTransaction,
  type UncategorizedGroup,
} from '../lib/api'
import { formatCents, formatDate, formatPeriod, formatSignedCents } from '../lib/format'

/** design-notes §3.4: one inbox instead of three screens -- possible
 *  duplicates, low-confidence categorizations, and failed/unsupported
 *  statements, each its own section with a count. */
export function ReviewRoute() {
  const queryClient = useQueryClient()

  const duplicates = useQuery({
    queryKey: ['review', 'duplicates'],
    queryFn: api.getPossibleDuplicates,
  })
  const uncategorized = useQuery({
    queryKey: ['review', 'categorizations'],
    queryFn: api.getUncategorized,
  })
  const batches = useQuery({
    queryKey: ['batches', 'list', 1],
    queryFn: () => api.listBatches(1, 100),
  })

  const invalidateReview = () => {
    queryClient.invalidateQueries({ queryKey: ['review'] })
    queryClient.invalidateQueries({ queryKey: ['analytics'] })
  }
  const invalidateCategorization = () => {
    invalidateReview()
    queryClient.invalidateQueries({ queryKey: ['transactions'] })
  }

  if (duplicates.isPending || uncategorized.isPending || batches.isPending) {
    return <p className="text-sm text-slate-500">Loading…</p>
  }
  if (duplicates.isError || uncategorized.isError || batches.isError) {
    return <p className="text-sm text-rose-600">Could not load Review.</p>
  }

  const failed = batches.data.items.filter((b) => b.processing_failed > 0)

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Review</h1>
      <DuplicatesSection
        pairs={duplicates.data.possible_duplicates}
        onResolved={invalidateReview}
      />
      <CategorizationSection
        groups={uncategorized.data.groups}
        onResolved={invalidateCategorization}
      />
      <FailedStatementsSection items={failed} />
    </div>
  )
}

function TxnLine({ t }: { t: ReviewTransaction }) {
  return (
    <p className="tabular flex flex-wrap items-baseline gap-x-2">
      <span>{formatDate(t.transaction_date)}</span>
      <span>{t.description_normalized}</span>
      <span>{formatSignedCents(t.amount_cents, t.direction)}</span>
      <span className="text-slate-400">
        ({t.bank} ••{t.account_identifier_masked})
      </span>
    </p>
  )
}

function DuplicatesSection({
  pairs,
  onResolved,
}: {
  pairs: PossibleDuplicate[]
  onResolved: () => void
}) {
  const [pending, setPending] = useState<string | null>(null)

  const act = async (id: string, action: DuplicateAction) => {
    setPending(id)
    try {
      await api.resolveDuplicate(id, action)
      onResolved()
    } finally {
      setPending(null)
    }
  }

  return (
    <Card>
      <h2 className="mb-3 text-sm font-semibold">
        Possible duplicates ({pairs.length})
      </h2>
      {pairs.length === 0 ? (
        <p className="text-sm text-slate-500">Nothing to review.</p>
      ) : (
        <ul className="space-y-3">
          {pairs.map((p) => (
            <li
              key={p.transaction.id}
              className="rounded-md border border-slate-200 p-3 text-sm dark:border-slate-800"
            >
              <TxnLine t={p.transaction} />
              <TxnLine t={p.matches} />
              <div className="mt-2 flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={pending === p.transaction.id}
                  onClick={() => act(p.transaction.id, 'keep_both')}
                >
                  Keep both
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={pending === p.transaction.id}
                  onClick={() => act(p.transaction.id, 'confirm')}
                >
                  This is a duplicate
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function CategorizationSection({
  groups,
  onResolved,
}: {
  groups: UncategorizedGroup[]
  onResolved: () => void
}) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const [choice, setChoice] = useState<Record<string, string>>({})
  const [pending, setPending] = useState<string | null>(null)

  const applyRule = async (merchant: string, category: string) => {
    setPending(merchant)
    try {
      await api.upsertCategoryRule(merchant, category)
      onResolved()
    } finally {
      setPending(null)
    }
  }

  return (
    <Card>
      <h2 className="mb-3 text-sm font-semibold">Needs a category ({groups.length})</h2>
      {groups.length === 0 ? (
        <p className="text-sm text-slate-500">Nothing to review.</p>
      ) : (
        <ul className="divide-y divide-slate-100 dark:divide-slate-800">
          {groups.map((g) => {
            const selected = choice[g.merchant] ?? g.suggested_category ?? ''
            return (
              <li key={g.merchant} className="py-2 text-sm">
                <button
                  className="flex w-full items-center gap-1.5 text-left"
                  onClick={() => setExpanded((v) => (v === g.merchant ? null : g.merchant))}
                >
                  {expanded === g.merchant ? (
                    <ChevronDown className="h-3.5 w-3.5 text-slate-400" />
                  ) : (
                    <ChevronRight className="h-3.5 w-3.5 text-slate-400" />
                  )}
                  <span className="font-medium">{g.merchant}</span>
                  <span className="tabular text-slate-500">
                    {formatCents(g.total_cents)} · {g.transaction_count} txn
                    {g.transaction_count === 1 ? '' : 's'}
                  </span>
                </button>
                {g.suggested_category && (
                  <p className="ml-5 text-xs text-slate-500">
                    Suggested: {g.suggested_category}
                  </p>
                )}
                <div className="ml-5 mt-1.5 flex flex-wrap items-center gap-2">
                  <Select
                    value={selected}
                    onChange={(e) =>
                      setChoice((c) => ({ ...c, [g.merchant]: e.target.value }))
                    }
                  >
                    <option value="" disabled>
                      Pick a category…
                    </option>
                    {CATEGORIES.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </Select>
                  {/* Explicit scope, never a silent merchant-wide write (owner
                      correction 2026-09-08): the button always spells out both
                      the merchant and the target category. */}
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!selected || pending === g.merchant}
                    onClick={() => applyRule(g.merchant, selected)}
                  >
                    Always categorize {g.merchant} as {selected || '…'}
                  </Button>
                </div>
                {expanded === g.merchant && (
                  <MerchantTransactionList merchant={g.merchant} />
                )}
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}

function MerchantTransactionList({ merchant }: { merchant: string }) {
  const [, setParams] = useSearchParams()
  const { data, isPending } = useQuery({
    queryKey: ['transactions', 'list', { merchant }, 1],
    queryFn: () => api.listTransactions({ merchant, pageSize: 50 }),
  })

  if (isPending) return <p className="ml-5 mt-1 text-xs text-slate-500">Loading…</p>

  return (
    <ul className="ml-5 mt-1.5 space-y-1">
      {data?.items.map((t) => (
        <li
          key={t.id}
          className="tabular flex cursor-pointer justify-between text-xs text-slate-500 hover:text-slate-800 dark:hover:text-slate-300"
          onClick={() =>
            setParams((prev) => {
              const next = new URLSearchParams(prev)
              next.set('txn', t.id)
              return next
            })
          }
        >
          <span>
            {formatDate(t.transaction_date)} · {t.description_normalized}
          </span>
          <span>{formatSignedCents(t.amount_cents, t.direction)}</span>
        </li>
      ))}
    </ul>
  )
}

function FailedStatementsSection({ items }: { items: BatchListItem[] }) {
  const navigate = useNavigate()
  return (
    <Card>
      <h2 className="mb-3 text-sm font-semibold">
        Failed / unsupported statements ({items.length})
      </h2>
      {items.length === 0 ? (
        <p className="text-sm text-slate-500">Nothing to review.</p>
      ) : (
        <ul className="divide-y divide-slate-100 text-sm dark:divide-slate-800">
          {items.map((b) => (
            <li key={b.id} className="flex items-center justify-between gap-2 py-1.5">
              <span>
                {formatPeriod(b.period_start, b.period_end) || `Batch ${b.id.slice(0, 8)}`}
              </span>
              <span className="text-slate-500">{b.processing_failed} failed</span>
              <button
                className="text-sky-600 hover:underline dark:text-sky-400"
                onClick={() => navigate(`/history?batch=${b.id}`)}
              >
                View in History →
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
