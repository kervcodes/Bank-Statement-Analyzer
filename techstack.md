# Tech Stack: Bank Statement Analyzer

This file is the build reference for Claude Code. It reflects the architecture worked out in `brainstorming.pdf` (a 79-page design conversation) plus two decisions locked in on 2026-09-04: the app ships as a downloadable, local-first Electron desktop app, and the LLM layer uses a hosted API (not a local model) behind the Privacy Gateway. Read this alongside `.claude.md` (coding conventions) before writing code. When in doubt, favor the simpler option. This is a v1 for a single local user, not a multi-tenant SaaS.

## 1. Product shape (recap)

- Input: PDF bank statements only. No CSV, OFX/QFX, images, or direct bank connections in v1.
- Runs entirely on the user's machine as a downloadable app (Windows and macOS installers). No server to operate, no hosting bill.
- Single user per install. No auth, no accounts, no multi-tenancy.
- Processing is async in the background (a user can drop in 100+ statements across 5 banks without freezing the UI).
- Raw PDFs are temporary and deleted after processing. Normalized data persists locally.
- Deterministic code owns every financial number. The LLM only explains results or assists with low-confidence categorization, and only ever sees sanitized, PII-stripped data through a Privacy Gateway.

## 2. Architecture at a glance

```
Electron App (installed on user's machine)
├── Renderer process (React UI)
│        │  HTTP (127.0.0.1:8420)
│        ▼
├── Main process ──spawns──► FastAPI backend (Python, packaged sidecar)
│                                   │
│                                   ├── Intake: upload, validate, temp-store PDF
│                                   ├── Job queue (SQLite-backed) + worker pool
│                                   ├── Extraction: native text or OCR fallback
│                                   ├── Bank/format detection + versioned parsers
│                                   ├── Canonical schema + financial validation
│                                   ├── Dedup + deterministic analytics engine
│                                   ├── Rule-based categorization (+ LLM fallback)
│                                   ├── Privacy Gateway (sanitizer) ──► Hosted LLM API
│                                   └── Local SQLite (app data store)
```

Seven zones from the brainstorm map directly onto this: User/Client = renderer, Intake + Background Processing + Extraction/Normalization + Trusted Data/Aggregation + Enrichment/Analytics/AI all live in the FastAPI backend, Outputs render back in the renderer.

## 3. Frontend (Electron renderer)

| Choice | Why |
|---|---|
| Electron (latest stable) | You asked for it directly, and it's the right fit: local-first, downloadable, cross-platform, mature ecosystem, pairs naturally with React. |
| Vite + React 19 + TypeScript | Not Next.js here, on purpose. Next's server-rendering and API routes are dead weight inside a desktop shell that already has a backend. Vite gives a plain client-side SPA with fast HMR, which is exactly what an Electron renderer needs. Keep Next.js for your hosted web projects; this one is different. |
| Tailwind CSS 4 + shadcn/ui | Matches your usual frontend stack, gives you accessible components fast without hand-rolling a design system. |
| TanStack Query | Handles polling job/batch status from the backend (progress bars, "82/120 completed") without hand-rolled state machines. |
| Zustand | Lightweight local UI state (active batch, selected account, filters). Don't reach for Redux here, it's overkill for this scope. |
| Recharts | Cash flow, spending breakdown, trend charts on the dashboard. Simple API, plays well with Tailwind. |
| React Hook Form + Zod | Settings screen (LLM API key, retention preferences) and any manual-review forms. |

Security note: enable `contextIsolation: true` and disable `nodeIntegration` in the renderer. Expose only a narrow, explicit IPC bridge via a preload script (e.g. `window.api.getBatches()`), never the raw Node/Electron API. This matters more than usual here because the app handles financial documents.

## 4. Backend (Python, local sidecar)

| Choice | Why |
|---|---|
| Python 3.12+, managed with `uv` | Already your convention per `.claude.md`. No reason to deviate. |
| FastAPI | Async-native, plays well with the queue/worker model, gives you OpenAPI docs for free while you're iterating with Claude Code. |
| Pydantic v2 | Request/response validation and the canonical transaction/statement schema from the brainstorm map directly onto Pydantic models. |
| SQLModel | Built on Pydantic + SQLAlchemy by the FastAPI author. One model definition serves both the API layer and the DB layer, which keeps this small project from growing unnecessary duplication. |
| Alembic | Schema migrations, even for a local SQLite app. You will change the schema more than once; don't hand-roll migrations. |
| httpx | Outbound calls to the hosted LLM API from the Privacy Gateway. |

