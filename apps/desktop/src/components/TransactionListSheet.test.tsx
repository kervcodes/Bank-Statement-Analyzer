import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { useSearchParams } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { API_BASE } from '../lib/api'
import { renderRoute } from '../test/render'
import { server } from '../test/server'
import { TransactionListSheet } from './TransactionListSheet'

function TxnParamProbe() {
  const [params] = useSearchParams()
  return <div data-testid="txn-param">{params.get('txn') ?? ''}</div>
}

const list = {
  items: [
    {
      id: 't1',
      transaction_date: '2026-08-15',
      merchant: 'Electric Company',
      description_normalized: 'ELECTRIC CO ACH DEBIT',
      amount_cents: -14219,
      direction: 'DEBIT',
      category: 'Utilities',
      category_source: 'RULE',
      bank: 'Chase',
      account_identifier_masked: '1234',
      dedup_status: 'UNIQUE',
    },
  ],
  page: 1,
  page_size: 25,
  total: 1,
}

describe('TransactionListSheet', () => {
  it('passes its filters through to the request', async () => {
    const captured = vi.fn()
    server.use(
      http.get(`${API_BASE}/transactions`, ({ request }) => {
        captured(new URL(request.url).searchParams.get('category'))
        return HttpResponse.json(list)
      }),
    )
    renderRoute(
      <>
        <TransactionListSheet
          open
          onOpenChange={() => {}}
          title="Dining"
          filters={{ category: 'Dining' }}
        />
        <TxnParamProbe />
      </>,
    )

    expect(await screen.findByText('Electric Company')).toBeInTheDocument()
    expect(captured).toHaveBeenCalledWith('Dining')
  })

  it('a row click opens the transaction drawer via ?txn=', async () => {
    server.use(
      http.get(`${API_BASE}/transactions`, () => HttpResponse.json(list)),
    )
    renderRoute(
      <>
        <TransactionListSheet
          open
          onOpenChange={() => {}}
          title="Dining"
          filters={{}}
        />
        <TxnParamProbe />
      </>,
    )

    await userEvent.click(await screen.findByText('Electric Company'))
    expect(screen.getByTestId('txn-param')).toHaveTextContent('t1')
  })
})
