# Bank Statement Analyzer

A local-first desktop app that ingests PDF bank and credit card statements, extracts and validates the transactions, and produces a dashboard: cash flow, spending by category, recurring charges, merchant trends, and an optional AI-generated plain-English summary layered on top of numbers that are always computed deterministically, never by the AI.

Runs entirely on your own machine (Electron desktop app, Python backend, local SQLite database). No server to operate, no account required, no data leaves the machine except sanitized, PII-stripped facts sent to a hosted LLM you've configured for the explanation layer.

## Status

The monorepo skeleton runs end to end: Electron launches, spawns the FastAPI backend as a local
sidecar, and the renderer reads `GET /health` and displays the result. The canonical data model
(`Batch`, `Account`, `Statement`, `Transaction`) is built on SQLModel with Alembic migrations,
money stored as integer cents, and schema-level constraints (CHECK constraints, enforced foreign
keys) backed by a 90%+ test coverage requirement (see [Testing](#testing) below). No parsers,
intake pipeline, or analytics yet.

Next up is intake and validation (`build-plan.md` #3). Progress is logged in
[`docs/activity.md`](./docs/activity.md), and written up for humans as a build log at
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
from #3 — they're sequenced so each one builds on a working, tested version of the last.

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

CI (`.github/workflows/ci.yml`) runs the same checks on every PR against `main`. Merging is
meant to require that check to pass — enforced via a GitHub branch protection rule on `main`,
configured separately from this repo's code.

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