Run it in dev with `uv run uvicorn app.main:app --port 8420 --reload`, spawned automatically by an Electron dev script (see section 10).

## 5. Local persistence

Two separate storage responsibilities, kept separate on purpose (this was an explicit invariant in the brainstorm):

- **Temporary file storage**: raw uploaded PDFs, written to the app's local temp/user-data directory. Deleted immediately after a statement finishes processing, unless the user explicitly opts to keep originals. Never synced, never leaves the machine.
- **Application data store**: SQLite (via SQLModel), one file in the app's user-data directory (e.g. `%APPDATA%/bank-statement-analyzer/app.db` on Windows, `~/Library/Application Support/...` on macOS). Holds batches, accounts, statements, transactions, validation results, analytics output, category rules, and user corrections. This is what powers the dashboard after the raw PDF is gone.

SQLite over Postgres here is deliberate: this is a single-user desktop app, and requiring a database server install would kill the "just download and run it" experience. If you ever build the hosted/multi-user version the brainstorm floated as a fork, SQLModel's ORM layer makes swapping the engine to Postgres a config change, not a rewrite.

Optional hardening (not v1-blocking, flag as a fast-follow): encrypt the SQLite file at rest with SQLCipher (`pysqlcipher3`), since this is financial data sitting on a user's disk. For v1, rely on OS-level disk protections and ship this later if it becomes a real ask.

## 6. Background processing (no Redis, no Celery)

A single local user doesn't need a distributed message broker. Use a SQLite-backed job table plus an in-process worker pool:

- A `statement_jobs` table with status (`QUEUED`, `PROCESSING`, `RETRYING`, `COMPLETED`, `FAILED`, `UNSUPPORTED`) and `attempt_count`, matching the state machine from the brainstorm exactly.
- A small worker loop polling for `QUEUED` jobs, dispatching to a `concurrent.futures.ProcessPoolExecutor` (OCR and PDF parsing are CPU-bound, so process-based parallelism beats threads here).
- Retry only retryable failures (worker crash, transient I/O, OCR timeout), never deterministic ones (corrupted PDF, password-protected, unsupported format), capped at 2 retries (3 attempts total), exactly as decided in the brainstorm.
- A `BatchCoordinator` service (not a separate process, just an application service) tracks per-batch counts and flips the batch to `COMPLETED` or `COMPLETED_WITH_WARNINGS` once every processable job reaches a terminal state.
- One failed statement never blocks or invalidates the rest of the batch.

If this app later grows into a hosted multi-user product, this is the piece to swap for Postgres-backed `SELECT ... FOR UPDATE SKIP LOCKED` or an actual broker (SQS, Redis). Don't build that now, it would be solving a scale problem you don't have.

## 7. PDF extraction and OCR

| Choice | Why |
|---|---|
| `pdfplumber` (built on `pdfminer.six`) | Inspect PDFs and extract native embedded text. Permissively licensed, which matters here since you're distributing a packaged binary to users, unlike a library you'd only run on your own server. |
| `pdf2image` + Poppler | Renders PDF pages to images when native text extraction is unusable, feeding the OCR fallback. |
| `pytesseract` + Tesseract OCR | The OCR engine itself. Free, offline, well-established, and small enough to bundle with the app installer. |

Deliberately not `PyMuPDF` (fitz) here even though it's faster and more convenient: it's AGPL-licensed (or requires a paid commercial license from Artifex). For a library you run on your own server that's usually a non-issue; for a binary you hand out to other people to install, it's a real licensing question you don't want to answer later. If you decide the AGPL terms are fine for a personal portfolio project, it's a reasonable swap, just make that call consciously rather than by accident.

Extraction contract (from the brainstorm, this boundary matters): both paths converge on the same "extracted text" shape before anything downstream runs, so nothing after this stage needs to know whether the source was native text or OCR.

OCR is a fallback, never the default. Check for usable embedded text first (not just "does the PDF contain any text," but "is a reasonable fraction of pages text with recoverable structure").

Packaging note: Tesseract's binary has to ship inside the Electron installer (via `electron-builder`'s `extraResources`), and `pytesseract` needs to be pointed at that bundled path at runtime rather than assuming it's on the system `PATH`.

## 8. Bank detection and parsers

- Detection runs on extracted text content, never on filename. Output includes `bank`, `account_type`, `statement_layout_version`, and a `confidence` score.
- Each supported institution/layout gets its own versioned parser module (e.g. `parsers/chase_checking_v1.py`), registered in a parser registry keyed by `(bank, account_type, layout_version)`. A bank redesigning its statement format means adding `chase_checking_v2`, not touching `v1`.
- Below a confidence threshold: mark `UNSUPPORTED`, don't guess. A confidently wrong parser producing believable-but-incorrect financial data is worse than a clear failure.

