import { screen } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import { API_BASE } from '../lib/api'
import { renderRoute } from '../test/render'
import { server } from '../test/server'
import { AccountsRoute } from './AccountsRoute'

describe('AccountsRoute', () => {
  it('shows the empty state', async () => {
    server.use(
      http.get(`${API_BASE}/accounts`, () =>
        HttpResponse.json({ items: [], page: 1, page_size: 20, total: 0 }),
      ),
    )
    renderRoute(<AccountsRoute />)
    expect(await screen.findByText('No accounts yet')).toBeInTheDocument()
  })

  it('lists accounts with their period and statement count', async () => {
    server.use(
      http.get(`${API_BASE}/accounts`, () =>
        HttpResponse.json({
          items: [
            {
              id: 'a1',
              bank: 'Chase',
              account_type: 'checking',
              account_identifier_masked: '1234',
              statement_count: 6,
              period_start: '2026-01-01',
              period_end: '2026-06-30',
            },
          ],
          page: 1,
          page_size: 20,
          total: 1,
        }),
      ),
    )
    renderRoute(<AccountsRoute />)
    expect(await screen.findByText('Chase checking ••1234')).toBeInTheDocument()
    expect(screen.getByText('Jan 2026 – Jun 2026')).toBeInTheDocument()
    expect(screen.getByText('6')).toBeInTheDocument()
  })
})
