# Todo: Scaffolding — apps/desktop + apps/backend skeleton

Source: `build-plan.md` §1, `techstack.md` §17 (repo structure), §3 (frontend stack), §4 (backend stack), §13 (process lifecycle / health check).

Goal for this task only: the monorepo skeleton exists and one thing works end to end —
Electron starts the FastAPI backend in dev mode, the renderer calls `GET /health` on load,
and shows the result on screen. No canonical schema, no DB, no parsers, no packaging yet —
those are later build-plan prompts.

Branch: `feature/monorepo-skeleton`

## Backend — `apps/backend`

- [x] `uv init` a Python 3.12+ project at `apps/backend` (`pyproject.toml`, `src/app/` layout per techstack §17 and root `.claude.md` §9)
- [x] `uv add fastapi "uvicorn[standard]"`
- [x] `src/app/main.py`: FastAPI instance with one route, `GET /health` → `{"status": "ok"}`
- [x] Confirm `uv run uvicorn app.main:app --port 8420 --reload` serves it (per techstack §4)
- [x] `apps/backend/README.md` — one paragraph, how to run it standalone
- [x] (found during verification) Add `CORSMiddleware` (`allow_origins=["*"]`) — without it the browser fetch from the renderer's origin is silently blocked even though curl succeeds

## Frontend — `apps/desktop`

- [x] Scaffold Vite + React 19 + TypeScript at `apps/desktop` (`pnpm create vite . --template react-ts`)
- [x] Add Tailwind CSS 4 (per techstack §3) — base config only, no shadcn/ui components yet, out of scope for this skeleton
- [x] Add `electron`, `electron-builder`, `vite-plugin-electron`/`vite-plugin-electron-renderer` as dev dependencies
- [x] `electron/main.ts`:
  - spawns the backend in dev mode (`uv run uvicorn app.main:app --port 8420 --reload`, `cwd: apps/backend`) as a child process
  - loads the Vite dev server URL in the BrowserWindow
  - kills the backend child process on `will-quit`
  - `contextIsolation: true`, `nodeIntegration: false` (per techstack §3 security note), even though this skeleton doesn't need IPC yet
- [x] `electron/preload.ts`: empty/minimal preload file, wired but no bridge methods yet (nothing to expose at this stage)
- [x] `src/App.tsx`: on mount, `fetch('http://127.0.0.1:8420/health')`, render the raw result (status text is enough — no styling polish)
- [x] `package.json` scripts: `dev` (starts Vite + Electron together via `vite-plugin-electron/simple`), per techstack's dev workflow
- [x] (found during verification) Set `package.json` `"main": "dist-electron/main.js"` — without it Electron can't find the entry point and shows an "Error launching app" dialog
- [x] (found during verification) Use `stdio: 'pipe'` + forward stdout/stderr, and attach an `'error'` listener on the spawned backend process — `stdio: 'inherit'` threw synchronously in this environment, and an unhandled `'error'` event on a Node `ChildProcess` crashes the process

## Wiring / repo-level

- [x] Root-level scripts or docs for running both halves in dev — added root `README.md` (less duplication than the Vite template's `apps/desktop/README.md`)
- [x] Confirm `.gitignore` already covers `node_modules/`, `.venv/`, `dist/`, backend build output — added `dist-electron/` to `apps/desktop/.gitignore`, not covered by the Vite template default
- [x] Manual verification: `pnpm dev` launches Electron; backend confirmed serving `/health` with `200 {"status":"ok"}` and the correct CORS header for the renderer's origin, and the window opens with no crash dialog. **Confirmed on screen by the user on 2026-09-04** — the Electron window renders the health card with `{"status":"ok"}`. End-to-end skeleton verified.

## Out of scope for this task (confirmed against techstack.md / build-plan.md)

- SQLModel/Alembic, canonical schema (build-plan #2)
- Any real API routes beyond `/health`
- shadcn/ui, TanStack Query, Zustand, Recharts, React Hook Form/Zod — real dependencies for later screens, not needed for a health-check skeleton
- PyInstaller/electron-builder packaging (build-plan #10)
- CI workflows

## Review

**What was completed:** Monorepo skeleton at `apps/backend` (uv + FastAPI, `GET /health`) and
`apps/desktop` (Vite + React 19 + TS + Tailwind 4 + Electron via `vite-plugin-electron/simple`).
Electron's main process spawns the backend in dev mode and kills it on `will-quit`; the renderer
fetches `/health` on mount and renders the result. Root `README.md` added for the combined dev
workflow.

**Tests/checks run:**
- `uv run uvicorn app.main:app --port 8420 --reload` standalone → `curl /health` → `200 {"status":"ok"}`
- `pnpm dev` (full stack) → backend confirmed reachable on `127.0.0.1:8420` with the correct
  `access-control-allow-origin` header for the renderer's origin
- Electron window opens with title "desktop" and normal menu, no crash dialog

**Known issues:**
- ~~On-screen render not visually confirmed.~~ Resolved 2026-09-04: user confirmed the rendered
  window showing `{"status":"ok"}`. Screenshot published with the build-log post.
- `uv run uvicorn --reload` did not reliably kill/replace its old worker process on Windows during
  this session (had to fully kill the process tree once to pick up a code change). Not a skeleton
  defect, but worth knowing if `--reload` seems to silently ignore a change later.
- `stdio: 'inherit'` on the spawned backend threw when launched via a non-interactive shell in
  this environment; switched to `'pipe'` + manual forwarding. Should be fine when launched
  normally from a terminal, but flagging in case it recurs.

**Recommended next step:** build-plan.md #2 — canonical schema (SQLModel) + Alembic + local SQLite,
no API endpoints yet.
