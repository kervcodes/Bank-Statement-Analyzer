import { useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Trash2, XCircle } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '../components/ui/button'
import { Card } from '../components/ui/card'
import { Select } from '../components/ui/select'
import { api, CATEGORIES } from '../lib/api'
import {
  type DesktopSettings,
  type LlmProvider,
  getDesktopSettings,
  saveDesktopSettings,
} from '../lib/desktopSettings'

/** design-notes §3.7. Four sections: LLM provider/keys (REQ-SET-001), raw-PDF
 *  retention (REQ-SET-002), the category rule table (REQ-SET-003), and a
 *  reserved License placeholder (techstack.md §19 -- not built yet). */
export function SettingsRoute() {
  const { data: settings, isPending } = useQuery({
    queryKey: ['desktop-settings'],
    queryFn: getDesktopSettings,
    staleTime: Infinity,
  })

  if (isPending) return <p className="text-sm text-slate-500">Loading…</p>

  return (
    <div className="max-w-2xl space-y-4">
      <h1 className="text-lg font-semibold">Settings</h1>
      <LlmSection settings={settings} />
      <RetentionSection settings={settings} />
      <CategoryRulesSection />
      <LicenseSection />
    </div>
  )
}

function useTestKey() {
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; error: string | null } | null>(
    null,
  )
  const run = async (provider: LlmProvider, apiKey: string, model: string) => {
    setTesting(true)
    setResult(null)
    try {
      const res = await api.testLlmKey(provider, apiKey, model || undefined)
      setResult(res)
    } catch {
      setResult({ ok: false, error: 'Could not reach the backend.' })
    } finally {
      setTesting(false)
    }
  }
  return { testing, result, run, reset: () => setResult(null) }
}

