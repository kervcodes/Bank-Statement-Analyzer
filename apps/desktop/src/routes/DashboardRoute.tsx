import { useQuery } from '@tanstack/react-query'
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  RefreshCw,
  Sparkles,
  TriangleAlert,
} from 'lucide-react'
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { CashFlowChart } from '../components/dashboard/CashFlowChart'
import { SpendingDonut } from '../components/dashboard/SpendingDonut'
import { TransactionListSheet } from '../components/TransactionListSheet'
import { Button } from '../components/ui/button'
import { Card } from '../components/ui/card'
import {
  api,
  type CoverageSummary,
  type ListTransactionsParams,
  type MerchantTotal,
  type RecurringCharge,
} from '../lib/api'
import { cn } from '../lib/cn'
import {
  computeRangeDates,
  type FullMonthComparison,
  latestFullMonthComparison,
  monthBounds,
  percentDelta,
  type RangePreset,
} from '../lib/dashboard'
import { formatCents, formatMonth, formatPeriod } from '../lib/format'

const RANGE_LABELS: Record<'12m' | 'ytd' | 'all', string> = {
  '12m': 'Last 12 months',
  ytd: 'This year',
  all: 'All time',
}

const CADENCE_SHORT: Record<RecurringCharge['cadence'], string> = {
  weekly: 'wk',
  biweekly: '2wk',
  monthly: 'mo',
  annual: 'yr',
}

type Drill = { title: string; filters: Omit<ListTransactionsParams, 'page' | 'pageSize'> }

export function DashboardRoute() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const range = (params.get('range') as RangePreset | null) ?? '12m'
  const defaults = computeRangeDates(range === 'custom' ? '12m' : range)
  const start = params.get('start') ?? defaults.start ?? undefined
  const end = params.get('end') ?? defaults.end ?? undefined

  const setRange = (preset: 'ytd' | 'all' | '12m') => {
    const bounds = computeRangeDates(preset)
    const next = new URLSearchParams(params)
    next.set('range', preset)
    if (bounds.start) next.set('start', bounds.start)
    else next.delete('start')
    if (bounds.end) next.set('end', bounds.end)
    else next.delete('end')
    setParams(next, { replace: true })
  }

  const [drill, setDrill] = useState<Drill | null>(null)

  const { data, isPending, isError } = useQuery({
    queryKey: ['analytics', start, end],
    queryFn: () => api.getAnalytics(start, end),
  })

  if (isPending) return <p className="text-sm text-slate-500">Loading…</p>
  if (isError)
    return <p className="text-sm text-rose-600">Could not load the dashboard.</p>

  if (data.coverage.transaction_count === 0) {
    return (
      <div className="mx-auto max-w-md pt-24 text-center">
        <h1 className="text-lg font-semibold">Nothing processed yet</h1>
        <p className="mt-2 text-sm text-slate-500">
          Import your first bank statements to see cash flow, spending, and trends
          here.
        </p>
        <Button className="mt-4" onClick={() => navigate('/import')}>
          Import statements
        </Button>
      </div>
    )
  }

  const comparison = latestFullMonthComparison(data.cash_flow)
  const latestPeriod = data.cash_flow.at(-1) ?? null
  const netDeltaPct = data.trends.net_delta_ratio
    ? Number(data.trends.net_delta_ratio) * 100
    : null
  const topCategory = data.spending_by_category[0] ?? null

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Dashboard</h1>
        <div className="flex gap-1">
          {(['12m', 'ytd', 'all'] as const).map((p) => (
            <Button
              key={p}
              size="sm"
              variant={range === p ? 'primary' : 'outline'}
              onClick={() => setRange(p)}
            >
              {RANGE_LABELS[p]}
            </Button>
          ))}
        </div>
      </div>

      <CoverageBar coverage={data.coverage} onNavigateHistory={() => navigate('/history')} />

      {data.cash_flow.length === 0 ? (
        <p className="text-sm text-slate-500">No transactions in this range.</p>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <StatCard
              label="Net cash flow"
              value={latestPeriod ? formatCents(latestPeriod.net_cents) : '—'}
              delta={netDeltaPct}
              deltaGoodDirection="up"
              onClick={() => {
                if (!latestPeriod) return
                const b = monthBounds(latestPeriod.period)
                setDrill({
                  title: `${formatMonth(latestPeriod.period)} transactions`,
                  filters: { dateFrom: b.start, dateTo: b.end },
                })
              }}
            />
            <SpendingStatCard
              comparison={comparison}
              onClick={() => {
                if (!comparison) return
                const b = monthBounds(comparison.current.period)
                setDrill({
                  title: `${formatMonth(comparison.current.period)} spending`,
                  filters: { dateFrom: b.start, dateTo: b.end, spendingOnly: true },
                })
              }}
            />
            <StatCard
              label="Top category"
              value={topCategory?.category ?? '—'}
              sub={topCategory ? formatCents(topCategory.total_cents) : undefined}
              onClick={() =>
                topCategory &&
                setDrill({
                  title: topCategory.category,
                  filters: { category: topCategory.category, dateFrom: start, dateTo: end },
                })
              }
            />
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card>
              <CashFlowChart data={data.cash_flow} />
            </Card>
            <Card>
              <SpendingDonut
                data={data.spending_by_category}
                onSelectCategory={(category) =>
                  setDrill({
                    title: category,
                    filters: { category, dateFrom: start, dateTo: end },
                  })
                }
              />
            </Card>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <RecurringChargesCard
              items={data.recurring_charges}
              onSelectMerchant={(merchant) =>
                setDrill({ title: merchant, filters: { merchant, dateFrom: start, dateTo: end } })
              }
            />
            <TopMerchantsCard
              items={data.merchant_totals}
              onSelectMerchant={(merchant) =>
                setDrill({ title: merchant, filters: { merchant, dateFrom: start, dateTo: end } })
              }
            />
          </div>
        </>
      )}

      <AiSummaryPanel start={start} end={end} />

      {drill && (
        <TransactionListSheet
          open
          onOpenChange={(open) => !open && setDrill(null)}
          title={drill.title}
          filters={drill.filters}
        />
      )}
    </div>
  )
}

