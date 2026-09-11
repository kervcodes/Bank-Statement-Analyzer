/** Mirrors `electron/settings.ts`'s public shapes -- kept as its own small
 *  type here rather than imported across the renderer/electron TS project
 *  boundary (same pattern as `lib/api.ts` mirroring the backend's Pydantic
 *  models rather than importing them). */

export type LlmProvider = 'anthropic' | 'openai'

export interface DesktopSettings {
  llmProvider: LlmProvider | null
  hasAnthropicKey: boolean
  hasOpenaiKey: boolean
  anthropicModel: string | null
  openaiModel: string | null
  retainRawPdfs: boolean
}

export interface DesktopSettingsPatch {
  llmProvider?: LlmProvider | null
  anthropicApiKey?: string
  openaiApiKey?: string
  anthropicModel?: string | null
  openaiModel?: string | null
  retainRawPdfs?: boolean
}

export const DEFAULT_DESKTOP_SETTINGS: DesktopSettings = {
  llmProvider: null,
  hasAnthropicKey: false,
  hasOpenaiKey: false,
  anthropicModel: null,
  openaiModel: null,
  retainRawPdfs: false,
}

/** Outside Electron (plain `vite`, or the test environment) there is no
 *  `window.desktop` bridge -- settings can't actually be saved. Callers
 *  should treat this as "read-only defaults" rather than throw, matching
 *  `useTheme.ts`'s existing outside-Electron fallback. */
export async function getDesktopSettings(): Promise<DesktopSettings> {
  return (await window.desktop?.getSettings()) ?? DEFAULT_DESKTOP_SETTINGS
}

export async function saveDesktopSettings(
  patch: DesktopSettingsPatch,
): Promise<DesktopSettings> {
  if (!window.desktop) {
    throw new Error('Settings require the desktop app (not available in the browser).')
  }
  return window.desktop.saveSettings(patch)
}
