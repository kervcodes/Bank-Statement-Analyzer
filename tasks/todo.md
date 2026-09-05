# Todo: Test coverage requirement — block push and merge under 90%

Source: your request — "add a project requirement, blocking new push and merge if [test
coverage score] is less than 90%."

**Reading "score" as test coverage percentage** (the standard meaning for a test "score"
threshold like this) — flag now if you meant something else (e.g. a lint/quality score).

Branch: `feature/coverage-gate`, now based on `main` — after PR #4 brought `main` up to date
with everything (it had been stuck at just the monorepo skeleton; PR #2/#3 had landed on their
stacked base branches, not `main`), this branch was rebased cleanly onto `origin/main`.

## Current state (checked before writing this plan)

`uv run pytest --cov=app --cov-report=term-missing` on the real codebase: **92% total**,
already above 90%. Breakdown: `canonical.py` 100%, `models/__init__.py` 100%, `db.py` 93%
(one line uncovered), `money.py` 93% (one line uncovered), **`main.py` 0%** (the FastAPI app,
CORS middleware, and `/health` route have no automated test at all — only manually
curl-tested so far). Frontend (`apps/desktop`) has no test script (`package.json` only has
`lint`), so a coverage gate is backend-only for now.

**Not adding a test for `main.py` in this task** — 92% already clears the 90% bar, and padding
coverage on code the gate doesn't require touching would be scope creep. Noting it as a real,
known gap instead.

## What "blocking push" and "blocking merge" actually require

GitHub can't block a `git push` itself — pushes always succeed if you have write access;
CI only runs *after* a push lands and reports pass/fail. So the two asks need two different
mechanisms:

1. **Blocking push** → a client-side git pre-push hook that runs the test suite locally and
   refuses the push if it fails (which now includes the coverage gate).
2. **Blocking merge** → a GitHub Actions CI check + a branch protection rule on GitHub
   requiring that check to pass before a PR can be merged.

## 1. The gate itself (single source of truth)

- [x] Add `pytest-cov` as a backend dev dependency
- [x] `pyproject.toml`: `[tool.coverage.report] fail_under = 90`, and `--cov=app
      --cov-report=term-missing` in pytest's `addopts` — a plain `uv run pytest` fails on its
      own if coverage drops below 90%. Both the local hook and CI just run `uv run pytest`;
      neither hardcodes the number, so it's changed in one place.
- [x] `.gitignore`: added `.coverage`, `htmlcov/`, `.pytest_cache/` (none were ignored before)

## 2. Local pre-push hook (blocks push)

- [x] `.githooks/pre-push` at repo root — runs `cd apps/backend && uv run pytest -q`, exits
      non-zero (blocking the push) on failure, including the coverage gate
- [x] Documented activation in the root `README.md`: `git config core.hooksPath .githooks`
      (a hook only runs if a dev has opted in this way — git doesn't auto-run
      non-`.git/hooks`-located scripts, and hooks aren't cloned/activated automatically)

## 3. CI workflow (backend for now — blocks merge, once branch protection is set)

- [x] `.github/workflows/ci.yml` — on PR against `main` and push to `main`: `uv run ruff
      check .`, `uv run ruff format --check .`, `uv run pytest` (coverage gate included),
      scoped to `apps/backend`. Not adding a frontend test step — `apps/desktop` has no test
      script yet; keeping `pnpm lint` only would be silently misleading about what's actually
      verified, so leaving frontend CI for when there's something real to run.

## 4. Branch protection (the actual merge block — needs your call)

- [x] Configured GitHub branch protection on `main` (approved) via `gh api`: requires the
      `backend` status check to pass before merging, blocks force-pushes and branch deletion.
      `enforce_admins` left off (solo project — the repo admin can still bypass in an
      emergency). Confirmed the check name by opening PR #5 against `main` first and watching
      it actually run (`backend` — pass, 8s) before wiring protection to it.

## 5. Documentation

- [x] `requirements.md` — NFR-MAINT-003 under §17.5 Maintainability: coverage floor + what's
      blocked
- [x] `techstack.md` §15 (CI/CD) — corrected to describe what `ci.yml` actually runs today
      (removed `mypy`/frontend-test mentions that don't exist yet, rather than leaving them
      aspirational)
- [x] `docs/activity.md` — this task's entry, including the `main`-behind-the-PR-stack finding
- [x] Root `README.md` — fixed a stale "Status" section (still said "no schema yet") and added
      a Testing section

## Review

**What was completed:** a 90% backend test-coverage floor, enforced two ways — a local
pre-push git hook (blocks the push) and a GitHub Actions CI workflow plus branch protection on
`main` (blocks the merge). Both mechanisms just run `uv run pytest`; the threshold lives in
exactly one place (`pyproject.toml`).

**Found and fixed along the way:** `main` was stuck at just the monorepo skeleton — the PR
stack meant PR #2 and #3 merged into their own base branches, never reaching `main`. Opened
and got merged PR #4 to catch `main` up (no code changes, pure sync). Confirmed after:
`git diff origin/main feature/canonical-schema` is empty.

**Tests/checks run:**

- `uv run pytest` — 29 passed, 92% coverage, gate reports "Required test coverage of 90.0%
  reached"
- Mutation check: temporarily set `fail_under = 95` (above real coverage) — `uv run pytest`
  exited 1 with "Required test coverage of 95.0% not reached"; restored to 90, reconfirmed pass
- Ran `.githooks/pre-push` directly after `git config core.hooksPath .githooks` — passes
  cleanly, correct exit code

**Known issues:**

- `main.py` (FastAPI app + `/health`) has 0% test coverage. Total is still 92% so the gate
  isn't blocked by it, but it's a real, known gap — not fixed here to avoid scope creep.
- Two unrelated checks (Vercel deployments for "backend" and "desktop") are failing on PRs
  against `main` — pre-existing, not something this task set up, and not required by branch
  protection (only `backend`, this task's own CI check, is required). This project isn't a
  Vercel deployment target, so those look like a leftover/misconfigured integration; flagged
  for you, not touched here.

**Recommended next step:** build-plan.md #3 — intake and validation endpoint.
