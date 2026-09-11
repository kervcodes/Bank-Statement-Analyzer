import { createHashRouter } from 'react-router-dom'
import App from './App'
import { AccountsRoute } from './routes/AccountsRoute'
import { DashboardRoute } from './routes/DashboardRoute'
import { HistoryRoute } from './routes/HistoryRoute'
import { ImportRoute } from './routes/ImportRoute'
import { ReviewRoute } from './routes/ReviewRoute'
import { SettingsRoute } from './routes/SettingsRoute'

// Hash routing: Electron loads the built app from file://, where path-based
// routing needs server rewrites. createHashRouter is the standard fit.
export const router = createHashRouter([
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <DashboardRoute /> },
      { path: 'import', element: <ImportRoute /> },
      { path: 'history', element: <HistoryRoute /> },
      { path: 'review', element: <ReviewRoute /> },
      { path: 'accounts', element: <AccountsRoute /> },
      { path: 'settings', element: <SettingsRoute /> },
    ],
  },
])