Confirmed institutions to build parsers for (2026-09-04), a mix of bank accounts and credit cards, which the canonical schema already handles since `account_type` is just a field on `Statement`:

- Banks (checking/savings): Chase, Citizens, Capital One, Santander, Citi
- Credit cards: Chase, Capital One, Citi, Best Buy, Home Depot, and one more issuer noted as "Cardis" (name unconfirmed, double-check the exact issuer before building that parser, since store cards are frequently issued by a third party like Synchrony or Citi rather than the retailer itself)

That is 7+ institutions, more than a v1 should try to build at once. Don't parallelize all of them. Build and fully validate one parser end-to-end first (extraction through reconciliation through the dashboard), prove the pipeline works on real statements, then add the rest one at a time. Pick whichever single institution you have the most historical statements for as the first target, since that gives the fastest feedback loop and the most real test fixtures. Store-card statements (Best Buy, Home Depot) are usually simpler than a full bank statement (single account, fewer transaction types), so they can be good later additions once the harder bank/credit-card parsers are proven.

## 9. Canonical schema and validation

Every parser must output the same shape regardless of source bank (Pydantic models in `app/models/canonical.py`):

- `Transaction`: `transaction_id`, `statement_id`, `account_id`, `transaction_date`, `posted_date`, `description_raw`, `description_normalized`, `amount`, `direction` (DEBIT/CREDIT), `balance_after` (optional), `category` (optional, assigned later), `source_bank`, `extraction_confidence`, `source_page`.
- `Statement`: `statement_id`, `batch_id`, `bank`, `account_type`, `account_identifier_masked` (last 4 only, never the full account number), `statement_start_date`, `statement_end_date`, `opening_balance`, `closing_balance`, `parser_version`, `extraction_status`.

Validation runs in three layers before anything is trusted by analytics: structural (required fields present), transaction-level (valid dates, numeric amounts, sane ranges), and financial reconciliation (`opening_balance + credits - debits ≈ closing_balance`, allowing small rounding tolerance). Result is `VALID`, `WARNING`, or `FAILED`, not a bare pass/fail. Nothing enters portfolio-level analytics until it clears minimum validation, but a small number of failed statements never blocks analysis of the rest, coverage gaps just get shown explicitly ("117 of 120 statements processed, excluding: ...").

## 10. Deduplication and analytics engine

- Two-pass dedup: statement-level first (same account, period, opening/closing balance strongly suggests the same file uploaded twice), then transaction-level (date, amount, direction, normalized description, reference ID where available).
- Three outcomes, not a binary: `HIGH confidence` auto-collapses, `POSSIBLE duplicate` keeps both and flags, `NOT DUPLICATE` keeps both. Bias toward false negatives, silently deleting a real transaction is worse than a flagged possible duplicate.
- Analytics engine (plain Python, `pandas` for the aggregation-heavy parts) computes cash flow, spending by category, recurring charges, merchant totals, and trend comparisons deterministically. It outputs structured facts (a small JSON/dict shape) that the LLM later explains in prose. It never asks the LLM to do arithmetic.
- Recurring-charge detection matches on normalized merchant + repeat interval + similar (not identical) amount, not a naive "same amount every month" rule, since real subscriptions drift.

## 11. Categorization

Layered, cheapest-first: exact rule/merchant mapping (deterministic, instant, free) is tried first, hosted LLM assistance only kicks in when a merchant isn't recognized. User corrections always override automated categorization and get remembered for that merchant going forward. Low-confidence results degrade to `Uncategorized`, never to a confident-looking guess.

## 12. LLM integration and Privacy Gateway

You chose a hosted API over a local model, which is reasonable given the sanitizer design already makes model location a non-issue for privacy ("model location is not the privacy control, sanitization is the privacy control," straight from the brainstorm). Concretely:

