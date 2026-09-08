import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import { API_BASE } from '../lib/api'
import { renderRoute } from '../test/render'
import { server } from '../test/server'
import { ImportRoute } from './ImportRoute'

vi.mock('react-router-dom', async (orig) => ({
  ...(await orig<typeof import('react-router-dom')>()),
  useNavigate: () => vi.fn(),
}))

const pdf = (name: string, size = 1000) =>
  new File([new Uint8Array(size)], name, { type: 'application/pdf' })

async function pick(files: File[]) {
  const input = document.querySelector<HTMLInputElement>('input[type=file]')!
  await userEvent.upload(input, files)
}

describe('ImportRoute', () => {
  it('pre-checks files client-side before upload', async () => {
    renderRoute(<ImportRoute />)
    await pick([pdf('jan.pdf'), new File(['x'], 'shot.png', { type: 'image/png' })])

    expect(screen.getByText('jan.pdf')).toBeInTheDocument()
    expect(screen.getByText('ready')).toBeInTheDocument()
    expect(screen.getByText('not a PDF')).toBeInTheDocument()
    // the button counts only the ready file
    expect(
      screen.getByRole('button', { name: 'Start analysis (1)' }),
    ).toBeEnabled()
  })

  it('posts the ready files and shows the per-file backend result', async () => {
    let contentType: string | null = null
    server.use(
      http.post(`${API_BASE}/batches`, ({ request }) => {
        contentType = request.headers.get('content-type')
        return HttpResponse.json({
          batch_id: 'b9',
          status: 'PROCESSING',
          selected: 1,
          uploaded: 1,
          upload_failed: 0,
          validation_failed: 0,
          files: [
            { filename: 'jan.pdf', status: 'ACCEPTED', failure_reason: null },
            { filename: 'feb.pdf', status: 'VALIDATION_FAILED', failure_reason: 'corrupted PDF' },
          ],
        })
      }),
    )

    renderRoute(<ImportRoute />)
    await pick([pdf('jan.pdf'), pdf('feb.pdf')])
    await userEvent.click(
      screen.getByRole('button', { name: 'Start analysis (2)' }),
    )

    await waitFor(() => expect(screen.getByText('Ready')).toBeInTheDocument())
    // the second file's specific rejection reason is shown, not hidden
    expect(screen.getByText('Rejected')).toBeInTheDocument()
    expect(screen.getByText('corrupted PDF')).toBeInTheDocument()
    expect(contentType).toContain('multipart/form-data')
  })

  it('never blocks Start on a bad file', async () => {
    renderRoute(<ImportRoute />)
    await pick([
      pdf('good.pdf'),
      new File(['x'], 'notes.txt', { type: 'text/plain' }),
    ])
    expect(screen.getByText('good.pdf')).toBeInTheDocument()
    expect(screen.getByText('notes.txt')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Start analysis \(1\)/ }),
    ).toBeEnabled()
  })
})
