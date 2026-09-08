import { createHashRouter } from 'react-router-dom'
import App from './App'
import { HistoryRoute } from './routes/HistoryRoute'
import { ImportRoute } from './routes/ImportRoute'
import { Placeholder } from './routes/Placeholder'

// Hash routing: Electron loads the built app from file://, where path-based
// routing needs server rewrites. createHashRouter is the standard fit.
export const router = createHashRouter([
  {
    path: '/',
    element: <App />,
    children: [
      {
        index: true,
        element: (
          <Placeholder
            title="Dashboard"
            note="Cash flow, spending, and trends land in the next update."
          />
        ),
      },
      { path: 'import', element: <ImportRoute /> },
      { path: 'history', element: <HistoryRoute /> },
      {
        path: 'review',
        element: (
          <Placeholder
            title="Review"
            note="The attention inbox lands in the next update."
          />
        ),
      },
      {
        path: 'accounts',
        element: (
          <Placeholder
            title="Accounts"
            note="Your resolved accounts land in a later update."
          />
        ),
      },
      {
        path: 'settings',
        element: (
          <Placeholder
            title="Settings"
            note="LLM keys, retention, and category rules land in a later update."
          />
        ),
      },
    ],
  },
])
