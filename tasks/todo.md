# Todo: Build-plan #9 — PR 3 (Accounts + Settings)

Branch `feature/accounts-settings` off `main` (PR #17 merged). Source: `build-plan.md` §9,
`design-notes.md` §3.5 / §3.7, `requirements.md` §15 (Settings) / §16 (Retention/Cleanup).

## Scope

**In:** Accounts (read-only), Settings (LLM provider/keys + test connection, raw-PDF retention
toggle + actual enforcement, category rules table), `GET /accounts`.
**Out:** nothing further deferred — this closes out build-plan #9. Next after this is #10
(Packaging).

## Investigation notes (why this needs a design decision, not just UI)

- **LLM keys today are env-var only** (`app/llm/providers.py` reads `ANTHROPIC_API_KEY` /
  `OPENAI_API_KEY` / `LLM_PROVIDER` from `os.environ` at call time). There is no settings
  persistence anywhere yet.
- **`techstack.md` requires `safeStorage`** for the keys (OS-keychain-backed encryption), which
  is an Electron/Node API — the Python backend cannot decrypt it directly. Electron is
  necessarily the only thing that ever sees a decrypted key.
- **Raw-PDF cleanup doesn't exist at all.** `POST /batches` writes every accepted file to
  `data/tmp/<batch_id>/<intake_file_id>.pdf` and nothing ever deletes it — a real gap against
  **REQ-CLEAN-001** (delete after processing unless retention is on), which `requirements.md`
  §17.2 marks as a security requirement, not optional.

## Design (needs a decision on one point — see below)

**Settings reach the backend the same way it already gets its config: environment variables at
spawn.** Electron (`electron/main.ts`) already owns `startBackend()`/`stopBackend()`. Adding:
- A local settings file in Electron's `userData` dir. Non-secret fields (`llmProvider`,
  `retainRawPdfs`, model names) stored plain; each API key stored as its own
  `safeStorage.encryptString()` blob. Never written to the SQLite DB (per `techstack.md`).
- `startBackend()` decrypts the stored keys and passes `LLM_PROVIDER` / `ANTHROPIC_API_KEY` /
  `ANTHROPIC_MODEL` / `OPENAI_API_KEY` / `OPENAI_MODEL` / `APP_RETAIN_RAW_PDFS` as env vars —
  exactly the mechanism `app/llm/providers.py` already reads today, plus one new var the
  processor checks before deleting a job's PDF.
- A new preload bridge (`window.desktop.getSettings()` / `.saveSettings(patch)`, mirroring the
  existing `shouldUseDarkColors`/`onThemeChange` pattern) — `getSettings` never returns a
  decrypted key or its ciphertext to the renderer, only `hasAnthropicKey`/`hasOpenaiKey`
  booleans, so a saved key is never shown again in plaintext (design-notes §3.7).
