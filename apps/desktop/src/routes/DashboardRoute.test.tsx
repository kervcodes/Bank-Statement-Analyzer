import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import { API_BASE } from '../lib/api'
import { renderRoute } from '../test/render'
import { server } from '../test/server'
import { DashboardRoute } from './DashboardRoute'

function analytics(over: Partial<Record<string, unknown>> = {}) {
  return {
    start: '2025-09-15',
    end: '2026-09-15',
    cash_flow: [
      {
        period: '2026-07',
        credits_cents: 500000,
        debits_cents: 400000,
        net_cents: 100000,
        spending_cents: 400000,
        transfers_cents: 0,
      },
      {
        period: '2026-08',
        credits_cents: 500000,
        debits_cents: 421000,
        net_cents: 79000,
        spending_cents: 421000,
        transfers_cents: 0,
      },
    ],
    spending_by_category: [
      { category: 'Dining', total_cents: 210000, transaction_count: 12 },
      { category: 'Groceries', total_cents: 150000, transaction_count: 8 },
    ],
    merchant_totals: [
      { merchant: 'Amazon', total_cents: 90000, transaction_count: 5 },
    ],
    recurring_charges: [
      {
        merchant: 'Netflix',
        cadence: 'monthly',
        typical_amount_cents: 2299,
        occurrences: 4,
        first_seen: '2026-05-01',
        last_seen: '2026-08-01',
      },
    ],
    trends: {
      current_period: '2026-08',
      previous_period: '2026-07',
      spending_delta_cents: 21000,
      spending_delta_ratio: '0.0525',
      net_delta_cents: -21000,
      net_delta_ratio: '-0.21',
    },
    coverage: {
      statements_included: 6,
      statements_excluded: 0,
      transaction_count: 42,
      ledger_start: '2026-01-01',
      ledger_end: '2026-08-31',
      excluded: [],
    },
    ...over,
  }
}

const explanationEmpty = { provider: null, model: null, text: null }

describe('DashboardRoute', () => {
  it('shows the empty-ledger state when nothing has been processed', async () => {
    server.use(
      http.get(`${API_BASE}/analytics`, () =>
        HttpResponse.json(
          analytics({
            cash_flow: [],
            spending_by_category: [],
            merchant_totals: [],
            recurring_charges: [],
            coverage: {
              statements_included: 0,
              statements_excluded: 0,
              transaction_count: 0,
              ledger_start: null,
              ledger_end: null,
              excluded: [],
            },
          }),
        ),
      ),
    )
    renderRoute(<DashboardRoute />)
    expect(await screen.findByText('Nothing processed yet')).toBeInTheDocument()
  })

  it('coverage bar reads green when nothing is excluded', async () => {
    server.use(
      http.get(`${API_BASE}/analytics`, () => HttpResponse.json(analytics())),
      http.get(`${API_BASE}/analytics/explanation`, () =>
        HttpResponse.json(explanationEmpty),
      ),
    )
    renderRoute(<DashboardRoute />)
    expect(await screen.findByText('6 of 6 statements')).toBeInTheDocument()
    expect(screen.queryByText(/excluded/)).not.toBeInTheDocument()
  })

  it('coverage bar reads amber and expands the excluded list', async () => {
    server.use(
      http.get(`${API_BASE}/analytics`, () =>
        HttpResponse.json(
          analytics({
            coverage: {
              statements_included: 5,
              statements_excluded: 1,
              transaction_count: 42,
              ledger_start: '2026-01-01',
              ledger_end: '2026-08-31',
              excluded: [
                {
                  statement_id: 's1',
                  bank: 'Chase',
                  account_identifier_masked: '1234',
                  period_start: '2026-08-01',
                  period_end: '2026-08-31',
                  reason: 'password-protected',
                },
              ],
            },
          }),
        ),
      ),
      http.get(`${API_BASE}/analytics/explanation`, () =>
        HttpResponse.json(explanationEmpty),
      ),
    )
    renderRoute(<DashboardRoute />)
    expect(await screen.findByText('5 of 6 statements')).toBeInTheDocument()
    expect(screen.getByText('1 excluded')).toBeInTheDocument()

    await userEvent.click(screen.getByText('1 excluded'))
    expect(screen.getByText('password-protected')).toBeInTheDocument()
  })

  it('AI panel shows the empty state with no provider configured', async () => {
    server.use(
      http.get(`${API_BASE}/analytics`, () => HttpResponse.json(analytics())),
      http.get(`${API_BASE}/analytics/explanation`, () =>
        HttpResponse.json(explanationEmpty),
      ),
    )
    renderRoute(<DashboardRoute />)
    expect(
      await screen.findByText('Add an API key in Settings to get a plain-English summary.'),
    ).toBeInTheDocument()
  })

  it('AI panel shows the provider tag and text when configured', async () => {
    server.use(
      http.get(`${API_BASE}/analytics`, () => HttpResponse.json(analytics())),
      http.get(`${API_BASE}/analytics/explanation`, () =>
        HttpResponse.json({
          provider: 'anthropic',
          model: 'claude',
          text: 'Dining drove most of the increase.',
        }),
      ),
    )
    renderRoute(<DashboardRoute />)
    expect(await screen.findByText('anthropic')).toBeInTheDocument()
    expect(
      screen.getByText('Dining drove most of the increase.'),
    ).toBeInTheDocument()
  })

  it('the cash-flow chart has a "show as table" toggle', async () => {
    server.use(
      http.get(`${API_BASE}/analytics`, () => HttpResponse.json(analytics())),
      http.get(`${API_BASE}/analytics/explanation`, () =>
        HttpResponse.json(explanationEmpty),
      ),
    )
    renderRoute(<DashboardRoute />)
    await screen.findByText('Cash flow, last 12 months')

    const toggles = screen.getAllByText('Show as table')
    await userEvent.click(toggles[0])
    expect(screen.getAllByText('Show chart').length).toBeGreaterThan(0)
  })
})
