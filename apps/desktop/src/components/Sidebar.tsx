import { useQuery } from '@tanstack/react-query'
import {
  LayoutDashboard,
  Upload,
  History,
  Inbox,
  Wallet,
  Settings,
  Loader,
} from 'lucide-react'
import { NavLink } from 'react-router-dom'
import { api } from '../lib/api'
import { cn } from '../lib/cn'

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/import', label: 'Import', icon: Upload },
  { to: '/history', label: 'History', icon: History },
  { to: '/review', label: 'Review', icon: Inbox },
  { to: '/accounts', label: 'Accounts', icon: Wallet },
]

export function Sidebar() {
  // A non-blocking "still processing" pill (design-notes §5). Polls only while
  // something is running.
  const { data } = useQuery({
    queryKey: ['batches', 'processing-check'],
    queryFn: () => api.listBatches(1, 5),
    refetchInterval: (q) =>
      q.state.data?.items.some((b) => b.status === 'PROCESSING') ? 3000 : false,
  })
  const processing =
    data?.items.filter((b) => b.status === 'PROCESSING').length ?? 0

  // One honest number for "things that need you" (design-notes §3.4) -- the
  // same queries Review itself runs, so mounting both costs no extra fetch.
  const duplicates = useQuery({
    queryKey: ['review', 'duplicates'],
    queryFn: api.getPossibleDuplicates,
  })
  const uncategorized = useQuery({
    queryKey: ['review', 'categorizations'],
    queryFn: api.getUncategorized,
  })
  const allBatches = useQuery({
    queryKey: ['batches', 'list', 1],
    queryFn: () => api.listBatches(1, 100),
  })
  const reviewCount =
    (duplicates.data?.possible_duplicates.length ?? 0) +
    (uncategorized.data?.groups.length ?? 0) +
    (allBatches.data?.items.filter((b) => b.processing_failed > 0).length ?? 0)

  return (
    <nav className="flex w-52 shrink-0 flex-col border-r border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
      <div className="px-2 pb-3 text-sm font-semibold">
        Bank Statement Analyzer
      </div>

      <ul className="flex flex-1 flex-col gap-0.5">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <li key={to}>
            <NavLink to={to} end={end} className={linkClass}>
              <Icon className="h-4 w-4" aria-hidden />
              {label}
              {to === '/review' && reviewCount > 0 && (
                <span className="ml-auto rounded-full bg-amber-100 px-1.5 text-xs font-medium text-amber-800 dark:bg-amber-950 dark:text-amber-300">
                  {reviewCount}
                </span>
              )}
            </NavLink>
          </li>
        ))}
      </ul>

      {processing > 0 && (
        <div className="mb-2 flex items-center gap-1.5 rounded-md bg-sky-50 px-2.5 py-1.5 text-xs text-sky-800 dark:bg-sky-950 dark:text-sky-300">
          <Loader className="h-3 w-3 animate-spin" aria-hidden />
          {processing} batch{processing > 1 ? 'es' : ''} processing
        </div>
      )}

      <NavLink to="/settings" className={linkClass}>
        <Settings className="h-4 w-4" aria-hidden />
        Settings
      </NavLink>
    </nav>
  )
}

function linkClass({ isActive }: { isActive: boolean }) {
  return cn(
    'flex items-center gap-2 rounded-md px-2 py-1.5 text-sm',
    isActive
      ? 'bg-slate-100 font-medium text-slate-900 dark:bg-slate-800 dark:text-slate-100'
      : 'text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800',
  )
}