- **Saving settings restarts the backend** (`stopBackend(); startBackend()`) so the new env
  takes effect immediately. This is the one real trade-off: a brief (sub-second, local-only)
  interruption on every settings save, in exchange for zero new backend persistence/IPC surface
  and reusing a mechanism that already exists and is already tested.
  - *(Alternative considered: an in-memory settings store in the backend + a `PUT` endpoint
  Electron calls after decrypting, so changes apply with no restart. More backend surface for a
  screen that gets touched rarely — rejected unless you'd rather not have the restart.)*
- **"Test connection"** doesn't touch persistence at all: a new stateless
  `POST /settings/test-llm-key {provider, api_key, model?}` builds a throwaway
  `AnthropicProvider`/`OpenAIProvider` with the given key and calls `.explain()` on a trivial
  empty `OutboundAnalytics`; `LLMUnavailable` → `{ok: false, error}`, else `{ok: true}`. Never
  logs or persists the key (REQ-CLEAN-003).
- **Retention enforcement**: `app/workers/processor.py`, after a job reaches a *terminal* status
  (not `RETRYING` — it still needs the file for the next attempt) — delete `job.pdf_path` unless
  `APP_RETAIN_RAW_PDFS=1`.
- **Accounts stays read-only.** design-notes §3.5 mentions merging "mis-grouped" accounts, but
  `Account`'s identity is `(bank, account_type, masked_digits)` under a DB `UNIQUE` constraint —
  the current architecture cannot produce two provisional accounts that are actually the same
  one, so there is nothing to merge. Flagging this rather than silently building a merge action
  that has no real case to handle, or silently dropping a requirement.

## Backend

- [x] `GET /accounts` (`app/api/accounts.py`, new) — paginated, each item: bank, account_type,
      masked id, statement_count, period_start/end (same rollup-query shape as `GET /batches`).
- [x] `POST /settings/test-llm-key` (`app/api/settings.py`, new) — body
      `{provider: "anthropic"|"openai", api_key: str, model?: str}`; 422 unknown provider;
      `{ok, error}` response, no persistence.
- [x] `app/workers/processor.py` — delete a terminal job's `pdf_path` unless
      `APP_RETAIN_RAW_PDFS=1`. `app/workers/queue.py`'s `reclaim_processing_jobs` path is
      unaffected (a reclaimed job goes to `RETRYING` or `FAILED`; `FAILED` still needs cleanup —
      route both through the same helper).
- [x] Tests: `GET /accounts` rollup + pagination + empty; `test-llm-key` ok/error/422; PDF
      deleted after a terminal job unless retained; not deleted for a job still `RETRYING`.

## Frontend (`apps/desktop`)

- [x] `electron/main.ts` — settings file read/write, `safeStorage` encrypt/decrypt, env
      injection into `startBackend()`, `settings:get`/`settings:save` IPC handlers (save
      restarts the backend).
- [x] `electron/preload.ts` — `getSettings()` / `saveSettings(patch)` on `window.desktop`.
      `useTheme.ts`'s existing outside-Electron fallback pattern extended: outside Electron,
      `getSettings` returns sensible defaults and `saveSettings` no-ops with a toast explaining
      settings require the desktop app.
- [x] `routes/SettingsRoute.tsx` — LLM provider radio + per-provider key input (masked, "••••
      saved" when one exists, never re-shown) + Test connection button (hits the new backend
      endpoint directly, no IPC) + Save; retention toggle with the retained-data-usage note
      (design-notes §3.7); category rules table (`GET`/`PUT`/`DELETE /category-rules`, all
      already built) editable directly; a License section reserved as a placeholder (per
      `techstack.md` §19 — not built).
- [x] `routes/AccountsRoute.tsx` — plain list, `GET /accounts`, period + statement count per row
      (design-notes §3.5).
- [x] `router.tsx` — replace both remaining `Placeholder` routes.
- [x] Tests: `SettingsRoute` (key save flow with `window.desktop` mocked, test-connection
      success/failure, retention toggle, category rule add/delete); `AccountsRoute` (list +
      empty state).
- [x] Docs & checks: `pnpm lint`/`typecheck`/`test:run`/`build`; backend `pytest`/`ruff`;
      `docs/activity.md`; `README.md`; `docs/manual-verification-frontend-pr3.md`; this file's
      Review section.

## Review

**Done:** the approved design end to end — Electron owns `safeStorage`, the backend never
persists a secret, a save restarts the backend so the new env takes effect. `GET /accounts`
(read-only, no merge action — see the design note above on why). `POST /settings/test-llm-key`
routed through a new `llm_gateway.test_provider_key()` rather than importing `app.llm` from the
API layer, respecting the existing hard architectural boundary
(`test_only_the_gateway_imports_app_llm`) — caught by that test on the first attempt, fixed
before it went further. Raw-PDF cleanup (REQ-CLEAN-001) wired into both `process_job()` and
`reclaim_processing_jobs()`.

**Tests:** 17 new backend, 9 new frontend. 262 backend tests, 97.85% coverage, ruff clean; 48
frontend tests, lint/typecheck/build clean.

**Verified against real data and a real provider call:** a fresh backend + standalone Vite dev
server. Accounts showed the real resolved account and rollup. Settings: an intentionally-wrong
Anthropic key, tested for real against Anthropic's API, correctly reported the failure without
ever exposing the key; deleting a real category rule updated the list live. The
`safeStorage`/restart-on-save/persists-across-app-restart flow needs the real Electron app to
verify (browser automation can't drive it) — recorded in
`docs/manual-verification-frontend-pr3.md` for the owner.

**Known limitation, documented not built:** `techstack.md`'s "estimated-cost note" for LLM usage
in Settings — no cost-estimation logic exists anywhere in the codebase to surface; out of scope
for this PR.

**Recommended next step:** owner review — especially the safeStorage/restart flow per the
manual-verification doc — then merge. This closes out build-plan #9; #10 (Packaging) is next.
