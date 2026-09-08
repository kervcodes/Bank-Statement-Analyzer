# Todo: Build-plan #9 — PR 2 (Dashboard + Review + transaction drawer)

Branch `feature/dashboard-review` off `main` (PR #15 merged). Source: `build-plan.md` §9,
`design-notes.md` §3.1 / §3.4 / §3.6, §4–§6.

## Scope (strict — from the owner)

**In:** Dashboard, Review, transaction drawer, `GET /transactions/{id}`, filtered/paginated
`GET /transactions`, duplicate review actions.
**Out (PR 3):** Accounts, Settings, Electron `safeStorage`, `GET /accounts`. Do not pull any of
these forward.

## Locked decisions carried from the #9 plan

- Dashboard default range = **last 12 months**; a date-range control is present.
- Charts = **Recharts**; every financial value must also be reachable as a number / table, not
  only in a chart (run the `dataviz` skill before writing chart code).
- Duplicate actions: `keep_both` → `UNIQUE`, `confirm` → `DUPLICATE`. No undo UI; both
  re-runnable; **never delete the row**; a confirmed duplicate stays queryable but is excluded
  from analytics. **No migration** — the existing `dedup_status` / `duplicate_of_id` columns
  are enough.
- Pagination on every list endpoint. State boundaries: TanStack Query = server; local React
  state = UI-only; router search params = navigation + filter state. No Redux/Zustand.
- Foundation stays minimal.

## Backend

### B1. `GET /transactions/{id}` — the drawer's data (`app/api/transactions.py`)
- Join Transaction → Statement → Account. Response: `id`, `transaction_date`, `posted_date`,
  `amount_cents`, `direction`, `category`, `category_source`, `predicted_category`,
  `user_category`, `merchant_normalized`, `description_normalized`, `description_raw`,
  `dedup_status`, and a **`source`** block that is always present (`statement_id`, `bank`,
  `account_type`, `account_identifier_masked`, `statement_period` (start/end), `source_page`,
  `parser_version`) — REQ-RPT-003 traceability. 404 on unknown id.
- Tests: full shape for a real txn; 404.

### B2. `GET /transactions` — filtered, paginated list (`app/api/transactions.py`)
- Query: `category`, `merchant` (exact match on `merchant_normalized`), `account_id`,
  `batch_id`, `date_from`, `date_to` (inclusive, on `transaction_date`), `page` (≥1),
  `page_size` (1–100, default 50), `sort` (`date_desc` default / `date_asc` / `amount_desc` /
  `amount_asc`), and `include_duplicates` (default `false`).
- Default view = the **deduplicated, validated ledger** (same rule as `app/services/ledger.py`
  — not `DUPLICATE`, statement not `DUPLICATE`/`FAILED`), so a Dashboard drill-through shows
  exactly the rows behind the number. `include_duplicates=true` widens it to every row
  (Review's "show me the confirmed duplicates" case).
- Response `{items, page, page_size, total}`. Each item: `id`, `transaction_date`,
  `merchant` (`merchant_normalized or description_normalized`), `description_normalized`,
  `amount_cents`, `direction`, `category`, `category_source`, `bank`,
  `account_identifier_masked`, `dedup_status`.
- Reuse the ledger filter helper from `app/services/ledger.py` where practical rather than
  re-deriving it.
- Tests: each filter narrows correctly; sort order; pagination; `include_duplicates`; empty →
  `{items: [], total: 0}`.

### B3. `POST /review/duplicates/{transaction_id}` — the duplicate action (`app/api/review.py`)
- Body `{action: "keep_both" | "confirm"}`.
- Preconditions: the txn is currently `POSSIBLE_DUPLICATE`, **or** already in the action's
  target state (so the call is safe to re-run). Otherwise 409.
  - `keep_both` → `dedup_status = "UNIQUE"`, `duplicate_of_id = None`.
  - `confirm` → `dedup_status = "DUPLICATE"` (keeps `duplicate_of_id`); 409 if there is no
    `duplicate_of_id` to point at.
- No re-run of dedup or validation; analytics reflects the change on its next read.
- Returns the txn's new `dedup_status`.
- Tests: `keep_both` and `confirm` from `POSSIBLE_DUPLICATE`; re-running each is a no-op 200;
  `confirm` with no match → 409; a `DUPLICATE` txn excluded from `GET /transactions` default
  but present with `include_duplicates=true`; analytics total drops after `confirm`.

## Frontend (`apps/desktop`)

### F0. Primitives
- Add `@radix-ui/react-dialog` (focus trap + Esc, for the drawer/sheet — design-notes
  §accessibility). Hand-vendor a minimal `Sheet` (right-side panel + overlay) and a `Select`
  (category picker) on top of it, or a tiny native `<select>` if that's enough.
- Extend `lib/api.ts` with the three new calls + query keys; `lib/format.ts` with
  `formatCents` (already implied) and a `categorySourceLabel`.

### F1. Transaction drawer (`components/TransactionDrawer.tsx`, design-notes §3.6)
- Opened via a `?txn=<id>` search param (linkable). `GET /transactions/{id}`.
- Merchant, `-$X · date`, category with `[edit]` → a `Select` of the fixed taxonomy →
  `PUT /transactions/{id}/category` (per-transaction override), account line, the **Source**
  block (always shown), raw text.
- Invalidates `['transactions']` + `['analytics']` on a category change.

### F2. Transaction list sheet (`components/TransactionListSheet.tsx`)
- A wider sheet holding a compact table, backed by `GET /transactions` with filters from its
  own props (category / merchant / date window / batch). Page controls. A row opens the F1
  drawer. This is the "click a number → see the rows" surface (§principle 4).

### F3. Dashboard (`routes/DashboardRoute.tsx`, design-notes §3.1)
- Date-range control top-right (`Last 12 months` default / `This year` / `All time` / custom)
  → writes `start` / `end` to the URL; the charts and lists below read them.
- **Coverage bar**, pinned above everything: from `analytics.coverage`. Green pill when
  `statements_excluded === 0`; amber + an expandable excluded list otherwise; the bar links to
  `/history`.
- **Stat cards**: net cash flow, spending, top category — `tabular` figures.
  - **Spending card = the latest _full calendar month_** (the current partial month is
    excluded), with a percentage delta vs the **previous full calendar month**. Label makes
    that explicit, e.g. "August spending — $4,210  ↓ 3% vs July". Not the selected-range total,
    not an average.
  - If there are **fewer than two complete months** of data: show the latest full month with
    **no delta** and a neutral "Not enough prior data" note.
  - Clicking the Spending card drills F2 to **exactly that month's spending transactions**
    (the same `date_from`/`date_to` + spending-category filter that produced the number).
  - The other cards use the `trends` delta where available. Clicking one opens F2 filtered.
- **Charts** (Recharts, after the `dataviz` skill): a 12-month cash-flow chart
  (credits / debits / net, transfers shown distinctly) and a spending-by-category donut. Each
  has a **"show as table"** toggle rendering the same numbers as an accessible `<table>`.
  Clicking a category segment opens F2 filtered to that category.
- **Recurring charges** + **Top merchants** lists (already numeric/tabular; a merchant row
  opens F2).
- **AI summary panel** — `GET /analytics/explanation`, its own labelled card with the provider
  tag + a Refresh button (refetch). `provider === null` → "Add an API key in Settings to get a
  plain-English summary" empty state. Never blended with the figures (§principle 2).
- Empty ledger → a "nothing processed yet, import statements" state, not zeroed charts
  (§empty states).

### F4. Review (`routes/ReviewRoute.tsx`, design-notes §3.4)
- One page, sections in order, each with a count; the sidebar badge = the sum.
- **Possible duplicates** — `GET /review/duplicates`; each pair shows both rows; `[Keep both]`
  → `POST /review/duplicates/{id}` `{keep_both}`, `[This is a duplicate]` → `{confirm}`.
  Invalidate `['review']` + `['analytics']`.
- **Needs a category** — `GET /review/categorizations` (grouped by merchant). **The category
  action must make its scope explicit before writing** (owner correction):
  - A **merchant-wide** action is presented as explicit intent — the button literally reads
    "Always categorize <merchant> as <category>" → `PUT /category-rules` (affects every
    non-overridden transaction of that merchant, now and future).
  - A generic "Categorize" that silently becomes a rule is **not allowed**. If the user wants
    to fix only some rows, they expand the group and edit per transaction →
    `PUT /transactions/{id}/category` (that row only).
  - Precedence invariant unchanged: `USER OVERRIDE → MERCHANT RULE → prediction ≥ 0.75 →
    Review`.
  - Invalidate `['review']` + `['analytics']` + `['transactions']`.
- **Failed / unsupported statements** — a read-only summary derived from `GET /batches`
  (batches with `processing_failed > 0`), linking to History for the retry/re-upload. (A
  first-class `GET /review/statements` endpoint + retry action is a later PR — not in scope
  here.)

### F5. Tests (Vitest + RTL + MSW)
- `lib`: the date-range → `start`/`end` helper.
- `TransactionDrawer`: renders the source block, category edit posts and closes.
- `TransactionListSheet`: filters passed through to the request; row opens the drawer.
- `DashboardRoute`: coverage bar green vs amber; AI panel empty state vs text; a chart's
  "show as table" toggle; empty-ledger state.
- `ReviewRoute`: `keep_both` / `confirm` hit the right endpoint+body and refetch; a category
  confirm writes a merchant rule.

### F6. Checks & docs
- `pnpm lint` / `pnpm typecheck` / `pnpm test:run` / `pnpm build`; backend `uv run pytest` /
  `ruff`.
- `docs/activity.md`; `README.md`; `docs/manual-verification-frontend-pr2.md`.
- `tasks/todo.md` Review.

## Suggested build order

B1 → B2 → B3 (backend, each with tests) → F0 → F1 + F2 (drawer + list, the shared drill-through
surface) → F3 (Dashboard) → F4 (Review) → F5/F6.

## Owner corrections recorded (2026-09-08)

- **Spending stat card** = latest *full calendar month* vs previous full calendar month;
  exclude the current partial month; `<2` full months → latest month, no delta, "Not enough
  prior data"; explicit label; click drills to that month's spending transactions. Not an
  average, not the range total. (F3.)
- **Review category action** never silently becomes a merchant rule — the merchant-wide button
  states the scope explicitly; per-transaction fixes go through `PUT /transactions/{id}/category`.
  (F4.)

## Review

_(filled in when PR 2 is done)_
