import { Outlet } from 'react-router-dom'
import { Toaster } from 'sonner'
import { Sidebar } from './components/Sidebar'
import { TransactionDrawer } from './components/TransactionDrawer'
import { useTheme } from './hooks/useTheme'

/** The shell: sidebar + routed content. `TransactionDrawer` is mounted once
 *  here (not per-route) so `?txn=<id>` opens it over whatever screen is
 *  showing, matching design-notes §3.6. */
export default function App() {
  useTheme()
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-y-auto p-6">
        <Outlet />
      </main>
      <TransactionDrawer />
      <Toaster position="bottom-right" richColors closeButton />
    </div>
  )
}