function LlmSection({ settings }: { settings: DesktopSettings | undefined }) {
  const queryClient = useQueryClient()
  // Settings only renders this once `settings` has loaded (see SettingsRoute's
  // isPending check), so these are one-time initial values, not synced via an
  // effect -- the user's in-progress edits should never be stomped by a
  // background refetch.
  const [provider, setProvider] = useState<LlmProvider>(
    settings?.llmProvider ?? 'anthropic',
  )
  const [anthropicKey, setAnthropicKey] = useState('')
  const [openaiKey, setOpenaiKey] = useState('')
  const [anthropicModel, setAnthropicModel] = useState(settings?.anthropicModel ?? '')
  const [openaiModel, setOpenaiModel] = useState(settings?.openaiModel ?? '')
  const [saving, setSaving] = useState(false)

  const anthropicTest = useTestKey()
  const openaiTest = useTestKey()

  const save = async () => {
    setSaving(true)
    try {
      await saveDesktopSettings({
        llmProvider: provider,
        ...(anthropicKey && { anthropicApiKey: anthropicKey }),
        ...(openaiKey && { openaiApiKey: openaiKey }),
        anthropicModel: anthropicModel || null,
        openaiModel: openaiModel || null,
      })
      setAnthropicKey('')
      setOpenaiKey('')
      await queryClient.invalidateQueries({ queryKey: ['desktop-settings'] })
      toast.success('Settings saved. Restarting the backend to apply them…')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not save settings.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card className="space-y-4">
      <div>
        <h2 className="text-sm font-semibold">AI provider</h2>
        <p className="text-xs text-slate-500">
          Used for the Dashboard's plain-English summary and category suggestions.
          Bring your own key -- stored encrypted on this machine, never sent
          anywhere except the provider you choose.
        </p>
      </div>

      <div className="flex gap-4 text-sm">
        {(['anthropic', 'openai'] as const).map((p) => (
          <label key={p} className="flex items-center gap-1.5">
            <input
              type="radio"
              name="llm-provider"
              checked={provider === p}
              onChange={() => setProvider(p)}
            />
            {p === 'anthropic' ? 'Claude (Anthropic)' : 'OpenAI'}
          </label>
        ))}
      </div>

      <ProviderKeyRow
        label="Anthropic API key"
        hasSavedKey={settings?.hasAnthropicKey ?? false}
        value={anthropicKey}
        onChange={setAnthropicKey}
        model={anthropicModel}
        onModelChange={setAnthropicModel}
        modelPlaceholder="claude-sonnet-5"
        test={anthropicTest}
        provider="anthropic"
      />
      <ProviderKeyRow
        label="OpenAI API key"
        hasSavedKey={settings?.hasOpenaiKey ?? false}
        value={openaiKey}
        onChange={setOpenaiKey}
        model={openaiModel}
        onModelChange={setOpenaiModel}
        modelPlaceholder="gpt-5.6-luna"
        test={openaiTest}
        provider="openai"
      />

      <Button onClick={save} disabled={saving}>
        {saving ? 'Saving…' : 'Save'}
      </Button>
    </Card>
  )
}

function ProviderKeyRow({
  label,
  hasSavedKey,
  value,
  onChange,
  model,
  onModelChange,
  modelPlaceholder,
  test,
  provider,
}: {
  label: string
  hasSavedKey: boolean
  value: string
  onChange: (v: string) => void
  model: string
  onModelChange: (v: string) => void
  modelPlaceholder: string
  test: ReturnType<typeof useTestKey>
  provider: LlmProvider
}) {
  return (
    <div className="space-y-1.5 rounded-md border border-slate-200 p-3 dark:border-slate-800">
      <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
        {label}
      </label>
      <div className="flex gap-2">
        <input
          type="password"
          className="h-8 flex-1 rounded-md border border-slate-300 bg-white px-2 text-sm dark:border-slate-700 dark:bg-slate-900"
          placeholder={hasSavedKey ? '•••• saved (enter a new key to replace)' : 'sk-…'}
          value={value}
          onChange={(e) => {
            onChange(e.target.value)
            test.reset()
          }}
        />
        <Button
          variant="outline"
          size="sm"
          disabled={!value || test.testing}
          onClick={() => test.run(provider, value, model)}
        >
          {test.testing ? 'Testing…' : 'Test connection'}
        </Button>
      </div>
      <input
        type="text"
        className="h-8 w-full rounded-md border border-slate-300 bg-white px-2 text-xs dark:border-slate-700 dark:bg-slate-900"
        placeholder={`Model (default: ${modelPlaceholder})`}
        value={model}
        onChange={(e) => onModelChange(e.target.value)}
      />
      {test.result && (
        <p
          className={
            test.result.ok
              ? 'flex items-center gap-1 text-xs text-emerald-600'
              : 'flex items-center gap-1 text-xs text-rose-600'
          }
        >
          {test.result.ok ? (
            <CheckCircle2 className="h-3.5 w-3.5" />
          ) : (
            <XCircle className="h-3.5 w-3.5" />
          )}
          {test.result.ok ? 'Connection works.' : test.result.error}
        </p>
      )}
    </div>
  )
}

function RetentionSection({ settings }: { settings: DesktopSettings | undefined }) {
  const queryClient = useQueryClient()
  const [saving, setSaving] = useState(false)

  const toggle = async (retain: boolean) => {
    setSaving(true)
    try {
      await saveDesktopSettings({ retainRawPdfs: retain })
      await queryClient.invalidateQueries({ queryKey: ['desktop-settings'] })
      toast.success('Retention setting saved.')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not save the setting.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <h2 className="text-sm font-semibold">Data retention</h2>
      <label className="mt-2 flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={settings?.retainRawPdfs ?? false}
          disabled={saving}
          onChange={(e) => toggle(e.target.checked)}
        />
        Keep original PDF files after processing
      </label>
      <p className="mt-1 text-xs text-slate-500">
        Off by default: a statement's raw PDF is deleted immediately after it's
        processed. The extracted data (transactions, balances, categories) is
        kept either way -- this only controls whether the original file
        remains on disk. Turning it on uses more storage over time.
      </p>
    </Card>
  )
}

function CategoryRulesSection() {
  const queryClient = useQueryClient()
  const { data: rules, isPending } = useQuery({
    queryKey: ['category-rules'],
    queryFn: api.listCategoryRules,
  })
  const [merchant, setMerchant] = useState('')
  const [category, setCategory] = useState('')
  const [pending, setPending] = useState<string | null>(null)

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['category-rules'] })

  const add = async () => {
    if (!merchant.trim() || !category) return
    setPending(merchant)
    try {
      await api.upsertCategoryRule(merchant.trim(), category)
      setMerchant('')
      setCategory('')
      await invalidate()
    } finally {
      setPending(null)
    }
  }

  const remove = async (m: string) => {
    setPending(m)
    try {
      await api.deleteCategoryRule(m)
      await invalidate()
    } finally {
      setPending(null)
    }
  }

  return (
    <Card>
      <h2 className="text-sm font-semibold">Category rules</h2>
      <p className="mt-1 text-xs text-slate-500">
        "Always categorize X as Y" rules confirmed from Review, editable here
        directly.
      </p>

      {isPending ? (
        <p className="mt-2 text-sm text-slate-500">Loading…</p>
      ) : rules && rules.length > 0 ? (
        <ul className="mt-2 divide-y divide-slate-100 text-sm dark:divide-slate-800">
          {rules.map((r) => (
            <li key={r.merchant} className="flex items-center justify-between py-1.5">
              <span>
                {r.merchant} → <span className="text-slate-500">{r.category}</span>
              </span>
              <button
                className="text-slate-400 hover:text-rose-600"
                disabled={pending === r.merchant}
                onClick={() => remove(r.merchant)}
                aria-label={`Remove rule for ${r.merchant}`}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-slate-500">No rules yet.</p>
      )}

      <div className="mt-3 flex gap-2">
        <input
          type="text"
          className="h-8 flex-1 rounded-md border border-slate-300 bg-white px-2 text-sm dark:border-slate-700 dark:bg-slate-900"
          placeholder="Merchant"
          value={merchant}
          onChange={(e) => setMerchant(e.target.value)}
        />
        <Select value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="" disabled>
            Category…
          </option>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </Select>
        <Button
          size="sm"
          variant="outline"
          disabled={!merchant.trim() || !category || pending === merchant}
          onClick={add}
        >
          Add
        </Button>
      </div>
    </Card>
  )
}

function LicenseSection() {
  return (
    <Card>
      <h2 className="text-sm font-semibold">License</h2>
      <p className="mt-1 text-xs text-slate-500">Reserved for a future release.</p>
    </Card>
  )
}
