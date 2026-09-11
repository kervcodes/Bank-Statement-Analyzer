import { app, safeStorage } from 'electron'
import fs from 'node:fs'
import path from 'node:path'

/** REQ-SET-001/002: LLM keys + the raw-PDF retention toggle.
 *
 * Lives entirely in Electron. Each key is its own `safeStorage` (OS-keychain)
 * blob -- never plaintext on disk, never the SQLite DB, never sent anywhere
 * except decrypted into the backend's own environment at spawn time (the
 * mechanism `app/llm/providers.py` already reads). The renderer never
 * receives a decrypted key or its ciphertext back (design-notes §3.7: "never
 * shown again in plaintext once saved") -- see `publicSettings()`.
 */

export type LlmProvider = 'anthropic' | 'openai'

interface StoredSettings {
  llmProvider: LlmProvider | null
  anthropicApiKeyEncrypted: string | null // base64
  openaiApiKeyEncrypted: string | null // base64
  anthropicModel: string | null
  openaiModel: string | null
  retainRawPdfs: boolean
}

const DEFAULTS: StoredSettings = {
  llmProvider: null,
  anthropicApiKeyEncrypted: null,
  openaiApiKeyEncrypted: null,
  anthropicModel: null,
  openaiModel: null,
  retainRawPdfs: false,
}

export interface PublicSettings {
  llmProvider: LlmProvider | null
  hasAnthropicKey: boolean
  hasOpenaiKey: boolean
  anthropicModel: string | null
  openaiModel: string | null
  retainRawPdfs: boolean
}

export interface SettingsPatch {
  llmProvider?: LlmProvider | null
  anthropicApiKey?: string // plaintext -- only present when the user is setting/changing it
  openaiApiKey?: string
  anthropicModel?: string | null
  openaiModel?: string | null
  retainRawPdfs?: boolean
}

function settingsPath(): string {
  return path.join(app.getPath('userData'), 'settings.json')
}

function readStored(): StoredSettings {
  try {
    const raw = fs.readFileSync(settingsPath(), 'utf-8')
    return { ...DEFAULTS, ...JSON.parse(raw) }
  } catch {
    return { ...DEFAULTS }
  }
}

function writeStored(settings: StoredSettings): void {
  fs.mkdirSync(path.dirname(settingsPath()), { recursive: true })
  fs.writeFileSync(settingsPath(), JSON.stringify(settings, null, 2), 'utf-8')
}

function encrypt(plaintext: string): string {
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error(
      'Secure storage is not available on this system -- cannot save an API key.',
    )
  }
  return safeStorage.encryptString(plaintext).toString('base64')
}

function decrypt(blob: string | null): string | null {
  if (!blob) return null
  try {
    return safeStorage.decryptString(Buffer.from(blob, 'base64'))
  } catch {
    return null // corrupt/foreign blob -- treat as "no key" rather than crash
  }
}

export function getPublicSettings(): PublicSettings {
  const s = readStored()
  return {
    llmProvider: s.llmProvider,
    hasAnthropicKey: s.anthropicApiKeyEncrypted !== null,
    hasOpenaiKey: s.openaiApiKeyEncrypted !== null,
    anthropicModel: s.anthropicModel,
    openaiModel: s.openaiModel,
    retainRawPdfs: s.retainRawPdfs,
  }
}

export function saveSettings(patch: SettingsPatch): PublicSettings {
  const current = readStored()
  const next: StoredSettings = { ...current }

  if (patch.llmProvider !== undefined) next.llmProvider = patch.llmProvider
  if (patch.anthropicModel !== undefined) next.anthropicModel = patch.anthropicModel
  if (patch.openaiModel !== undefined) next.openaiModel = patch.openaiModel
  if (patch.retainRawPdfs !== undefined) next.retainRawPdfs = patch.retainRawPdfs
  if (patch.anthropicApiKey !== undefined) {
    next.anthropicApiKeyEncrypted = encrypt(patch.anthropicApiKey)
  }
  if (patch.openaiApiKey !== undefined) {
    next.openaiApiKeyEncrypted = encrypt(patch.openaiApiKey)
  }

  writeStored(next)
  return getPublicSettings()
}

/** Env vars for spawning the backend -- the same variables
 * `app/llm/providers.py` and `app/workers/queue.py` already read. Only
 * includes a var when the setting is actually configured, so an unset
 * value falls through to the backend's own default. */
export function backendEnv(): Record<string, string> {
  const s = readStored()
  const env: Record<string, string> = {}
  if (s.llmProvider) env.LLM_PROVIDER = s.llmProvider
  const anthropicKey = decrypt(s.anthropicApiKeyEncrypted)
  if (anthropicKey) env.ANTHROPIC_API_KEY = anthropicKey
  if (s.anthropicModel) env.ANTHROPIC_MODEL = s.anthropicModel
  const openaiKey = decrypt(s.openaiApiKeyEncrypted)
  if (openaiKey) env.OPENAI_API_KEY = openaiKey
  if (s.openaiModel) env.OPENAI_MODEL = s.openaiModel
  env.APP_RETAIN_RAW_PDFS = s.retainRawPdfs ? '1' : '0'
  return env
}
