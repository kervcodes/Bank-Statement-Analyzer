import { useEffect, useState } from 'react'

type HealthState =
  | { status: 'loading' }
  | { status: 'ok'; body: unknown }
  | { status: 'error'; message: string }

function App() {
  const [health, setHealth] = useState<HealthState>({ status: 'loading' })

  useEffect(() => {
    fetch('http://127.0.0.1:8420/health')
      .then((res) => res.json())
      .then((body) => setHealth({ status: 'ok', body }))
      .catch((err) =>
        setHealth({ status: 'error', message: String(err) }),
      )
  }, [])

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-100">
      <div className="rounded-lg border border-slate-800 bg-slate-900 px-8 py-6 text-center">
        <h1 className="text-lg font-semibold">Bank Statement Analyzer</h1>
        <p className="mt-2 text-sm text-slate-400">Backend health check</p>
        <pre className="mt-4 text-sm">
          {health.status === 'loading' && 'checking...'}
          {health.status === 'ok' && JSON.stringify(health.body)}
          {health.status === 'error' && `error: ${health.message}`}
        </pre>
      </div>
    </main>
  )
}

export default App
