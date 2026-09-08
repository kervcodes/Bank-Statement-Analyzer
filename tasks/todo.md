# Todo: Build-plan #9 — Frontend screens

Source: `build-plan.md` §9, `design-notes.md` §2–§6, `techstack.md` §3 (stack: Electron, Vite +
React 19 + TS, Tailwind v4, TanStack Query; `design-notes` adds shadcn/ui + `lucide-react`).
Branch `feature/frontend-screens` off `main` (backend feature-complete through #8).

## Goal

A working Electron/React app against the real backend: **Import, History, Dashboard, Review**
(the four screens `build-plan` §9 names), plus the app shell, the transaction drawer, and the
supporting screens (Accounts, Settings). Real batch progress and coverage — no mock data.

## What exists now

`apps/desktop` is the bare skeleton: one `App.tsx` that fetches `/health`. Tailwind v4 wired,
Electron main spawns the backend, `oxlint` for linting, **no router, no data layer, no
component library, no tests**. Backend API in place: `POST /batches`, `GET /batches/{id}`,
`GET /analytics`, `GET /analytics/explanation`, `GET /review/duplicates`,
`GET /review/categorizations`, `PUT /transactions/{id}/category`, `GET`/`PUT`/`DELETE
/category-rules`.

## Backend gaps the frontend needs (small, additive — no migration)

| Endpoint | For | Notes |
|---|---|---|
| `GET /batches` | History list | id, created_at, counters, status, statement count. Ordered newest first. |
| `GET /accounts` | Accounts screen | bank, type, masked id, statement count, date range. |
| `GET /transactions/{id}` | Transaction drawer (§3.6) | amount, date, direction, category + source, `merchant_normalized`, `description_raw`, statement (bank/period), `source_page`, `parser_version`. |
| `GET /transactions?…` | Drill-through from a chart/stat (§ principle 4) | filter by `category` / `merchant` / `start` / `end` / `statement_id`, over the deduplicated ledger. Paginated. |
| `POST /statements/{id}/retry` *(maybe)* | Review "re-upload / retry" | only if a retry path is cheap; otherwise Review links to Import. |

Each gets a thin router + tests, same style as the existing API.

## Frontend foundation

- **Deps:** `@tanstack/react-query`, `react-router-dom` (hash router — Electron `file://`),
  `lucide-react`, `class-variance-authority` + `clsx` + `tailwind-merge` (shadcn/ui utils),
  `recharts` (Dashboard charts — see the `dataviz` skill), `@radix-ui/*` primitives as shadcn
  components pull them in.
- **shadcn/ui**: vendor the handful of primitives actually used (Button, Card, Table, Badge,
  Sheet, Dialog, Tabs, Select, Input, Sonner/toast) into `src/components/ui/` — not the whole
  library. Tailwind v4 config for the slate theme + CSS variables.
- **Dark mode**: `dark:` variants off `nativeTheme.shouldUseDarkColors`, bridged through
  `preload.ts` (`window.desktop.theme`), with an OS-change listener.
- **App shell** (`design-notes` §2): left sidebar (Dashboard / Import / History / Review /
  Accounts / Settings), Review badge count (from `/review/*` totals), a processing pill near
  Import/History when any batch is `PROCESSING` (§5), routing, a `QueryClientProvider`, an
  error boundary that shows a friendly message not a stack trace (§ principle 5, §error
  states).
- **`src/lib/api.ts`**: typed fetch wrappers + query keys, one base URL (`127.0.0.1:8420`).
- **`src/lib/format.ts`**: `formatCents`, `formatDate`, `tabular-nums` helpers, the status →
  {color, icon, label} map (§4 — colour is never the only signal).

## Screens

### Import (§3.2)
- Drag-drop / browse; per-file rows with immediate **client-side** pre-check (extension, size)
  showing `ready` / `rejected` before upload.
- `POST /batches` (multipart) → the response's per-file `ACCEPTED` / `UPLOAD_FAILED` /
  `VALIDATION_FAILED` with the specific reason.
- "Start analysis (N)" — label shows the count that will actually process; never blocked by a
  bad file.
- On start → navigate to History (or a progress view) polling `GET /batches/{id}` until
  terminal; toast on completion (§5).

### History (§3.3)
- `GET /batches` table (TanStack Table): batch label (date range of its statements), date,
  `processed / total`, status badge.
- Expand a row → its statements (`GET /batches/{id}` → `statements[]`) with per-statement
  `validation_result` / `dedup_status`, a retry action for retryable failures.
- First-launch empty state routes to Import (§empty states).

### Dashboard (§3.1)
- Top: **coverage bar** — `GET /analytics` → `coverage` (included/excluded, date span). Green
  pill when clean, expands amber with the excluded list when not; click → History filtered.
  **Pinned above every figure** (§ principle 1).
- Date-range filter top-right (all time / last 12 mo / this year / custom) → drives `start` /
  `end` on every query. (Decision D-b below.)
- Stat cards: net cash flow, monthly spending, top category — `tabular-nums`, each clickable →
  drawer / filtered transaction list.
- Cash-flow chart (12 mo, credits/debits/net, `transfers` shown separately) + spending-by-
  category donut — `recharts`, each segment clickable, each with an accessible data-table
  toggle (§accessibility).
- Recurring charges + top merchants lists.
- **AI summary panel** — `GET /analytics/explanation`; its own labelled box with the provider
  tag and a Refresh button; when `provider` is null, a plain "add an API key in Settings"
  empty state (§ principle 2).

### Review (§3.4)
- One list, three grouped sections:
  - **Possible duplicates** — `GET /review/duplicates`; `[Keep both]` / `[This is a dup]`
    (needs backend actions — see decision D-d).
  - **Needs a category** — `GET /review/categorizations`; `[Confirm <suggested>]` /
    `[Pick different]` → `PUT /transactions/{id}/category` (per-txn) or `PUT /category-rules`
    (merchant-wide) — the two are distinct actions per the Part-1 design.
  - **Failed / unsupported statements** — from `GET /batches` scan; `[Re-upload]` → Import.
- Badge count = duplicates + uncategorized groups + failed statements.

### Accounts (§3.5)
- `GET /accounts` list. (Merge action → deferred; v1 is read-only + a note. Decision D-e.)

### Settings (§3.7)
- LLM provider radio + per-provider key field + "test connection"; data-retention toggle;
  category-rules table (`GET`/`PUT`/`DELETE /category-rules`).
- **Key storage**: Electron `safeStorage` via `preload.ts` → the main process writes the
  encrypted blob and injects `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` into the backend spawn
  env. The renderer never holds a key. (This is the piece deferred from #8 Part 2.)

### Transaction drawer (§3.6)
- shadcn `Sheet`, opens over any screen. `GET /transactions/{id}` → merchant, amount, date,
  category (with `[edit]` → `PUT`), account, the **Source block** (statement, page, parser
  version — always present), raw text.

## Testing

- Add **Vitest + React Testing Library + `@testing-library/jest-dom`** (`apps/desktop` has no
  test runner). Cover the logic that hides bugs, not pixels: `format.ts` (currency, dates,
  status map), the coverage-bar state machine (clean / warnings / failed), Import's per-file
  pre-check, Review action wiring (with a mocked API). MSW for API mocking.
- `apps/desktop/package.json`: `test`, `typecheck` (`tsc -b --noEmit`) scripts.
- **CI**: add a `frontend` job to `.github/workflows/ci.yml` — `pnpm install`, `oxlint`,
  `tsc`, `vitest run`. (Backend job unchanged.) Add `frontend` to the branch-protection
  required checks once it's run green once.

## Proposed split (3 PRs)

1. **Foundation + Import + History + `GET /batches`** — the "did my upload work" loop, real
   data end to end. Includes the shell, deps, theme, test setup, CI frontend job.
2. **Dashboard + Review + Transaction drawer** + `GET /transactions/{id}`, `GET /transactions`,
   the Review write actions.
3. **Accounts + Settings + `safeStorage`** + `GET /accounts`.

## LOCKED decisions (owner)

- **Router:** `react-router-dom` v7, `createHashRouter`.
- **Dashboard default:** last 12 months on first load; a date-range control is present.
- **Charts:** Recharts. Financial values must also exist as accessible/drillable
  numbers/tables, not only in a chart.
- **Duplicate review actions:** `keep_both` → `UNIQUE`, `confirm` → `DUPLICATE`. No undo UI in
  v1; both re-runnable; never delete the row; a confirmed duplicate stays
  traceable/queryable but is excluded from analytics. `keep_both` = both are legitimate, not
  "erase the review history". No migration just for audit history — existing dedup metadata is
  enough.
- **Accounts:** read-only in v1; merge deferred.
- **PR 1 scope:** shell, sidebar/nav, routing, TanStack Query, shadcn foundation, dark mode,
  Vitest + RTL, frontend CI, `GET /batches`, Import, History. **No Dashboard or Review.**
- **Pagination:** no unbounded list endpoints. `GET /batches` gets `page` / `page_size` /
  deterministic sort now. `GET /transactions` (PR 2) planned with `category` / `merchant` /
  `account_id` / `batch_id` / `date_from` / `date_to` / `page` / `page_size` / `sort`.
- **State boundaries:** TanStack Query = server state; local React state = UI-only; router
  search params = navigation/filter state. No Redux/Zustand.
- **Foundation stays minimal** — build only what Import + History need; not a design-system
  project.

## PR 1 — Foundation + Import + History  ✅

- [x] **`GET /batches`** (`app/api/batches.py`) — paginated (`page` ≥1, `page_size` 1–100),
      sort `created_at DESC, id DESC`, `{items, page, page_size, total}`; per-item statement
      rollup (`statement_count` / `period_start` / `period_end`) in one grouped query. 4 tests.
- [x] Deps: `@tanstack/react-query`, `react-router-dom` v7, `lucide-react`, `sonner`, shadcn
      utils; dev `vitest` + RTL + `jsdom` + `msw`.
- [x] Shell: `App.tsx` (sidebar + `<Outlet/>` + `<Toaster/>`), `Sidebar.tsx` (+ processing
      pill), `ErrorBoundary`, `createHashRouter`, `QueryClientProvider` in `main.tsx`.
- [x] `lib/api.ts` (typed fetch, `ApiError`), `lib/format.ts` (`formatPeriod` tz-safe,
      `formatBytes`, status→`{tone,label,icon}` map), `lib/cn.ts`.
- [x] `components/ui/` — `button`, `card`, `StatusBadge` (colour + icon + word, always).
- [x] Dark mode: `.dark` on `<html>` from Electron `nativeTheme` via `preload.ts`
      (`window.desktop`), `matchMedia` fallback; Tailwind v4 `@custom-variant dark`.
- [x] `ImportRoute` — drag/browse, client pre-check per file, `POST /batches`, per-file result
      badges + reasons, "Start analysis (N)" (ready count, never blocked), → History + toast.
- [x] `HistoryRoute` — `GET /batches` table + pagination, expand → `GET /batches/{id}`
      statements, empty state → Import, `?page` / `?batch` in the URL, polls while non-terminal.
- [x] Dashboard / Review / Accounts / Settings routes = "lands in the next update" placeholders.
- [x] Vitest: `format.test.ts`, `ImportRoute.test.tsx`, `HistoryRoute.test.tsx` (MSW) — 14
      pass. `pnpm lint` / `pnpm typecheck` / `pnpm build` clean.
- [x] CI `frontend` job (`pnpm install --frozen-lockfile` → lint → typecheck → test,
      `ELECTRON_SKIP_BINARY_DOWNLOAD=1`).
- [x] `docs/activity.md`, `README.md`, `docs/manual-verification-frontend-pr1.md`.

## PR 2 / PR 3 (not started)

- **PR 2:** Dashboard (§3.1) + Review (§3.4) + transaction drawer (§3.6) + `GET
  /transactions/{id}` + `GET /transactions?…` + `POST /review/duplicates/{id}` + the
  category-confirm wiring.
- **PR 3:** Accounts (§3.5) + Settings (§3.7) + Electron `safeStorage` key handling + `GET
  /accounts`.

## Review

### PR 1

**Completed:** `GET /batches`, the frontend shell + Import + History, Vitest+RTL, a `frontend`
CI job. Branch `feature/frontend-screens` off `main`.

**Deviations:** dropped `<input accept>` (it hid the "not a PDF" reject state the screen must
show; the JS pre-check is the sole gate). shadcn primitives hand-vendored, not CLI-generated.
`techstack.md` §15's CI description is now stale (says ruff + pytest only) — flagged for the
owner, not edited.

**Tests:** frontend `pnpm test:run` — 14 pass; `oxlint` + `tsc` clean; `pnpm build` produces
all three bundles. Backend `uv run pytest` — 223 pass, 97%. Live-in-Electron E2E not run;
runbook `docs/manual-verification-frontend-pr1.md`.

### PR 2 / PR 3 — _(later)_
