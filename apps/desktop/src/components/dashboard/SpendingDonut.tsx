import { useState } from 'react'
import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import type { CategoryTotal } from '../../lib/api'
import { CATEGORY_COLORS, MAX_DONUT_SLICES, OTHER_CATEGORY_COLOR } from '../../lib/chartColors'
import { formatCents } from '../../lib/format'
import { Button } from '../ui/button'

/** design-notes §3.1: spending by category, donut. Capped at
 *  MAX_DONUT_SLICES; anything past that folds into "Other" (dataviz
 *  anti-patterns: a pie/donut past ~6 segments stops being readable at a
 *  glance) -- the table view still lists every category individually. */
export function SpendingDonut({
  data,
  onSelectCategory,
}: {
  data: CategoryTotal[]
  onSelectCategory: (category: string) => void
}) {
  const [asTable, setAsTable] = useState(false)

  if (data.length === 0) {
    return <p className="text-sm text-slate-500">No spending in this range yet.</p>
  }

  const top = data.slice(0, MAX_DONUT_SLICES - 1)
  const rest = data.slice(MAX_DONUT_SLICES - 1)
  const otherTotal = rest.reduce((sum, c) => sum + c.total_cents, 0)
  const slices = [
    ...top.map((c, i) => ({
      category: c.category,
      total_cents: c.total_cents,
      color: CATEGORY_COLORS[i],
    })),
    ...(otherTotal > 0
      ? [{ category: 'Other', total_cents: otherTotal, color: OTHER_CATEGORY_COLOR }]
      : []),
  ]

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-medium">Spending by category</h3>
        <Button variant="ghost" size="sm" onClick={() => setAsTable((v) => !v)}>
          {asTable ? 'Show chart' : 'Show as table'}
        </Button>
      </div>

      {asTable ? (
        <table className="w-full text-xs">
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {data.map((c) => (
              <tr
                key={c.category}
                className="cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50"
                onClick={() => onSelectCategory(c.category)}
              >
                <td className="py-1 pr-3">{c.category}</td>
                <td className="tabular py-1 pr-3 text-right">
                  {formatCents(c.total_cents)}
                </td>
                <td className="tabular py-1 text-right text-slate-400">
                  {c.transaction_count} txn{c.transaction_count === 1 ? '' : 's'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <PieChart>
            <Pie
              data={slices}
              dataKey="total_cents"
              nameKey="category"
              innerRadius={55}
              outerRadius={90}
              onClick={(entry) => {
                const category = (entry as unknown as { category: string }).category
                if (category !== 'Other') onSelectCategory(category)
              }}
            >
              {slices.map((s) => (
                <Cell key={s.category} fill={s.color} className="cursor-pointer" />
              ))}
            </Pie>
            <Tooltip formatter={(value) => formatCents(Number(value))} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
          </PieChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
