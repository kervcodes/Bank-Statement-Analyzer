# Manual verification — build-plan #9, PR 3 (Accounts + Settings)

**Scope:** Accounts (read-only), Settings (LLM provider/keys + test connection, raw-PDF
retention, category rules), `GET /accounts`, `POST /settings/test-llm-key`. This closes out
build-plan #9.

All commands from `apps/desktop/` unless noted.

---

## 1. Automated checks

```powershell
pnpm install --frozen-lockfile
pnpm lint
pnpm typecheck
pnpm test:run
pnpm build
```

- [ ] All four pass.
- [ ] Backend: from `apps/backend`, `uv run pytest` green, `ruff check .` / `ruff format --check .`
      clean.

---

## 2. The app, end to end

```powershell
pnpm dev
```

### Accounts

- [ ] Lists every resolved account (bank, account type, masked digits), each with its statement
      count and period. Empty state when nothing has been imported yet.

### Settings — LLM provider

- [ ] Typing a key and clicking "Test connection" makes a real call to that provider and reports
      success or a specific error — try an obviously-wrong key and confirm it fails cleanly
      (never a raw stack trace, never the key echoed back).
- [ ] After **Save**, the app briefly shows the backend restarting (a toast, or the sidebar's
      processing indicator blipping) and the Anthropic/OpenAI field now reads "•••• saved (enter
      a new key to replace)" — the plaintext is never shown again.
- [ ] Restart the whole app (quit and reopen). The saved key still works — confirms it actually
      persisted via `safeStorage` and Electron re-injected it into the backend's environment on
      the next launch, not just for the current session.
- [ ] With a valid key saved, the Dashboard's AI summary panel shows the provider tag and real
      text (this exercises the same key end-to-end through the actual explain path, not just the
      test-connection ping).

### Settings — retention

- [ ] Import a statement with the toggle **off** (default). After it finishes processing, its
      temp PDF (`apps/backend/data/tmp/<batch_id>/<file>.pdf`) is gone from disk.
- [ ] Turn the toggle **on**, save, import another statement. Its temp PDF remains on disk after
      processing.

### Settings — category rules

- [ ] The table matches whatever rules Review has confirmed. Adding one here has the same effect
      as confirming it from Review (transactions re-resolve); deleting one reverts those
      transactions to their stored prediction, never deletes the transactions themselves.

---

## 3. Sign-off

- [ ] `pnpm lint` / `pnpm typecheck` / `pnpm test:run` / `pnpm build` all green; backend suite
      green.
- [ ] No API key ever appears in a log line, a network request other than to its own provider,
      or a UI element after being saved.
- [ ] A settings save that fails (e.g. secure storage unavailable) shows a clear error, not a
      silent no-op or a crash.
