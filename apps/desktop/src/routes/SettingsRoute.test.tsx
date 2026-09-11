import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { API_BASE } from '../lib/api'
import type { DesktopSettings, DesktopSettingsPatch } from '../lib/desktopSettings'
import { renderRoute } from '../test/render'
import { server } from '../test/server'
import { SettingsRoute } from './SettingsRoute'

const DEFAULTS: DesktopSettings = {
  llmProvider: null,
  hasAnthropicKey: false,
  hasOpenaiKey: false,
  anthropicModel: null,
  openaiModel: null,
  retainRawPdfs: false,
}

function installDesktopBridge(overrides: Partial<DesktopSettings> = {}) {
  const settings: DesktopSettings = { ...DEFAULTS, ...overrides }
  const saveSettings = vi.fn(async (patch: DesktopSettingsPatch) => {
    Object.assign(settings, {
      ...patch,
      hasAnthropicKey: patch.anthropicApiKey ? true : settings.hasAnthropicKey,
      hasOpenaiKey: patch.openaiApiKey ? true : settings.hasOpenaiKey,
    })
    return settings
  })
  window.desktop = {
    shouldUseDarkColors: () => false,
    onThemeChange: () => () => {},
    getSettings: async () => settings,
    saveSettings,
  }
  return { settings, saveSettings }
}

afterEach(() => {
  delete window.desktop
})

describe('SettingsRoute', () => {
  it('shows an unconfigured state with no window.desktop bridge', async () => {
    renderRoute(<SettingsRoute />)
    expect(await screen.findByText('AI provider')).toBeInTheDocument()
    expect(
      screen.getAllByPlaceholderText('sk-…', { exact: false })[0],
    ).toBeInTheDocument()
  })

  it('test connection reports success', async () => {
    installDesktopBridge()
    server.use(
      http.post(`${API_BASE}/settings/test-llm-key`, () =>
        HttpResponse.json({ ok: true, error: null }),
      ),
    )
    renderRoute(<SettingsRoute />)
    await screen.findByText('AI provider')

    const [anthropicKeyInput] = screen.getAllByPlaceholderText(/sk-/i)
    await userEvent.type(anthropicKeyInput, 'sk-ant-fake')
    await userEvent.click(screen.getAllByRole('button', { name: 'Test connection' })[0])

    expect(await screen.findByText('Connection works.')).toBeInTheDocument()
  })

  it('test connection reports the error message', async () => {
    installDesktopBridge()
    server.use(
      http.post(`${API_BASE}/settings/test-llm-key`, () =>
        HttpResponse.json({ ok: false, error: 'anthropic: HTTPStatusError' }),
      ),
    )
    renderRoute(<SettingsRoute />)
    await screen.findByText('AI provider')

    const [anthropicKeyInput] = screen.getAllByPlaceholderText(/sk-/i)
    await userEvent.type(anthropicKeyInput, 'sk-bad')
    await userEvent.click(screen.getAllByRole('button', { name: 'Test connection' })[0])

    expect(await screen.findByText('anthropic: HTTPStatusError')).toBeInTheDocument()
  })

  it('saving writes the typed key and provider through the desktop bridge', async () => {
    const { saveSettings } = installDesktopBridge()
    renderRoute(<SettingsRoute />)
    await screen.findByText('AI provider')

    const [anthropicKeyInput] = screen.getAllByPlaceholderText(/sk-/i)
    await userEvent.type(anthropicKeyInput, 'sk-ant-new')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(saveSettings).toHaveBeenCalledWith(
        expect.objectContaining({
          llmProvider: 'anthropic',
          anthropicApiKey: 'sk-ant-new',
        }),
      ),
    )
  })

  it('an already-saved key shows as saved, never the plaintext', async () => {
    installDesktopBridge({ hasAnthropicKey: true })
    renderRoute(<SettingsRoute />)
    expect(
      await screen.findByPlaceholderText(/saved \(enter a new key to replace\)/),
    ).toBeInTheDocument()
  })

  it('toggling retention saves through the desktop bridge', async () => {
    const { saveSettings } = installDesktopBridge({ retainRawPdfs: false })
    renderRoute(<SettingsRoute />)
    const checkbox = await screen.findByLabelText('Keep original PDF files after processing')

    await userEvent.click(checkbox)

    await waitFor(() =>
      expect(saveSettings).toHaveBeenCalledWith({ retainRawPdfs: true }),
    )
  })

  it('adds and removes a category rule', async () => {
    installDesktopBridge()
    let rules: { merchant: string; category: string }[] = []
    server.use(
      http.get(`${API_BASE}/category-rules`, () => HttpResponse.json(rules)),
      http.put(`${API_BASE}/category-rules`, async ({ request }) => {
        const body = (await request.json()) as { merchant: string; category: string }
        rules = [...rules, body]
        return HttpResponse.json({
          merchant: body.merchant,
          category: body.category,
          transactions_recategorized: 1,
        })
      }),
      http.delete(`${API_BASE}/category-rules/:merchant`, ({ params }) => {
        rules = rules.filter((r) => r.merchant !== params.merchant)
        return HttpResponse.json({
          merchant: params.merchant,
          category: null,
          transactions_recategorized: 1,
        })
      }),
    )
    renderRoute(<SettingsRoute />)
    await screen.findByText('No rules yet.')

    await userEvent.type(screen.getByPlaceholderText('Merchant'), 'Netflix')
    await userEvent.selectOptions(screen.getByDisplayValue('Category…'), 'Subscriptions')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))

    expect(await screen.findByText(/Netflix/)).toBeInTheDocument()

    await userEvent.click(screen.getByLabelText('Remove rule for Netflix'))

    await waitFor(() => expect(screen.getByText('No rules yet.')).toBeInTheDocument())
  })
})
