# Design Notes: Bank Statement Analyzer

UI/UX design notes for the Electron desktop app. This sits one layer below `techstack.md` (which fixed the stack: Electron, Vite + React + TypeScript, Tailwind + shadcn/ui, TanStack Query) and `brainstorming.pdf` (which fixed the architecture and the trust/privacy invariants). This doc is about what the user actually sees and clicks. Read it alongside those two before building any screen.

## 1. Design principles

These come straight from the architecture invariants in the brainstorm, translated into UI rules. Every screen below should be checked against these:

1. **Coverage is never hidden.** If any statement failed or was excluded, the user sees that before they see any dollar figure, not buried in a log or a settings page.
2. **The AI explains, it never replaces a number.** Any LLM-generated text is visually distinct (its own labeled panel, never inline with a computed figure) and always sits next to, never instead of, the number it's describing.
3. **Uncertainty is shown, not hidden.** Low-confidence categorization, possible duplicates, and unsupported statements are surfaced explicitly with a clear affordance to review, not silently auto-resolved.
4. **Every number is traceable.** Clicking any transaction, category total, or chart segment gets you back to the source statement and page. Don't build a dashboard you can't drill into.
5. **Failure is local, not global.** One bad statement shows a badge on that one statement. It never blocks or degrades the rest of the dashboard.

## 2. Information architecture

