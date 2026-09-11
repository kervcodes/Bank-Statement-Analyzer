# Manual verification — build-plan #9, PR 2 (Dashboard + Review + transaction drawer)

**Scope:** Dashboard, Review, the transaction drawer, the transaction list sheet drill-through,
`GET /transactions/{id}`, filtered/paginated `GET /transactions`, duplicate review actions.
Accounts / Settings / `safeStorage` / `GET /accounts` are PR 3 — not in this PR.

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

- [ ] All four pass.
- [ ] Backend: from `apps/backend`, `uv run pytest` green, `ruff check .` / `ruff format --check .`
      clean.

---

## 2. The app, end to end

```powershell
pnpm dev
```

Import at least a few real statements first (or use an existing dev DB) so the Dashboard has
real numbers to show, not an empty ledger.

### Dashboard

- [ ] Coverage bar is pinned above everything. Green + "N of N statements" when nothing is
      excluded. With an excluded/failed statement present: amber, "N excluded" is clickable and
      expands a list (bank, period, reason) with a "View in History" link.
- [ ] Date-range control top-right (`Last 12 months` / `This year` / `All time`) changes the
      URL's `range`/`start`/`end` and every card/chart below reacts.
- [ ] Net cash flow, Monthly spending, and Top category stat cards show `tabular` figures.
- [ ] **Spending card** specifically: labelled with the latest *full* calendar month (the
      current partial month is excluded), delta vs the previous full month. With fewer than two
      full months of data: no delta, "Not enough prior data" instead.
- [ ] Clicking a stat card, a donut segment, a recurring charge, or a top merchant opens the
      transaction list sheet filtered to exactly that slice (same date range + category/merchant
      as the number shown).
- [ ] Cash-flow chart and spending donut each have a "Show as table" toggle rendering the same
      numbers as a plain, accessible table.
- [ ] AI summary panel: its own visually distinct card, never blended with the numeric cards.
      Shows the empty state ("Add an API key in Settings…") when no LLM key is configured, or the
      provider tag + text + a working Refresh button when one is.
- [ ] Empty ledger (no batches processed yet): "Nothing processed yet" + an Import button, not a
      zeroed-out dashboard.

### Transaction drawer + list sheet

- [ ] Clicking any row in a list sheet opens the drawer (`?txn=<id>` in the hash) stacked on top,
      showing merchant, signed amount + date, category (with an inline edit via `[pencil icon]`),
      account, and an always-present **Source** block (statement, period, page, parser) plus raw
      text.
- [ ] Editing the category writes immediately (`PUT /transactions/{id}/category`) and the
      Dashboard's numbers (spending total, category donut) update on next view.
- [ ] Reload the app with `?txn=<id>` still in the address — the drawer reopens to that same
      transaction.

### Review

- [ ] Three sections, each with a count in its heading: **Possible duplicates**, **Needs a
      category**, **Failed / unsupported statements**. Sidebar "Review" badge = the sum of all
      three, and disappears at zero.
- [ ] Possible duplicates: both transactions of a pair shown side by side. `[Keep both]` →
      `UNIQUE`; `[This is a duplicate]` → `DUPLICATE`. Either action removes the pair from the
      list and drops the sidebar count.
- [ ] Needs a category: grouped by merchant. Picking a category and confirming shows a button
      that **literally names the merchant and the category** ("Always categorize X as Y") —
      never a generic "Categorize" that silently becomes a merchant-wide rule. Expanding a group
      lists its individual transactions; clicking one opens the drawer to fix that row alone via
      `PUT /transactions/{id}/category`, without touching the merchant rule.
- [ ] Failed / unsupported statements: read-only, links to History.

---

## 3. Sign-off

- [ ] `pnpm lint` / `pnpm typecheck` / `pnpm test:run` / `pnpm build` all green; backend suite
      green.
- [ ] Every chart has a non-visual (table) fallback; no chart is the only way to see a number.
- [ ] The AI panel never sits inline with a computed figure.
- [ ] A merchant-wide category rule is never written without the button explicitly naming both
      the merchant and the target category.
