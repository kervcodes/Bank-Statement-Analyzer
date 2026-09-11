# Bank Statement Analyzer

A local-first desktop app that ingests PDF bank and credit card statements, extracts and validates the transactions, and produces a dashboard: cash flow, spending by category, recurring charges, merchant trends, and an optional AI-generated plain-English summary layered on top of numbers that are always computed deterministically, never by the AI.

Runs entirely on your own machine (Electron desktop app, Python backend, local SQLite database). No server to operate, no account required, no data leaves the machine except sanitized, PII-stripped facts sent to a hosted LLM you've configured for the explanation layer.

## Status

The monorepo skeleton runs end to end: Electron launches, spawns the FastAPI backend as a local
sidecar, and the renderer reads `GET /health` and displays the result. The canonical data model
(`Batch`, `Account`, `Statement`, `Transaction`) is built on SQLModel with Alembic migrations,
money stored as integer cents, and schema-level constraints (CHECK constraints, enforced foreign
keys) backed by a 90%+ test coverage requirement (see [Testing](#testing) below).

`POST /batches` accepts one or more PDF uploads, validates each independently (rejects non-PDF,
corrupted, password-protected, oversized, or too-many-page files with a specific reason), and
tracks every file's status (`IntakeFile`) from the moment it's submitted. A standalone extraction
service pulls page text out of an accepted PDF — native text via `pdfplumber` first, OCR via
`pdf2image`/`pytesseract` as a fallback when a page has no usable embedded text — converging on
one contract either way.

Every accepted file gets a `statement_job` row, and a background worker (a single polling thread,
started with the app) claims each job and runs it end to end: extract text → detect the issuing
bank, account type, and layout version from the content (never the filename) with a confidence
score → below threshold, mark the job `UNSUPPORTED` and produce no `Statement` → otherwise parse
with a versioned, bank-specific parser, normalize into the canonical schema (resolving a stable
masked `Account` identity), and run three-level financial validation (structural,
transaction-level, and `opening + credits − debits == closing` reconciliation to the cent). The
first parser, `santander_checking_v1`, is built and regression-tested against real statements.
Transient failures retry twice; a parse error or a sub-cent misread fails the job without a
`Statement`. Once every job in a batch is terminal, a coordinator flips the batch to `COMPLETED`
— or `COMPLETED_WITH_WARNINGS` if any file was excluded at intake, failed processing, or
produced a statement that doesn't reconcile. `GET /batches/{id}` reports batch counters, per-job
status, and the produced statements with their validation result.

When a batch finishes, its new statements are checked for duplicates — statement-level (the
same PDF uploaded twice, auto-collapsed) then transaction-level for partial overlaps (a "last
90 days" statement overlapping monthly ones). Nothing is ever deleted: a duplicate row keeps
its place and is excluded from the ledger, and anything ambiguous is flagged for Review
(`GET /review/duplicates`) rather than collapsed.

`GET /analytics?start=&end=` computes the dashboard numbers deterministically over that
deduplicated, validated ledger: monthly cash flow (credits / debits / net), spending by
category, top merchants, recurring-charge detection (merchant + regular cadence + a stable but
not necessarily identical amount, so a subscription with price drift is still caught),
month-over-month trends, and a coverage summary (statements included vs. excluded and why, the
ledger's real date span) shown alongside every total. No LLM, no bank-specific branching, money
in integer cents, ratios as fixed-precision strings.

Each transaction is then given a normalized merchant ("UBER *TRIP 8AF3" and "UBER TECHNOLOGIES"
both become "Uber") and a category, resolved through a fixed, non-destructive hierarchy: a
per-transaction user override, then a saved merchant rule, then the deterministic prediction
(a built-in merchant/keyword map), then — only for merchants the rules can't place — one LLM
classification. A prediction is used only if it clears a 0.75 confidence gate; otherwise the
transaction goes to the Review queue rather than being labelled on a weak guess. The automated
guess is stored separately and never discarded, so removing a rule restores it with no bulk
rewrite. Every category carries an income / expense / transfer type, so a transfer between your
own accounts never counts as spending. `PUT /transactions/{id}/category` records a single
correction; `PUT /category-rules` makes it merchant-wide.

Anything sent to an LLM — the merchant classification above, and the optional plain-English
dashboard summary at `GET /analytics/explanation` — goes through one Privacy Gateway that is
the only place an outbound payload is built. It is an allowlist, not a scrub: exactly four
fields (`merchant`, `description`, `amount`, `direction`) leave the machine, built from
primitives so a raw transaction object can never be serialized by accident, with the
description locally sanitized (account/card/routing numbers, SSNs, emails, phone numbers,
transfer-recipient names) and a fail-closed check that routes a transaction to Review rather
than send anything it can't vouch for. The provider is configurable (OpenAI primary, Anthropic
fallback on provider failure only); with no API key the app is byte-identical to its
deterministic self.

The Electron/React frontend (`build-plan.md` #9, landing in three parts) is underway. The first
slice is live: an app shell (sidebar nav, hash routing, TanStack Query, dark mode off the OS
theme), an **Import** screen (drag-drop, per-file client pre-check, the backend's per-file
accept/reject reasons, a non-blocking progress pill), and a **History** screen (`GET /batches`,
paginated, expand a batch to see its statements and their validation status). The second slice
adds **Dashboard** (a date-range-scoped coverage bar, stat cards, a cash-flow chart and a
spending-by-category donut — each with a "show as table" fallback, recurring charges, top
merchants, and an optional AI summary panel) and **Review** (one inbox for possible duplicates,
low-confidence categorizations, and failed/unsupported statements), plus a shared transaction
drawer (`?txn=<id>`, linkable) and a filtered transaction list sheet used as the drill-through
surface from every clickable number. Accounts and Settings follow in part 3. Progress is
logged in [`docs/activity.md`](./docs/activity.md), and written up for humans as a build log at
[kervintznoel.com/posts](https://kervintznoel.com/posts/build-log-1-a-window-that-says-ok).

## What it does (v1)

- Accepts PDF statements from multiple banks and credit cards (Chase, Citizens, Capital One, Santander, Citi, Best Buy, Home Depot, and one more issuer to confirm).
- Processes statements asynchronously in the background so large batches (years of history across several institutions) don't freeze the UI.
- Extracts transactions from native PDF text, falling back to OCR only when needed.
- Detects the source bank/format and parses with a versioned, bank-specific parser, normalizing everything into one shared transaction schema.
- Validates every statement's numbers against its own reported balances before trusting them.
- Deduplicates overlapping statements and transactions conservatively (never silently deletes a real one).
- Computes cash flow, spending, recurring charges, and trends with deterministic code, then optionally asks a hosted LLM (Claude or OpenAI, your choice) to explain the results in plain English, always behind a Privacy Gateway that strips sensitive data first.
- Deletes raw PDFs after processing by default; normalized data persists and stays traceable back to its source statement and page even after the original is gone.

Full behavioral spec: [`requirements.md`](./requirements.md).

## How it works

```
Electron App (installed locally)
├── React UI (Dashboard, Import, History, Review, Accounts, Settings)
│        │  HTTP, localhost only
│        ▼
└── FastAPI backend (spawned as a local sidecar process)
         ├── Intake, validation, temp file storage
         ├── Background job queue + worker pool (SQLite-backed, no external broker)
         ├── Extraction (native text or OCR) → bank detection → versioned parser
         ├── Canonical schema → financial validation → deduplication
         ├── Deterministic analytics + rule-based categorization
         ├── Privacy Gateway (sanitizer) → hosted LLM (Claude or OpenAI)
         └── Local SQLite database
```

The full architecture reasoning (why async processing, why a canonical schema, why the LLM never touches raw numbers) came out of a design conversation worked through decision by decision before anything was built. Its conclusions live in [`techstack.md`](./techstack.md); the source PDF is kept locally and excluded from the repo by the `*.pdf` rule in `.gitignore`.

## Docs in this repo

| File | What's in it |
|---|---|
| [`techstack.md`](./techstack.md) | The concrete stack and every technology decision, with the reasoning behind each one. |
| [`design-notes.md`](./design-notes.md) | Screen-by-screen UI/UX spec: navigation, wireframes, visual style. |
| [`requirements.md`](./requirements.md) | The testable requirement list (REQ-IDs), non-functional requirements, and the v1 definition of done. |
| [`build-plan.md`](./build-plan.md) | The first 10 prompts for building this with Claude Code, in dependency order. |
| [`CLAUDE.md`](./CLAUDE.md) | Coding conventions Claude Code follows in this repo: planning workflow, Python/uv setup, testing, git branching. |
| [`docs/activity.md`](./docs/activity.md) | Running log of what was actually built, when, and what broke. |
| [Build log](https://kervintznoel.com/posts/build-log-1-a-window-that-says-ok) | The public write-up of each milestone — the same story told for people rather than tooling. Hosted on my site, not in this repo. |

## Getting started

Prerequisites: Node 20+ with `pnpm`, and Python 3.12+ with [`uv`](https://docs.astral.sh/uv/).

```bash
# From apps/desktop — starts Vite, Electron, and the backend together
pnpm install
pnpm dev
```

Electron's main process spawns the backend automatically in dev mode. To run either half on its
own while iterating:

```bash
# Backend (from apps/backend)
uv sync
uv run uvicorn app.main:app --port 8420 --reload

# Frontend (from apps/desktop, separate terminal)
pnpm install
pnpm dev
```

To continue building, run the prompts in [`build-plan.md`](./build-plan.md) in order, starting
from #9 — they're sequenced so each one builds on a working, tested version of the last.

## Testing

Backend tests require **90% coverage** (`apps/backend/pyproject.toml`,
`[tool.coverage.report] fail_under = 90`) — `uv run pytest` fails on its own if coverage drops
below that, so the number lives in one place.

```bash
cd apps/backend
uv run pytest       # runs with coverage automatically (see addopts)
uv run ruff check .
uv run ruff format --check .
```

A local pre-push hook runs the same suite and blocks the push if it fails. It's opt-in per
clone (git doesn't auto-run hooks outside `.git/hooks/`):

```bash
git config core.hooksPath .githooks
```

CI (`.github/workflows/ci.yml`) runs the same checks on every PR against `main`. `main` is
branch-protected to require the `backend` check before merging (no force-pushes, no branch
deletion; the repo admin can still bypass in an emergency — `enforce_admins` is off since
this is a solo project).

## Project structure

```
bank-statements-analyzer/
├── apps/
│   ├── desktop/       # Electron + React frontend
│   └── backend/       # Python FastAPI backend (uv-managed)
├── docs/
│   ├── activity.md    # Running log of work done, per CLAUDE.md
├── tasks/
│   └── todo.md        # Current plan, per CLAUDE.md's planning workflow
├── techstack.md
├── design-notes.md
├── requirements.md
├── build-plan.md
└── CLAUDE.md
```

Full rationale for this layout: `techstack.md` section 17.

## Tech stack (short version)

Electron + Vite + React + TypeScript + Tailwind on the frontend, Python + FastAPI + SQLModel + SQLite on the backend, pdfplumber/pytesseract for extraction, a SQLite-backed job queue for background processing (no Redis or Celery), and Claude/OpenAI behind a Privacy Gateway for the optional AI explanation layer. Full reasoning for every choice: [`techstack.md`](./techstack.md).

## Contributing / conventions

Solo project for now. Coding conventions, the plan-then-approve workflow, testing and linting expectations, and git branching rules are all defined in [`CLAUDE.md`](./CLAUDE.md), read that before making changes.

## License

Not yet decided. There's a plan to eventually charge a one-time fee for this app (see `techstack.md` section 19), so this is not currently open source.