- **Provider**: since you already hold API keys for both Anthropic Claude and OpenAI, build a small provider interface (`LLMProvider` protocol with `explain()` and `categorize()` methods) with two implementations, rather than hard-committing to one. Default to Claude (generally strong instruction-following for "explain these numbers in plain English" and "suggest a category for this merchant" tasks), let the user pick either in Settings. This is a thin abstraction, not overengineering, since you have concrete, immediate use for both.
- **Privacy Gateway**: every single path into the model (categorization assistance and result explanation both) routes through one sanitizer module, never called directly by any other service. It strips or masks before anything crosses the network: full account numbers, routing numbers, full legal names, addresses, phone/email, customer/member IDs, check numbers, card numbers. Merchant names are generally kept (they're useful for explanations and not typically PII), but raw `description_raw` text is not sent as-is, since it can contain things like `VENMO KERVINTZ NOEL`; only the normalized, sanitized description goes out.
- **What the model actually receives**: small, task-specific structured payloads like `{"merchant": "Netflix", "amount": 22.99, "category": "Entertainment", "frequency": "monthly"}`, never raw statement text and never full account identifiers.
- **API key handling**: since this ships as a downloadable app to (presumably) just you for now, use a bring-your-own-key model. The user pastes their Anthropic API key into a settings screen; store it via Electron's `safeStorage` API (OS-keychain-backed encryption on Windows/macOS), never in plaintext config or in the SQLite DB. This also means you don't have to pay for or proxy anyone else's usage.
- **Cost**: a handful of small structured API calls per analysis run, this should run a few cents per report at most given typical Claude/GPT pricing for short prompts. Worth surfacing an estimated-cost note in settings if you want to be transparent about it.
- **If the key is missing or invalid**: the app must still work. Deterministic analytics, categorization (rule-based), and the dashboard all function without the LLM; only the plain-English explanation and LLM-assisted categorization fallback are skipped.

## 13. Desktop packaging and distribution

This is the part with the most real engineering risk, budget time for it:

- **Backend packaging**: use `PyInstaller` to bundle the FastAPI app plus its dependencies into a single standalone executable (`backend/dist/analyzer-backend.exe` on Windows, no extension on macOS). This is what Electron's main process actually spawns in production, no Python install required on the end user's machine.
- **Frontend + shell packaging**: `electron-builder` produces the installers (`.exe`/NSIS for Windows, `.dmg`/`.zip` for macOS). Bundle the PyInstaller output and the Tesseract binary via `extraResources`.
- **Process lifecycle**: Electron's main process spawns the backend executable on a fixed local port (e.g. `127.0.0.1:8420`), polls a `/health` endpoint until it's ready before loading the renderer, and kills the child process on app quit (`app.on('will-quit', ...)`). Handle the port-already-in-use case gracefully (another instance already running, or a stale process).
- **Auto-update**: `electron-updater` if you want the app to self-update later; skip it for v1, it's not needed until you have real users beyond yourself.
- **Code signing matters more than usual here**: since you're planning to eventually charge for this app, factor code-signing cost/setup in earlier than you would for a pure portfolio piece. An unsigned installer is a real conversion killer, macOS Gatekeeper will hard-block an unsigned/unnotarized app for most users, and Windows SmartScreen throws a scary warning on unsigned executables. You don't need this for v1 while you're building and testing solo, but plan for an Apple Developer account (notarization) and a Windows code-signing certificate before you actually try to sell it.
- **Alternative worth knowing about**: Tauri (Rust-based) produces much smaller installers since it uses the OS's system webview instead of bundling Chromium. Electron is the right starting choice given your React familiarity and the maturity of the Python-sidecar pattern in that ecosystem; revisit Tauri only if installer size becomes an actual complaint.

## 14. Testing strategy

| Layer | Tooling |
|---|---|
| Backend unit/integration | `pytest`, per your existing convention. Build a fixture library of sample (synthetic or redacted) statements per bank/layout, this is the single highest-value test investment for this project since parser correctness is the core risk. |
| Parser regression | Golden-file tests: known input PDF → expected canonical transaction list. Run these on every parser change. |
| Financial validation logic | Property-style tests: reconciliation math, dedup confidence scoring, retry/backoff state transitions. |
| Frontend | Vitest + React Testing Library for components; mock the local API layer rather than hitting the real backend. |
| End-to-end (optional, later) | Playwright can drive the packaged Electron app if you want true end-to-end coverage. Not necessary for v1. |

## 15. CI/CD (GitHub Actions)

Three workflows, kept separate per your usual dev/staging/prod split, adapted for a desktop app (no staging environment here, since there's no server to stage):

- **`ci.yml`** (on every PR against `main`, and on push to `main`): currently `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pytest` for the backend, with a 90% coverage floor enforced by pytest-cov (`requirements.md` NFR-MAINT-003) rather than a separate CI-only check. `uv run mypy .` and frontend `pnpm lint`/`pnpm test` are not wired in yet — no `mypy` config exists yet, and `apps/desktop` has no test script to run.
- **`build.yml`** (on every PR, optional but recommended): builds unsigned installers for Windows and macOS as a smoke test that packaging still works, without publishing them.
- **`release.yml`** (on a version tag): full PyInstaller + electron-builder build, produces signed installers (code signing certs needed for a clean install experience, especially on macOS) and attaches them to a GitHub release.

## 16. Security and privacy checklist

Straight from the brainstorm's locked invariants, made concrete as engineering requirements:

- Raw PDFs exist only for the duration of processing; delete after normalization completes, unless the user explicitly opts to retain originals.
- The queue/job table carries a file reference, never the PDF bytes.
- Full account numbers, routing numbers, and full names are never persisted or sent to the LLM; only masked last-4 account identifiers.
- Every model call, no exceptions, routes through the Privacy Gateway sanitizer.
- Even after a raw PDF is deleted, every reported number stays traceable to its source (`source_statement_id`, `source_page`, `parser_version`) for auditability.
- Never log full statement text, account numbers, or the LLM API key.
- The app must be honest about incomplete data: a batch with excluded/failed statements is always shown as `COMPLETED_WITH_WARNINGS` with an explicit list of what's missing, never silently presented as a complete analysis.

## 17. Proposed repository structure

```
bank-statements-analyzer/
├── apps/
│   ├── desktop/                      # Electron + React frontend
│   │   ├── electron/
│   │   │   ├── main.ts               # spawns/kills the backend sidecar
│   │   │   └── preload.ts            # IPC bridge, contextIsolation on
│   │   ├── src/
│   │   │   ├── components/
│   │   │   ├── pages/                # Upload, Batches, Dashboard, Settings
│   │   │   ├── hooks/                # TanStack Query hooks per endpoint
│   │   │   └── stores/               # Zustand stores
│   │   ├── package.json
│   │   └── electron-builder.yml
│   └── backend/                      # Python FastAPI sidecar (uv-managed)
│       ├── src/
│       │   └── app/
│       │       ├── api/              # FastAPI routers, thin
│       │       ├── services/         # validation, dedup, analytics, privacy gateway
│       │       ├── parsers/          # one module per bank/layout version
│       │       ├── models/           # SQLModel + canonical Pydantic schemas
│       │       ├── workers/          # job queue + worker pool
│       │       └── utils/
│       ├── tests/
│       │   └── fixtures/statements/  # sample PDFs per bank/layout
│       └── pyproject.toml
├── docs/
│   └── activity.md
├── tasks/
│   └── todo.md
├── .github/workflows/
├── techstack.md
└── .claude.md
```

## 18. Explicitly out of scope for v1

CSV/OFX/QFX import, direct bank API connections, multi-user accounts or auth, a hosted/server-deployed version, mobile app, local LLM via Ollama (revisit only if hosted-API cost or privacy comfort changes), SQLite-at-rest encryption (fast-follow, not blocking), auto-update.

## 19. Monetization (future, not v1)

You mentioned wanting to eventually charge a one-time fee for access. Don't build any of this yet, but the architecture above was chosen so it doesn't block this later:

- **Licensing mechanism**: for a one-time fee on a local-first app with no server to operate, the standard indie pattern is a payment processor built for solo developers (Lemon Squeezy or Gumroad, both handle sales tax/VAT compliance for you, which is a real headache to DIY) that generates a license key on purchase. The app validates that key **offline**, using public-key signature verification (an Ed25519-signed license embedded with the key, checked against a public key baked into the app). This means no ongoing server, no phone-home requirement, and it stays consistent with the local-first, privacy-first story you're building. This is a self-contained addition later: a `LicenseService` that gates certain features (or gates the whole app after a trial period/statement count) without touching anything in this document.
- **One real fork to think about before you build the paywall**: whether paying customers bring their own Claude/OpenAI API key (keeps your costs at zero forever, but is real friction for a non-technical buyer who doesn't have one) or whether the one-time fee includes some amount of LLM usage (better buyer experience, but means routing their requests through a small relay you operate and pay the API bill for, which turns a one-time fee into an ongoing cost on your side unless usage is capped per license). The provider abstraction in section 12 supports either path without a rewrite: BYOK today, and if you add a metered relay later, it's a third `LLMProvider` implementation, not a redesign.
- Revisit this section once the core pipeline and 1 to 2 parsers are working end-to-end. Building payment/licensing before the product itself works is a common way to burn time on the wrong problem first.

## 20. Open items to confirm before Claude Code starts building

- Exact issuer for the card you referred to as "Cardis", the name doesn't match a bank/card issuer, worth double-checking before building that parser.
- Which single institution to build and fully validate first (see section 8), before parallelizing across all 7+.
- Windows-only installer for now, or macOS too from day one? Affects whether code-signing setup (see section 13) is needed immediately.
