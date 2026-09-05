# Activity Log

## 2026-09-04 — Monorepo scaffolding (apps/desktop + apps/backend)

**Prompt:** "Set up the initial monorepo structure exactly as described in techstack.md section 17
... minimal skeleton: a FastAPI app with a single GET /health endpoint, and an Electron app whose
main process spawns the backend in dev mode and whose renderer calls /health on load and displays
the result." (build-plan.md #1)

**What was built:**
- `apps/backend`: `uv`-managed Python 3.12 project, FastAPI, single `GET /health` route.
- `apps/desktop`: Vite + React 19 + TypeScript, Tailwind CSS 4, Electron (via
  `vite-plugin-electron/simple`). Main process spawns the backend in dev mode and kills it on
  `will-quit`. Renderer fetches `/health` on mount.
- Root `README.md` with the combined dev workflow.

**Decisions:**
- Used `pnpm` (installed mid-task) per techstack.md's CI section, rather than plain npm.
- Added `CORSMiddleware` (`allow_origins=["*"]`) to the backend — necessary for the renderer
  (cross-origin from the sidecar on 127.0.0.1) to actually read the response; not explicitly
  called out in techstack.md but required for the architecture it describes to function. Judged
  acceptable given the local-only, single-user threat model (techstack.md §1, §16).
- Did not add `concurrently`/`cross-env` — `vite-plugin-electron/simple` already orchestrates
  Vite + Electron in one `pnpm dev`, so they were unused dead dependencies.

**Bugs fixed during verification (all on this task, before commit):**
- `package.json` had no `"main"` field → Electron couldn't find its entry point, showed an
  "Error launching app" dialog. Fixed: `"main": "dist-electron/main.js"`.
- Spawning the backend with `stdio: 'inherit'` threw synchronously in this environment (no
  console attached to the spawning process), crashing Electron's main process. Fixed: `stdio:
  'pipe'` with manual stdout/stderr forwarding, plus an `'error'` listener on the child process
  (an unhandled `'error'` event on a Node `ChildProcess` otherwise crashes the process).

**Verified:** backend `/health` returns `200 {"status":"ok"}` standalone and under `pnpm dev`,
with the correct CORS header for the renderer's origin; Electron window opens cleanly (title
"desktop", no crash dialog). The on-screen render was confirmed by the user on 2026-09-04 — the
window displays the health card with `{"status":"ok"}` (screenshot published with the build log post).
Build-plan #1 is complete: the skeleton works end to end.

**Next step:** build-plan.md #2 — canonical schema (SQLModel) + Alembic + local SQLite.

---

## 2026-09-04 — Docs cleanup + first build-log post

**What changed:**
- `tasks/todo.md`, `docs/activity.md`: closed out the one open verification item from scaffolding.
- `README.md`: status corrected from "Pre-code, spec-complete" (stale) to scaffolded; fixed the
  `.claude.md` link (file is `CLAUDE.md`); removed the `brainstorming.pdf` links — that file is
  excluded by `.gitignore`'s `*.pdf` rule, so those links 404 for anyone reading on GitHub.
- Wrote the first build-log post — published on the portfolio site (`portfolio-v2`, `src/data/posts.js`)
  rather than kept in this repo, so there's one copy and no drift. It covers why
  the project exists, the architecture boundaries chosen before writing code, and why the first
  screen is only a health check.

**Not code.** No application behavior changed in this entry.
