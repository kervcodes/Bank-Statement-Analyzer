import { useState } from 'react'
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { CASH_FLOW_COLORS } from '../../lib/chartColors'
import { formatCents, formatMonth } from '../../lib/format'
import type { PeriodCashFlow } from '../../lib/api'
import { Button } from '../ui/button'

/** design-notes §3.1: credits / debits / net, transfers shown distinctly.
 *  One axis -- all four series share the same unit (dollars), so this is bars
 *  + an overlaid line, not a dual-axis chart. Accessibility §6: every chart
 *  needs a non-visual fallback, here a "show as table" toggle. */
export function CashFlowChart({ data }: { data: PeriodCashFlow[] }) {
  const [asTable, setAsTable] = useState(false)

  if (data.length === 0) {
    return <p className="text-sm text-slate-500">Not enough data yet.</p>
  }

  const rows = data.map((p) => ({
    period: p.period,
    label: formatMonth(p.period).slice(0, 3) + ' ' + p.period.slice(0, 4),
    credits: p.credits_cents / 100,
    debits: -p.debits_cents / 100, // shown below the axis, like a real ledger
    net: p.net_cents / 100,
    transfers: p.transfers_cents / 100,
  }))

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-medium">Cash flow, last 12 months</h3>
        <Button variant="ghost" size="sm" onClick={() => setAsTable((v) => !v)}>
          {asTable ? 'Show chart' : 'Show as table'}
        </Button>
      </div>

      {asTable ? (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-left text-slate-500">
              <tr>
                <th className="py-1 pr-3 font-medium">Month</th>
                <th className="py-1 pr-3 text-right font-medium">Credits</th>
                <th className="py-1 pr-3 text-right font-medium">Debits</th>
                <th className="py-1 pr-3 text-right font-medium">Net</th>
                <th className="py-1 text-right font-medium">Transfers</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {data.map((p) => (
                <tr key={p.period}>
                  <td className="tabular py-1 pr-3">{formatMonth(p.period)}</td>
                  <td className="tabular py-1 pr-3 text-right">
                    {formatCents(p.credits_cents)}
                  </td>
                  <td className="tabular py-1 pr-3 text-right">
                    {formatCents(p.debits_cents)}
                  </td>
                  <td className="tabular py-1 pr-3 text-right">
                    {formatCents(p.net_cents)}
                  </td>
                  <td className="tabular py-1 text-right">
                    {formatCents(p.transfers_cents)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={rows}>
            <CartesianGrid strokeDasharray="3 3" className="stroke-slate-200 dark:stroke-slate-800" />
            <XAxis dataKey="label" tick={{ fontSize: 11 }} />
            <YAxis
              tick={{ fontSize: 11 }}
              tickFormatter={(v: number) => `$${v}`}
            />
            <Tooltip
              formatter={(value) => `$${Number(value).toFixed(2)}`}
              contentStyle={{ fontSize: 12 }}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar dataKey="credits" name="Credits" fill={CASH_FLOW_COLORS.credits} />
            <Bar dataKey="debits" name="Debits" fill={CASH_FLOW_COLORS.debits} />
            <Bar
              dataKey="transfers"
              name="Transfers"
              fill={CASH_FLOW_COLORS.transfers}
            />
            <Line
              type="monotone"
              dataKey="net"
              name="Net"
              stroke={CASH_FLOW_COLORS.net}
              strokeWidth={2}
              dot={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
