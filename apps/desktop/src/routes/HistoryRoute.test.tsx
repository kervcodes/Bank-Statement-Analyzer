import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import { API_BASE } from '../lib/api'
import { renderRoute } from '../test/render'
import { server } from '../test/server'
import { HistoryRoute } from './HistoryRoute'

const emptyList = { items: [], page: 1, page_size: 20, total: 0 }

function batch(over: Partial<Record<string, unknown>> = {}) {
  return {
    id: 'b1',
    created_at: '2026-09-04T12:00:00Z',
    status: 'COMPLETED_WITH_WARNINGS',
    selected: 3,
    uploaded: 3,
    upload_failed: 0,
    validation_failed: 1,
    processed: 2,
    processing_failed: 0,
    statement_count: 2,
    period_start: '2026-01-01',
    period_end: '2026-08-31',
    ...over,
  }
}

describe('HistoryRoute', () => {
  it('shows the empty state and routes to Import', async () => {
    server.use(http.get(`${API_BASE}/batches`, () => HttpResponse.json(emptyList)))
    renderRoute(<HistoryRoute />)
    expect(await screen.findByText('No imports yet')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Import statements' }),
    ).toBeInTheDocument()
  })

  it('lists batches newest-first with a status badge and period label', async () => {
    server.use(
      http.get(`${API_BASE}/batches`, () =>
        HttpResponse.json({
          items: [batch()],
          page: 1,
          page_size: 20,
          total: 1,
        }),
      ),
    )
    renderRoute(<HistoryRoute />)
    expect(await screen.findByText('Jan 2026 – Aug 2026')).toBeInTheDocument()
    expect(screen.getByText('Completed with warnings')).toBeInTheDocument()
    expect(screen.getByText('2 / 3')).toBeInTheDocument()
  })

  it('expands a row to show its statements', async () => {
    server.use(
      http.get(`${API_BASE}/batches`, () =>
        HttpResponse.json({
          items: [batch()],
          page: 1,
          page_size: 20,
          total: 1,
        }),
      ),
      http.get(`${API_BASE}/batches/b1`, () =>
        HttpResponse.json({
          batch_id: 'b1',
          status: 'COMPLETED_WITH_WARNINGS',
          selected: 3,
          uploaded: 3,
          upload_failed: 0,
          validation_failed: 1,
          processed: 2,
          processing_failed: 0,
          possible_duplicate_count: 0,
          uncategorized_count: 0,
          jobs: [],
          statements: [
            {
              id: 's1',
              bank: 'Santander',
              account_type: 'checking',
              account_identifier_masked: '7890',
              extraction_status: 'SUCCESS',
              validation_result: 'VALID',
              dedup_status: 'UNIQUE',
            },
          ],
        }),
      ),
    )
    renderRoute(<HistoryRoute />)
    const row = await screen.findByText('Jan 2026 – Aug 2026')
    await userEvent.click(row)
    await waitFor(() =>
      expect(
        screen.getByText(/Santander checking ••7890/),
      ).toBeInTheDocument(),
    )
    expect(screen.getByText('1 file was rejected at intake.')).toBeInTheDocument()
  })
})
