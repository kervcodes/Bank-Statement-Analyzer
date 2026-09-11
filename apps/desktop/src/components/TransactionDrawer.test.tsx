import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import { API_BASE } from '../lib/api'
import { renderRoute } from '../test/render'
import { server } from '../test/server'
import { TransactionDrawer } from './TransactionDrawer'

function detail(over: Partial<Record<string, unknown>> = {}) {
  return {
    id: 't1',
    transaction_date: '2026-08-15',
    posted_date: '2026-08-16',
    amount_cents: -14219,
    direction: 'DEBIT',
    category: 'Utilities',
    category_source: 'RULE',
    predicted_category: 'Utilities',
    user_category: null,
    merchant_normalized: 'Electric Company',
    description_normalized: 'ELECTRIC CO ACH DEBIT',
    description_raw: 'ELECTRIC CO ACH DEBIT 08/15',
    dedup_status: 'UNIQUE',
    source: {
      statement_id: 's1',
      bank: 'Chase',
      account_type: 'checking',
      account_identifier_masked: '1234',
      period_start: '2026-08-01',
      period_end: '2026-08-31',
      source_page: 3,
      parser_version: 'chase_checking_v2',
    },
    ...over,
  }
}

describe('TransactionDrawer', () => {
  it('is closed when there is no ?txn= param', () => {
    renderRoute(<TransactionDrawer />, '/')
    expect(screen.queryByText('Transaction')).not.toBeInTheDocument()
  })

  it('renders the source block from ?txn=<id>', async () => {
    server.use(
      http.get(`${API_BASE}/transactions/t1`, () => HttpResponse.json(detail())),
    )
    renderRoute(<TransactionDrawer />, '/?txn=t1')

    expect(await screen.findByText('Electric Company')).toBeInTheDocument()
    expect(screen.getByText('-$142.19 · Aug 15, 2026')).toBeInTheDocument()
    expect(
      screen.getByText('Page 3 · Parser chase_checking_v2'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('ELECTRIC CO ACH DEBIT 08/15'),
    ).toBeInTheDocument()
  })

  it('editing the category posts the change and closes the editor', async () => {
    server.use(
      http.get(`${API_BASE}/transactions/t1`, () => HttpResponse.json(detail())),
      http.put(`${API_BASE}/transactions/t1/category`, async ({ request }) => {
        const body = (await request.json()) as { category: string }
        expect(body.category).toBe('Housing')
        return HttpResponse.json({
          id: 't1',
          merchant_normalized: 'Electric Company',
          category: 'Housing',
          category_source: 'USER',
          predicted_category: 'Utilities',
          user_category: 'Housing',
        })
      }),
    )
    renderRoute(<TransactionDrawer />, '/?txn=t1')

    await screen.findByText('Electric Company')
    await userEvent.click(screen.getByLabelText('Edit category'))
    await userEvent.selectOptions(screen.getByRole('combobox'), 'Housing')

    await waitFor(() =>
      expect(screen.queryByRole('combobox')).not.toBeInTheDocument(),
    )
  })
})
