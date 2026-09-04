# Bank Statement Analyzer

Local-first desktop app that extracts, normalizes, and analyzes bank statement PDFs. See
`techstack.md`, `requirements.md`, and `design-notes.md` for the full spec and architecture.

## Getting started (dev)

Prerequisites: [uv](https://docs.astral.sh/uv/) (Python), [pnpm](https://pnpm.io/) (Node).

```
cd apps/desktop
pnpm install
pnpm dev
```

`pnpm dev` starts Vite, then Electron's main process spawns the FastAPI backend
(`uv run uvicorn app.main:app --port 8420 --reload`) automatically. The renderer calls
`GET /health` on load and displays the result.

To run the backend on its own, see `apps/backend/README.md`.