Left sidebar navigation (standard desktop app pattern, matches the Electron/React ecosystem you're already choosing from, e.g. Slack, Notion, Obsidian):

```
┌─────────────────┐
│ Bank Statement   │
│ Analyzer         │
├─────────────────┤
│ ● Dashboard      │
│ ● Import         │
│ ● History        │
│ ● Review    (3)  │  ← badge count, only shown when > 0
│ ● Accounts       │
├─────────────────┤
│ ● Settings       │
└─────────────────┘
```

- **Dashboard**: the home screen. Aggregate view across the whole unified ledger (not just the last batch): cash flow, spending, recurring charges, merchants, trends. This is where most time gets spent.
- **Import**: start a new analysis by adding more PDFs. Always available, not a one-time onboarding flow, since the user will come back monthly/yearly to add statements.
- **History**: past import batches and their processing status. Answers "what did I upload and did it all work."
- **Review**: a single inbox for anything needing a human decision, possible duplicates, low-confidence categorizations, unsupported/failed statements. See section 4.4 for why this is one screen instead of three.
- **Accounts**: the resolved account list (Chase Checking ••1234, etc.), with the ability to fix a mis-grouped account.
- **Settings**: LLM provider + API key, data retention policy, category rules, (later) license activation.

## 3. Screens

### 3.1 Dashboard (home)

```
┌──────────────────────────────────────────────────────────────┐
│  Coverage: 117 of 120 statements · Jan 2025–Dec 2026    ⚠ 3   │  ← always pinned, clickable
├──────────────────────────────────────────────────────────────┤
│  Net cash flow          Monthly spending         Top category │
│  +$1,204  ↑ 8%          $4,210  ↓ 3%              Dining      │  ← stat cards, tabular nums
├──────────────────────────────────────────────────────────────┤
│  [ Cash flow chart, last 12 months ]      [ Spending by       │
│                                              category, donut ] │
├──────────────────────────────────────────────────────────────┤
│  Recurring charges              Top merchants                 │
│  Netflix      $22.99/mo         Amazon        $2,310          │
│  Electric     ~$150/mo          Uber          $1,802          │
├──────────────────────────────────────────────────────────────┤
│  ✦ AI summary (Claude)                              [Refresh] │  ← visually separate panel,
│  "Dining was the largest driver of your spending increase..." │     never blends with the
└──────────────────────────────────────────────────────────────┘     numbers above it
```

- The coverage bar is a `Badge` + inline summary, not a full banner, when everything is clean (green, "117/117 statements, fully processed"). It expands to amber with an explicit excluded-statements list the moment anything is missing or failed. Clicking it goes to History filtered to the problem statements.
- Every stat card and chart segment is clickable and opens a transaction drawer (section 3.6), never just decorative.
- The AI panel is collapsible, has a visible "Claude" or "OpenAI" provider tag (whichever is active), and a manual refresh button since the user may want a fresh take after correcting categories. If no LLM key is configured, this panel is replaced with a plain empty state ("Add an API key in Settings to get a plain-English summary"), the rest of the dashboard works identically either way.
- Date range filter lives top-right of this screen (last 12 months / this year / all time / custom), everything below reacts to it.

### 3.2 Import

```
┌──────────────────────────────────────────────────────────────┐
│                                                                │
│              Drop PDF statements here, or browse              │
│                                                                │
├──────────────────────────────────────────────────────────────┤
│  chase_jan.pdf              12.4 KB     ✓ ready               │
│  chase_feb.pdf              11.9 KB     ✓ ready               │
│  boa_march.pdf               8.1 KB     ✗ upload failed  [retry]│
│  random_screenshot.png       2.0 KB     ✗ not a PDF     [remove]│
├──────────────────────────────────────────────────────────────┤
│  4 files selected, 2 ready, 1 failed, 1 rejected               │
│                                     [ Start analysis (2) ]     │
└──────────────────────────────────────────────────────────────┘
```

- Per-file status appears immediately on drop, before "Start analysis" is even clickable, this is the upload-vs-validation distinction from the brainstorm made visible: a failed upload and a rejected (invalid) file look different and say why.
- "Start analysis" is never blocked by individual failures. The button label always shows the count of files that will actually be processed, matching the "don't throw away 9 good statements because 1 failed" invariant.
- Once started, this screen hands off to a progress view (can be a modal or can navigate to History) showing the batch counters live: queued / processing / completed / failed, sourced from the Batch Coordinator.

### 3.3 History

A table (TanStack Table pairs naturally with the TanStack Query stack already chosen) of past batches:

```
Batch            Date         Statements        Status
─────────────────────────────────────────────────────────────
Jan–Dec 2026     Sep 4        118 / 120         ⚠ Completed with warnings
2025 statements  Aug 20        60 / 60          ✓ Completed
```

- Expanding a row lists every statement in that batch with its individual status (`VALID`, `WARNING`, `FAILED`, `UNSUPPORTED`) and a retry action for retryable failures. This is the detail view for the coverage numbers shown elsewhere.
- Never a delete-only history, statements here map back to what's actually in the ledger, so this table is also how a user would spot "I never actually uploaded March."

### 3.4 Review (the attention inbox)

Three sources feed one list, grouped by type, instead of three separate screens: possible duplicates need a keep/merge decision, low-confidence categorizations need a category confirmed, unsupported/failed statements need a retry or acknowledgment. Putting them in one place means the sidebar badge count is one honest number for "things that need you," rather than the user having to remember to check three tabs.

```
┌──────────────────────────────────────────────────────────────┐
│  Possible duplicate (2)                                       │
│  08/14  Starbucks  $7.82   (Chase ••1234, statement A)         │
│  08/14  Starbucks  $7.82   (Chase ••1234, statement B)         │
│                              [ Keep both ]  [ This is a dup ] │
├──────────────────────────────────────────────────────────────┤
│  Needs a category (1)                                          │
│  XYZ SERVICES   $84.00      Suggested: Home Services (72%)    │
│                              [ Confirm ]  [ Pick different ]  │
├──────────────────────────────────────────────────────────────┤
│  Failed statement (1)                                          │
│  Bank of America — October 2024      Reason: password-protected│
│                              [ Re-upload ]                     │
└──────────────────────────────────────────────────────────────┘
```

- High-confidence duplicates never appear here, they're already auto-collapsed. Only genuinely ambiguous cases reach a human, matching the "false negative is safer than false positive" rule.
- A category confirmation here is what writes back to the merchant-mapping rule table, so the next occurrence of the same merchant never shows up in Review again.

### 3.5 Accounts

A simple list: `Chase Checking ••1234`, `Capital One Credit Card ••4444`, etc., each showing the date range and statement count backing it. Mainly exists so the user can catch a mis-grouped account (e.g. two provisional accounts that are actually the same one) and merge them, this maps directly to the "ask for confirmation" fallback path in the account-resolution design.

### 3.6 Transaction detail (drawer, not a page)

Opens as a right-side `Sheet` (shadcn/ui) over whatever screen triggered it, so the user never loses their place:

```
┌──────────────────────────────┐
│  Electric Company             │
│  -$142.19  ·  08/15/2026      │
│                                │
│  Category: Utilities  [edit]  │
│  Account: Chase Checking ••1234│
│                                │
│  Source                       │
│  Statement: Chase, August 2026│
│  Page 3 · Parser chase_checking_v2│
│                                │
│  Raw text                     │
│  "ELECTRIC CO ACH DEBIT..."   │
└────────────────────────────────┘
```

This is the traceability principle made concrete, the Source block should always be present, even for transactions from a statement whose raw PDF has since been deleted (that's exactly why `source_statement_id`, `source_page`, and `parser_version` persist independently of the raw file).

### 3.7 Settings

- **LLM provider**: radio choice between Claude and OpenAI, an API key field per provider (masked input, stored via Electron `safeStorage`, never shown again in plaintext once saved), and a "test connection" button.
- **Data retention**: toggle for "delete raw PDFs after processing" (on by default) vs "keep originals," plus a visible note on what "keep" means for disk usage and privacy.
- **Category rules**: a plain table of merchant → category overrides the user has confirmed, editable directly here, not just reactively through Review.
- **License** (placeholder for the future one-time-fee flow from `techstack.md` section 19, not built in v1): reserve the space now so adding it later doesn't require a Settings redesign.

## 4. Visual style

- **Typography**: Inter (the standard shadcn/ui pairing). Use `font-variant-numeric: tabular-nums` on every dollar amount and date column so figures actually align in tables and stat cards, a detail that's easy to skip and immediately looks unpolished if you do.
- **Color, kept restrained**: a neutral slate/gray base (shadcn/ui's default "slate" or "zinc" theme is a fine starting point), one accent color for primary actions and links, and a small, consistent semantic set used only for status, never decoratively:
  - Gray: queued / not started
  - Blue: processing
  - Green: completed / valid / high confidence
  - Amber: warning / needs review / possible duplicate
  - Red: failed / rejected
- **Don't rely on color alone** for credit/debit or status, financial UIs get scanned quickly and some users are colorblind. Pair every status color with an icon or label (a checkmark, a triangle, the word "Failed"), not color by itself.
- **Density**: this is a data-heavy tool (transaction tables can run into the thousands of rows), lean toward a compact table density (shadcn/ui's `Table` with tight padding) over a spacious consumer-app feel. Reserve generous whitespace for the Dashboard's summary cards, where the eye should land first.
- **Dark mode**: support it from the start via Tailwind's `dark:` variants driven off the OS theme (Electron can read `nativeTheme.shouldUseDarkColors`), this is a desktop app running next to code editors and terminals, users will expect it.

## 5. Interaction patterns

- **Background job progress**: a persistent, non-blocking indicator (a small progress pill in the sidebar near "Import" or "History") for any batch still processing, plus a toast on completion ("Analysis complete: 118/120 statements processed"). Never a blocking spinner over the whole app, the async design exists specifically so the UI stays usable during processing.
- **Empty states**: first launch (no batches yet) should land on Import with a clear "drop your first statements here" state, not an empty Dashboard with zeroed-out charts, that reads as broken rather than new.
- **Error states**: distinguish "we couldn't read this file" (actionable, retry/remove) from "something in the app broke" (a real bug) visually and in copy, users should never see a raw stack trace.

## 6. Accessibility

- Keyboard navigation matters more than usual for a desktop app (users expect Tab/Enter/Esc to work everywhere, not just mouse interaction).
- Maintain WCAG AA contrast for the status colors above, especially amber-on-white, which commonly fails contrast checks at default Tailwind shades, verify it rather than assuming.
- All charts need a non-visual fallback (a text summary or an accessible data table toggle), don't make the recurring-charges or spending-breakdown data available only as a rendered chart.

## 7. Open design questions

- Should Review-queue actions (confirm category, resolve duplicate) be reversible/undoable, or final? Worth deciding before building the write path.
- Does the Dashboard default to "all time" or "last 12 months" on first load? Affects perceived performance once the ledger has years of data.
- Exact icon set: shadcn/ui commonly pairs with `lucide-react`, reasonable default, confirm before wiring up components.