function CoverageBar({
  coverage,
  onNavigateHistory,
}: {
  coverage: CoverageSummary
  onNavigateHistory: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const clean = coverage.statements_excluded === 0
  const total = coverage.statements_included + coverage.statements_excluded

  return (
    <Card
      className={
        clean
          ? 'border-emerald-200 dark:border-emerald-900'
          : 'border-amber-200 dark:border-amber-900'
      }
    >
      <button
        className="flex w-full items-center justify-between text-left"
        onClick={() => (clean ? onNavigateHistory() : setExpanded((v) => !v))}
      >
        <span className="flex items-center gap-2 text-sm">
          {clean ? (
            <CheckCircle2 className="h-4 w-4 text-emerald-600" aria-hidden />
          ) : (
            <TriangleAlert className="h-4 w-4 text-amber-600" aria-hidden />
          )}
          <span className="font-medium">
            {coverage.statements_included} of {total} statements
          </span>
          {coverage.ledger_start && coverage.ledger_end && (
            <span className="text-slate-500">
              · {formatPeriod(coverage.ledger_start, coverage.ledger_end)}
            </span>
          )}
        </span>
        {!clean && (
          <span className="flex items-center gap-1 text-xs text-amber-700 dark:text-amber-400">
            {coverage.statements_excluded} excluded
            {expanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
          </span>
        )}
      </button>
      {!clean && expanded && (
        <ul className="mt-2 space-y-1 border-t border-amber-200 pt-2 text-xs dark:border-amber-900">
          {coverage.excluded.map((e) => (
            <li key={e.statement_id} className="flex justify-between gap-2">
              <span>
                {e.bank} ••{e.account_identifier_masked} ·{' '}
                {formatPeriod(e.period_start, e.period_end)}
              </span>
              <span className="text-slate-500">{e.reason}</span>
            </li>
          ))}
          <li>
            <button
              className="text-sky-600 hover:underline dark:text-sky-400"
              onClick={onNavigateHistory}
            >
              View in History →
            </button>
          </li>
        </ul>
      )}
    </Card>
  )
}

function StatCard({
  label,
  value,
  delta,
  deltaGoodDirection = 'up',
  sub,
  onClick,
}: {
  label: string
  value: string
  delta?: number | null
  deltaGoodDirection?: 'up' | 'down'
  sub?: string
  onClick?: () => void
}) {
  const good = delta != null && (deltaGoodDirection === 'up' ? delta >= 0 : delta <= 0)
  return (
    <Card
      className={onClick ? 'cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50' : undefined}
      onClick={onClick}
    >
      <p className="text-xs text-slate-500">{label}</p>
      <p className="tabular mt-1 text-xl font-semibold">{value}</p>
      {delta != null && (
        <p className={cn('tabular mt-1 text-xs', good ? 'text-emerald-600' : 'text-rose-600')}>
          {delta >= 0 ? '↑' : '↓'} {Math.abs(delta).toFixed(1)}%
        </p>
      )}
      {sub && <p className="mt-1 text-xs text-slate-500">{sub}</p>}
    </Card>
  )
}

function SpendingStatCard({
  comparison,
  onClick,
}: {
  comparison: FullMonthComparison | null
  onClick: () => void
}) {
  if (!comparison) {
    return (
      <Card>
        <p className="text-xs text-slate-500">Monthly spending</p>
        <p className="mt-1 text-sm text-slate-500">Not enough data yet.</p>
      </Card>
    )
  }
  const { current, previous } = comparison
  const label = `${formatMonth(current.period)} spending`
  const delta = previous ? percentDelta(current.spending_cents, previous.spending_cents) : null
  // A drop in spending is the good direction here, the opposite of net cash flow.
  const good = delta != null && delta <= 0

  return (
    <Card className="cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50" onClick={onClick}>
      <p className="text-xs text-slate-500">{label}</p>
      <p className="tabular mt-1 text-xl font-semibold">{formatCents(current.spending_cents)}</p>
      {!previous && <p className="mt-1 text-xs text-slate-500">Not enough prior data</p>}
      {previous && delta != null && (
        <p className={cn('tabular mt-1 text-xs', good ? 'text-emerald-600' : 'text-rose-600')}>
          {delta <= 0 ? '↓' : '↑'} {Math.abs(delta).toFixed(0)}% vs {formatMonth(previous.period)}
        </p>
      )}
    </Card>
  )
}

function RecurringChargesCard({
  items,
  onSelectMerchant,
}: {
  items: RecurringCharge[]
  onSelectMerchant: (merchant: string) => void
}) {
  return (
    <Card>
      <h3 className="mb-2 text-sm font-medium">Recurring charges</h3>
      {items.length === 0 ? (
        <p className="text-sm text-slate-500">None detected yet.</p>
      ) : (
        <ul className="divide-y divide-slate-100 text-sm dark:divide-slate-800">
          {items.map((r) => (
            <li
              key={r.merchant}
              className="flex cursor-pointer items-center justify-between py-1.5 hover:bg-slate-50 dark:hover:bg-slate-800/50"
              onClick={() => onSelectMerchant(r.merchant)}
            >
              <span>{r.merchant}</span>
              <span className="tabular text-slate-500">
                {formatCents(r.typical_amount_cents)}/{CADENCE_SHORT[r.cadence]}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function TopMerchantsCard({
  items,
  onSelectMerchant,
}: {
  items: MerchantTotal[]
  onSelectMerchant: (merchant: string) => void
}) {
  return (
    <Card>
      <h3 className="mb-2 text-sm font-medium">Top merchants</h3>
      {items.length === 0 ? (
        <p className="text-sm text-slate-500">No spending yet.</p>
      ) : (
        <ul className="divide-y divide-slate-100 text-sm dark:divide-slate-800">
          {items.map((m) => (
            <li
              key={m.merchant}
              className="flex cursor-pointer items-center justify-between py-1.5 hover:bg-slate-50 dark:hover:bg-slate-800/50"
              onClick={() => onSelectMerchant(m.merchant)}
            >
              <span>{m.merchant}</span>
              <span className="tabular text-slate-500">{formatCents(m.total_cents)}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function AiSummaryPanel({ start, end }: { start?: string; end?: string }) {
  const { data, isPending, isError, refetch, isFetching } = useQuery({
    queryKey: ['analytics', 'explanation', start, end],
    queryFn: () => api.getAnalyticsExplanation(start, end),
  })

  return (
    <Card className="border-violet-200 dark:border-violet-900">
      <div className="flex items-center justify-between">
        <h3 className="flex items-center gap-1.5 text-sm font-medium">
          <Sparkles className="h-4 w-4 text-violet-600" aria-hidden />
          AI summary
          {data?.provider && (
            <span className="rounded-full bg-violet-100 px-1.5 py-0.5 text-[10px] font-medium text-violet-700 dark:bg-violet-950 dark:text-violet-300">
              {data.provider}
            </span>
          )}
        </h3>
        {data?.provider && (
          <Button variant="ghost" size="sm" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw className={cn('h-3.5 w-3.5', isFetching && 'animate-spin')} />
            Refresh
          </Button>
        )}
      </div>
      <div className="mt-2 text-sm">
        {isPending ? (
          <p className="text-slate-500">Loading…</p>
        ) : isError ? (
          <p className="text-rose-600">Could not load a summary.</p>
        ) : !data.provider ? (
          <p className="text-slate-500">
            Add an API key in Settings to get a plain-English summary.
          </p>
        ) : (
          <p>{data.text}</p>
        )}
      </div>
    </Card>
  )
}
