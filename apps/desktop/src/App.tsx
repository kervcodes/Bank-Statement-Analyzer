import { Outlet } from 'react-router-dom'
import { Toaster } from 'sonner'
import { Sidebar } from './components/Sidebar'
import { useTheme } from './hooks/useTheme'

/** The shell: sidebar + routed content. */
export default function App() {
  useTheme()
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-y-auto p-6">
        <Outlet />
      </main>
      <Toaster position="bottom-right" richColors closeButton />
    </div>
  )
}
