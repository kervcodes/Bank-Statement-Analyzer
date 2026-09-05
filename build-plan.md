# Build Plan: First Prompts for Claude Code

The first 10 prompts to run against this repo with Claude Code, in order. This follows the pipeline bottom-up (schema and extraction before UI, since everything downstream depends on the canonical data being right first), and matches the "one task at a time, plan before implementing" workflow already enforced by `.claude.md`, so these prompts don't need to repeat that instruction, Claude Code picks it up automatically from the repo.

Each prompt assumes `techstack.md`, `design-notes.md`, `requirements.md`, and `brainstorming.pdf` are already in the repo for reference.

## 1. Scaffolding

- Set up the initial monorepo structure exactly as described in techstack.md section 17: apps/desktop (Electron + Vite + React + TypeScript + Tailwind) and apps/backend (Python, uv-managed, FastAPI).
- For now, just a minimal skeleton: a FastAPI app with a single GET /health endpoint.
- An Electron app whose main process spawns the backend in dev mode.
- The renderer calls /health on load and displays the result.
- Write a plan to tasks/todo.md first and let me review it before you start.

## 2. Canonical schema and local database

- Implement the canonical data model from techstack.md section 9 and requirements.md section 6 as SQLModel classes: Batch, Statement, Transaction, and Account.
- Include every field listed (source_statement_id, source_page, parser_version, extraction_confidence, direction, etc.).
- Set up Alembic and get a local SQLite database created from this schema.
- No API endpoints yet, just the models and migration.
- Write a couple of tests that write and read back a Statement and its Transactions.

## 3. Intake and validation

- Build the file intake and validation flow from requirements.md section 2 (REQ-INT-001 through 006).
- An endpoint that accepts one or more PDF uploads.
- Validate each one, store valid files in temporary storage.
- Create a Batch and return per-file status.
- Upload failure and validation failure need to be distinct, testable states.
- Test the reject cases (corrupted PDF, password-protected PDF, non-PDF file) as well as the happy path.

## 4. Extraction pipeline

- Implement the PDF extraction pipeline from requirements.md section 4.
- Inspect a PDF to decide if it has usable embedded text.
- Extract natively with pdfplumber if so, fall back to OCR (pdf2image + pytesseract) if not.
- Both paths should converge on the same extracted-text contract.
- Build it as a standalone service with unit tests against a real statement with clean embedded text and one that needs OCR.
- Don't wire it into the job queue yet.

## 5. Background job queue

- Implement the background processing system from requirements.md section 3.
- A SQLite-backed statement_jobs table.
- A worker pool that runs QUEUED jobs through the extraction pipeline from the last task.
- Retry logic: 2 retries, retryable failures only.
- A BatchCoordinator that flips a batch to COMPLETED or COMPLETED_WITH_WARNINGS once every job reaches a terminal state.
- Wire this to the intake endpoint so an upload gets queued and processed end to end.

## 6. First bank parser, end to end

- Build the first parser fully: [name your highest-priority institution, e.g. Chase checking].
- The versioned parser module.
- Bank/format detection with a confidence score.
- Normalization into the canonical schema.
- The three-level financial validation from requirements.md section 8.
- Use real or redacted sample statements as test fixtures.
- This is the milestone where a real PDF goes in and a validated, normalized statement comes out the other side.

## 7. Deduplication and analytics

- Implement deduplication (requirements.md section 9): statement-level then transaction-level, three-outcome confidence.
- Implement the deterministic analytics engine (section 10): cash flow, spending by category, recurring charges, merchant totals, trends.
- Test a deliberately duplicated statement.
- Test recurring-charge detection with a slightly varying amount.

## 8. Categorization, Privacy Gateway, and LLM

- Implement rule-based categorization with merchant normalization (section 11).
- Implement the Privacy Gateway sanitizer (section 12.1).
- Implement the Claude/OpenAI provider abstraction (section 12.2) for LLM-assisted categorization fallback and the dashboard summary.
- Every model call must go through the sanitizer.
- Write a test asserting a description containing something like an account number or full name never reaches the LLM client unsanitized.

## 9. Frontend screens

- Build the Electron/React frontend against the backend that now exists.
- Screens: Import, History, Dashboard, and Review from design-notes.md sections 3.1 to 3.4.
- Use TanStack Query for data fetching.
- Follow the visual style in section 4 (tabular-nums figures, the status color system, dark mode).
- Wire real batch progress and coverage data in, don't mock it.

## 10. Packaging

- Bundle the backend into a standalone executable with PyInstaller.
- Configure electron-builder for a Windows installer that includes the backend executable and Tesseract as extraResources.
- Wire the Electron main process to spawn the bundled backend, wait for /health, and kill it on quit.
- Verify the definition-of-done checklist in requirements.md section 20 on a clean machine.
