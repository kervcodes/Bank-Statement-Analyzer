import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import {
  API_BASE,
  type DuplicatesResponse,
  type PossibleDuplicate,
  type UncategorizedResponse,
} from '../lib/api'
import { renderRoute } from '../test/render'
import { server } from '../test/server'
import { ReviewRoute } from './ReviewRoute'

const emptyBatches = { items: [], page: 1, page_size: 100, total: 0 }

const duplicatePair: PossibleDuplicate = {
  transaction: {
    id: 't1',
    statement_id: 's1',
    account_identifier_masked: '1234',
    bank: 'Chase',
    transaction_date: '2026-08-14',
    description_normalized: 'Starbucks',
    amount_cents: 782,
    direction: 'DEBIT',
  },
  matches: {
    id: 't2',
    statement_id: 's2',
    account_identifier_masked: '1234',
    bank: 'Chase',
    transaction_date: '2026-08-14',
    description_normalized: 'Starbucks',
    amount_cents: 782,
    direction: 'DEBIT',
  },
}

function baseHandlers({
  duplicates = { possible_duplicates: [] },
  categorizations = { groups: [] },
}: {
  duplicates?: DuplicatesResponse
  categorizations?: UncategorizedResponse
} = {}) {
  return [
    http.get(`${API_BASE}/review/duplicates`, () => HttpResponse.json(duplicates)),
    http.get(`${API_BASE}/review/categorizations`, () =>
      HttpResponse.json(categorizations),
    ),
    http.get(`${API_BASE}/batches`, () => HttpResponse.json(emptyBatches)),
  ]
}

describe('ReviewRoute', () => {
  it('shows an empty state per section when there is nothing to review', async () => {
    server.use(...baseHandlers())
    renderRoute(<ReviewRoute />)
    expect(await screen.findByText('Possible duplicates (0)')).toBeInTheDocument()
    expect(screen.getByText('Needs a category (0)')).toBeInTheDocument()
    expect(screen.getByText('Failed / unsupported statements (0)')).toBeInTheDocument()
  })

  it('keep_both posts the right body and refetches', async () => {
    let posted: unknown
    server.use(
      ...baseHandlers({ duplicates: { possible_duplicates: [duplicatePair] } }),
      http.post(`${API_BASE}/review/duplicates/t1`, async ({ request }) => {
        posted = await request.json()
        return HttpResponse.json({ id: 't1', dedup_status: 'UNIQUE' })
      }),
    )
    renderRoute(<ReviewRoute />)
    await screen.findByText('Possible duplicates (1)')

    await userEvent.click(screen.getByRole('button', { name: 'Keep both' }))

    await waitFor(() => expect(posted).toEqual({ action: 'keep_both' }))
  })

  it('confirm posts the right body', async () => {
    let posted: unknown
    server.use(
      ...baseHandlers({ duplicates: { possible_duplicates: [duplicatePair] } }),
      http.post(`${API_BASE}/review/duplicates/t1`, async ({ request }) => {
        posted = await request.json()
        return HttpResponse.json({ id: 't1', dedup_status: 'DUPLICATE' })
      }),
    )
    renderRoute(<ReviewRoute />)
    await screen.findByText('Possible duplicates (1)')

    await userEvent.click(screen.getByRole('button', { name: 'This is a duplicate' }))

    await waitFor(() => expect(posted).toEqual({ action: 'confirm' }))
  })

  it('a category confirm writes an explicit merchant-wide rule', async () => {
    const upsert = vi.fn()
    server.use(
      ...baseHandlers({
        categorizations: {
          groups: [
            {
              merchant: 'XYZ SERVICES',
              transaction_count: 3,
              total_cents: 8400,
              suggested_category: 'Home Services',
              sample_description: 'XYZ SERVICES ACH',
            },
          ],
        },
      }),
      http.put(`${API_BASE}/category-rules`, async ({ request }) => {
        upsert(await request.json())
        return HttpResponse.json({
          merchant: 'XYZ SERVICES',
          category: 'Home Services',
          transactions_recategorized: 3,
        })
      }),
    )
    renderRoute(<ReviewRoute />)
    await screen.findByText('Needs a category (1)')

    expect(
      screen.getByText('Always categorize XYZ SERVICES as Home Services'),
    ).toBeInTheDocument()
    await userEvent.click(
      screen.getByText('Always categorize XYZ SERVICES as Home Services'),
    )

    await waitFor(() =>
      expect(upsert).toHaveBeenCalledWith({
        merchant: 'XYZ SERVICES',
        category: 'Home Services',
      }),
    )
  })

  it('a failed batch links to History', async () => {
    server.use(
      http.get(`${API_BASE}/review/duplicates`, () =>
        HttpResponse.json({ possible_duplicates: [] }),
      ),
      http.get(`${API_BASE}/review/categorizations`, () =>
        HttpResponse.json({ groups: [] }),
      ),
      http.get(`${API_BASE}/batches`, () =>
        HttpResponse.json({
          items: [
            {
              id: 'b1',
              created_at: '2026-08-01T00:00:00Z',
              status: 'COMPLETED_WITH_WARNINGS',
              selected: 2,
              uploaded: 2,
              upload_failed: 0,
              validation_failed: 0,
              processed: 1,
              processing_failed: 1,
              statement_count: 1,
              period_start: '2026-07-01',
              period_end: '2026-07-31',
            },
          ],
          page: 1,
          page_size: 100,
          total: 1,
        }),
      ),
    )
    renderRoute(<ReviewRoute />)
    expect(
      await screen.findByText('Failed / unsupported statements (1)'),
    ).toBeInTheDocument()
    expect(screen.getByText('1 failed')).toBeInTheDocument()
  })
})
