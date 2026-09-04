# Bank Statement Analyzer

A local-first desktop app that ingests PDF bank and credit card statements, extracts and validates the transactions, and produces a dashboard: cash flow, spending by category, recurring charges, merchant trends, and an optional AI-generated plain-English summary layered on top of numbers that are always computed deterministically, never by the AI.

Runs entirely on your own machine (Electron desktop app, Python backend, local SQLite database). No server to operate, no account required, no data leaves the machine except sanitized, PII-stripped facts sent to a hosted LLM you've configured for the explanation layer.

## Status

Pre-code, spec-complete. This repo currently holds the full design: architecture, tech stack, screens, and requirements, but no application code yet. If you're picking this up to start building, go to [Getting started](#getting-started) below.

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

The full architecture reasoning (why async processing, why a canonical schema, why the LLM never touches raw numbers) is in [`brainstorming.pdf`](./brainstorming.pdf), a design conversation worked through decision by decision before anything was built.

## Docs in this repo

| File | What's in it |
|---|---|
| [`brainstorming.pdf`](./brainstorming.pdf) | The original architecture design conversation. Read this for the *why* behind every boundary in the system. |
| [`techstack.md`](./techstack.md) | The concrete stack and every technology decision, with the reasoning behind each one. |
| [`design-notes.md`](./design-notes.md) | Screen-by-screen UI/UX spec: navigation, wireframes, visual style. |
| [`requirements.md`](./requirements.md) | The testable requirement list (REQ-IDs), non-functional requirements, and the v1 definition of done. |
| [`build-plan.md`](./build-plan.md) | The first 10 prompts for building this with Claude Code, in dependency order. |
| [`.claude.md`](./.claude.md) | Coding conventions Claude Code follows in this repo: planning workflow, Python/uv setup, testing, git branching. |

## Getting started

This project isn't scaffolded yet. To start:

1. Open this folder in Claude Code.
2. Run prompt 1 from [`build-plan.md`](./build-plan.md) to scaffold `apps/desktop` and `apps/backend`.
3. Continue through the remaining prompts in order, they're sequenced so each one builds on a working, tested version of the last.

Once scaffolded, the expected local dev workflow (per `techstack.md`) is:

```bash
# Backend (from apps/backend)
uv sync
uv run uvicorn app.main:app --port 8420 --reload

# Frontend (from apps/desktop, separate terminal)
pnpm install
pnpm dev
```

Electron's main process spawns the backend automatically in dev mode once prompt 1 is done, these commands are for running each half independently while iterating.

## Project structure

```
bank-statements-analyzer/
├── apps/
│   ├── desktop/       # Electron + React frontend
│   └── backend/       # Python FastAPI backend (uv-managed)
├── docs/
│   └── activity.md    # Running log of work done, per .claude.md
├── tasks/
│   └── todo.md        # Current plan, per .claude.md's planning workflow
├── techstack.md
├── design-notes.md
├── requirements.md
├── build-plan.md
├── brainstorming.pdf
└── .claude.md
```

Full rationale for this layout: `techstack.md` section 17.

## Tech stack (short version)

Electron + Vite + React + TypeScript + Tailwind on the frontend, Python + FastAPI + SQLModel + SQLite on the backend, pdfplumber/pytesseract for extraction, a SQLite-backed job queue for background processing (no Redis or Celery), and Claude/OpenAI behind a Privacy Gateway for the optional AI explanation layer. Full reasoning for every choice: [`techstack.md`](./techstack.md).

## Contributing / conventions

Solo project for now. Coding conventions, the plan-then-approve workflow, testing and linting expectations, and git branching rules are all defined in [`.claude.md`](./.claude.md), read that before making changes.

## License

Not yet decided. There's a plan to eventually charge a one-time fee for this app (see `techstack.md` section 19), so this is not currently open source.
