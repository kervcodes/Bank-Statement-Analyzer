# Manual verification — build-plan #9, PR 1 (shell + Import + History)

**Scope:** the vertical slice — open app → import statements → backend processes → frontend
reports status → see previous imports. Dashboard / Review / Accounts / Settings are honest
placeholders in this PR.

All commands from `apps/desktop/` unless noted.

---

## 1. Automated checks

```powershell
pnpm install --frozen-lockfile
pnpm lint          # oxlint
pnpm typecheck     # tsc -b
pnpm test:run      # vitest
pnpm build         # tsc + vite (renderer + electron main + preload)
```

- [ ] All four pass. `pnpm test:run` reports the `format` / `ImportRoute` / `HistoryRoute`
      suites green.
- [ ] Backend: from `apps/backend`, `uv run pytest` still green (223+), including the new
      `test_list_batches_*` cases.

---

## 2. `GET /batches` by hand

Start the backend (`apps/backend`: `uv run uvicorn app.main:app --port 8420`).

```powershell
curl.exe -s "http://127.0.0.1:8420/batches?page=1&page_size=5" | ConvertFrom-Json | ConvertTo-Json -Depth 5
```

- [ ] Response has `items` / `page` / `page_size` / `total`.
- [ ] `page_size=0` or `page_size=200` → HTTP 422.
- [ ] After processing a real statement, its batch item has `statement_count`, `period_start`,
      `period_end` populated and `status` one of `COMPLETED` / `COMPLETED_WITH_WARNINGS`.

---

## 3. The app, end to end

```powershell
pnpm dev
```

(Electron spawns the backend itself in dev.)

- [ ] The window opens to the **Dashboard** placeholder; the sidebar shows Dashboard / Import /
      History / Review / Accounts / Settings, and Settings pinned at the bottom.
- [ ] Toggle the OS between light and dark → the app follows within a moment.
- [ ] **History** with no data → "No imports yet" + an "Import statements" button that
      navigates to Import.

### Import

- [ ] Drag 2–3 real PDFs + one non-PDF onto the drop zone (or use Browse).
- [ ] Each row shows its size and a status: PDFs → "ready", the non-PDF → "not a PDF", before
      anything is uploaded.
- [ ] "Start analysis (N)" shows the count of ready files only; it is **not** disabled by the
      bad file. Removing a file with the × updates the count.
- [ ] Click Start → a toast ("N statements queued…") and you land on **History** with the new
      batch.

### History + progress

- [ ] The new batch row appears at the top, status "Processing" (blue, with a spinner icon and
      the word — never colour alone).
- [ ] The sidebar shows a "1 batch processing" pill while it runs; both clear when done.
- [ ] Within a few seconds the row flips to "Completed" or "Completed with warnings" without a
      manual refresh.
- [ ] Expand the row → each produced statement with its bank / account / validation status
      (Valid / Warning / Failed), plus a note if any file was rejected at intake.
- [ ] Reload the app → History still lists the batch (it's real data, not session state).
- [ ] `#/history?page=1&batch=<id>` in the address — the page and expanded row come from the
      URL (refresh keeps them).

---

## 4. Sign-off

- [ ] `pnpm lint` / `pnpm typecheck` / `pnpm test:run` / `pnpm build` all green; backend suite
      green.
- [ ] A real PDF imported through the UI produces a batch that reaches a terminal status and is
      visible in History with its statements — no mock data anywhere.
- [ ] One bad file never blocks the good ones (design-notes §principle 5).
- [ ] Status is always colour + icon + word (design-notes §4).
- [ ] Dark mode follows the OS.
