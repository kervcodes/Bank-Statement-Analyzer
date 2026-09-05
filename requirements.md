# Requirements: Bank Statement Analyzer

This is the testable "what must be true" companion to the other three docs in this folder: `brainstorming.pdf` (why the architecture looks this way), `techstack.md` (what it's built with), and `design-notes.md` (what the user sees). Every requirement below traces back to a decision already made in one of those.

Priority note: every requirement is **Must** unless tagged otherwise. A `(Should)` tag means a strong default that can slip if it's genuinely hard; `(Could)` means nice-to-have, first thing cut under time pressure. Reference these IDs in commit messages, PR descriptions, and test names where practical (e.g. a reconciliation test named `test_req_val_003`), so a future audit of "did we actually build what we designed" is a grep, not an archaeology project.

## 1. Overview

**Problem**: manually reviewing PDF bank and credit card statements to understand spending, cash flow, and recurring charges across multiple institutions and years of history is tedious and error-prone.

**Solution**: a downloadable, local-first desktop app that ingests PDF statements from multiple banks and credit cards, extracts and normalizes transactions, validates the extraction against the statement's own totals, and produces a dashboard, report, and export, with an optional AI-generated plain-English summary layered on top of deterministic numbers.

**v1 user**: a single local user (you), running the app on Windows, analyzing your own statements. Not multi-user, not hosted, no accounts or auth.

**v1 institutions**: Chase, Citizens, Capital One, Santander, Citi (banks), Chase, Capital One, Citi, Best Buy, Home Depot, and "Cardis" (issuer to confirm) as credit cards. Per `techstack.md` section 8, build and fully validate one institution end to end before adding the rest.

### 2. Intake and Upload

- **REQ-INT-001**: The system shall accept one or more PDF files selected via drag-and-drop or a file browser.
- **REQ-INT-002**: The system shall treat upload failure (file never received) and validation failure (file received but rejected) as distinct states, each with its own user-facing reason.
- **REQ-INT-003**: The system shall accept a PDF as valid only if it is readable, not password-protected, and within a supported size/page count.
- **REQ-INT-004**: The system shall reject non-PDF files, corrupted PDFs, and password-protected PDFs with a specific, actionable reason, not a generic error.
- **REQ-INT-005**: A failure on any single file shall never block or discard the other files in the same upload.
- **REQ-INT-006**: The system shall group every upload into a batch, tracked from the moment files are selected, even if some files fail before processing begins.

### 3. Background Processing

#### 3.1 Job Queue and Status

- **REQ-PROC-001**: Statement processing shall run asynchronously in the background; the UI shall remain responsive while any number of statements are queued or processing.
- **REQ-PROC-002**: Each statement shall be processed as an independent job with its own status (`QUEUED`, `PROCESSING`, `RETRYING`, `COMPLETED`, `FAILED`, `UNSUPPORTED`).
- **REQ-PROC-003**: The job queue shall carry a reference to the temporarily stored PDF, never the PDF bytes themselves.
- **REQ-PROC-004**: A batch's statements shall be excluded from the processing queue if they failed intake validation; invalid files never enter the queue.

#### 3.2 Retry and Batch Completion

- **REQ-PROC-101**: Retryable failures (worker crash, transient I/O error, OCR timeout) shall be retried automatically, up to 2 retries (3 total attempts).
- **REQ-PROC-102**: Deterministic failures (corrupted file, password-protected, unsupported format) shall not be retried.
- **REQ-PROC-103**: A batch shall be marked ready for aggregation only once every processable statement job has reached a terminal state.

### 4. Extraction (Native Text and OCR)

- **REQ-EXT-001**: The system shall inspect each PDF to determine whether it contains usable embedded text before choosing an extraction method.
- **REQ-EXT-002**: Native text extraction shall be attempted first; OCR shall run only as a fallback when embedded text is unusable or absent.
- **REQ-EXT-003**: Native extraction and OCR shall both converge on the same extracted-text contract, so nothing downstream needs to know which method was used.
- **REQ-EXT-004**: An OCR failure shall mark the statement as a processing failure, not silently return partial or garbled text.

### 5. Bank Detection and Parsing

- **REQ-DET-001**: The system shall detect the issuing bank, account type, and statement layout version from extracted content, not from the filename.
- **REQ-DET-002**: Detection shall produce a confidence score; below a defined threshold, the statement shall be marked `UNSUPPORTED` rather than parsed with a best-guess parser.
- **REQ-DET-003**: Each supported institution and layout shall have its own versioned parser module (e.g. `chase_checking_v1`), so a layout redesign adds a new version without modifying the old one.
- **REQ-DET-004**: The system shall ship with a working, tested parser for at least one institution at v1 launch, with the remaining confirmed institutions (section 1) added incrementally.

### 6. Canonical Schema and Normalization

- **REQ-NORM-001**: Every parser shall output transactions and statement metadata in the shared canonical schema defined in `techstack.md` section 9, regardless of source institution.
- **REQ-NORM-002**: `description_raw` (the original statement text) shall be preserved unmodified alongside `description_normalized` (cleaned); the raw value shall never be overwritten.
- **REQ-NORM-003**: `amount` shall be stored as a positive numeric value with an explicit `direction` (DEBIT/CREDIT), never a signed amount alone.
- **REQ-NORM-004**: Every transaction shall retain `statement_id` and `source_page` so it remains traceable to its origin even after the raw PDF is deleted.
- **REQ-NORM-005**: No component downstream of normalization (validation, dedup, analytics, categorization) shall branch on which bank produced the data.
- **REQ-NORM-006**: Every monetary field (`amount`, `balance_after`, `opening_balance`, `closing_balance`) shall be stored as an integer count of minor units (cents), never as a float or an unconstrained decimal type; a value with sub-cent precision shall be rejected, not rounded, since it indicates a misread rather than a display rounding case.

### 7. Account Resolution

- **REQ-ACC-001**: The system shall derive a stable internal account identifier from bank, account type, and masked account digits, and shall never store the full account number.
- **REQ-ACC-002**: Statements shall be grouped by resolved account identity, not merely by bank name, so two accounts at the same bank are never merged by default.
- **REQ-ACC-003** (Should): When account matching is ambiguous, the system shall create a provisional account and surface it for user confirmation rather than silently merging or silently splitting.
- **REQ-ACC-004** (Should): The user shall be able to view and manually merge or correct account groupings from the Accounts screen.

### 8. Financial Validation

- **REQ-VAL-001**: Every parsed statement shall pass three validation levels before being trusted by analytics: structural (required fields present), transaction-level (valid dates/amounts/direction), and financial reconciliation (opening balance + credits minus debits approximately equals closing balance, within rounding tolerance).
- **REQ-VAL-002**: Validation result shall be one of `VALID`, `WARNING`, or `FAILED`, not a bare pass/fail, and shall be visible per statement.
- **REQ-VAL-003**: A statement that fails validation shall be excluded from trusted analytics but shall not remove or invalidate other statements in the same batch.
- **REQ-VAL-004**: Extraction confidence (how well the text was read) and financial validation (whether the resulting numbers reconcile) shall be tracked as two separate signals, not conflated into one confidence score. At the statement level this is two independent fields: `extraction_status` (`SUCCESS` or `PARTIAL` — could the document be read) and `validation_result` (`VALID`/`WARNING`/`FAILED`, nullable until validation runs — do the numbers reconcile). A statement may legally be `SUCCESS` and `FAILED` at once (cleanly read, doesn't reconcile).
- **REQ-VAL-005**: A `Statement` record shall only ever represent a document that was successfully parsed; a file that failed extraction or fell below the bank-detection confidence threshold (REQ-DET-002) shall not produce a `Statement` row; its failure/unsupported state is tracked on the statement job (section 3) instead.

### 9. Deduplication

- **REQ-DEDUP-001**: The system shall run statement-level duplicate detection (same account, period, opening/closing balance) before transaction-level detection.
- **REQ-DEDUP-002**: Transaction-level duplicate detection shall use the strongest available combination of account, date, amount, direction, normalized description, and reference ID, not timestamp, which most statements omit.
- **REQ-DEDUP-003**: Duplicate confidence shall resolve to one of three outcomes: high confidence (auto-collapse), possible (keep both, flag for review), or not a duplicate (keep both).
- **REQ-DEDUP-004**: The system shall never silently delete a transaction on ambiguous evidence; a missed duplicate is an acceptable outcome, a wrongly deleted real transaction is not.

### 10. Analytics Engine

- **REQ-ANLY-001**: Cash flow, spending-by-category, recurring charges, merchant totals, and trend comparisons shall be computed by deterministic code, never by the LLM.
- **REQ-ANLY-002** (Should): Recurring-charge detection shall match on merchant, cadence, and a similar (not identical) amount, so subscriptions with small price drift are still detected.
- **REQ-ANLY-003**: Analytics shall operate only on the unified, deduplicated ledger, never directly on individual statements or raw PDFs.
- **REQ-ANLY-004**: Analytics output shall be structured (not free text) so it can feed both the dashboard and, separately, the LLM explanation layer.

### 11. Categorization

- **REQ-CAT-001**: Categorization shall attempt a deterministic rule/merchant mapping before falling back to LLM assistance.
- **REQ-CAT-002**: Merchant normalization shall happen before categorization (e.g. "UBER *TRIP" and "UBER TECHNOLOGIES" both resolve to merchant "Uber") so rules and LLM calls both operate on clean input.
- **REQ-CAT-003**: A category assigned below a confidence threshold shall be marked `Uncategorized` and routed to Review, never presented as a confident guess.
- **REQ-CAT-004**: A user category correction shall override the automated category and shall be stored as a rule applied to future transactions from that merchant.

### 12. LLM and Privacy Gateway

#### 12.1 Privacy Gateway (Sanitization)

- **REQ-LLM-001**: Every path from the application into the LLM (explanation and categorization assistance both) shall pass through one shared sanitizer module; there shall be no direct call site that bypasses it.
- **REQ-LLM-002**: The sanitizer shall strip or mask full account numbers, routing numbers, full legal names, addresses, phone numbers, email addresses, customer/member IDs, check numbers, and card numbers before any data leaves the machine.
- **REQ-LLM-003**: Raw statement text (`description_raw`) shall never be sent to the LLM as-is; only normalized, sanitized descriptions may be sent.

#### 12.2 Provider Configuration and Availability

- **REQ-LLM-101**: The system shall support both Anthropic Claude and OpenAI as LLM providers, selectable by the user, behind a single provider interface.
- **REQ-LLM-102**: The app shall be fully functional without any LLM key configured; deterministic analytics, rule-based categorization, and the dashboard shall not depend on LLM availability.
- **REQ-LLM-103**: API keys shall be stored via the OS keychain (Electron `safeStorage`), never in plaintext configuration or in the application database.

#### 12.3 Explanation Presentation

- **REQ-LLM-201**: An LLM-generated explanation shall be visually and structurally distinct from computed figures and shall never be the sole source of a reported number.

### 13. Reporting and Export

#### 13.1 Coverage and Trust

- **REQ-RPT-001**: The dashboard shall display a coverage summary (statements processed vs. expected, date range, excluded statements) before or alongside any financial totals.
- **REQ-RPT-002**: A batch with any excluded or failed statement shall be shown as `COMPLETED_WITH_WARNINGS`, never presented as a complete analysis.
- **REQ-RPT-003**: Every transaction, even after its source PDF has been deleted, shall retain enough metadata (source statement, page, parser version) to answer "where did this come from."

#### 13.2 Drill-down and Export

- **REQ-RPT-101**: Every reported number (a category total, a chart segment, a recurring charge) shall be clickable through to the underlying transactions.
- **REQ-RPT-102** (Should): The system shall support exporting the normalized ledger as CSV and/or JSON.

### 14. Review and Correction

- **REQ-REV-001** (Should): Possible duplicates, low-confidence categorizations, and failed/unsupported statements shall surface in a single Review view, per `design-notes.md` section 3.4.
- **REQ-REV-002** (Should): The Review view shall show a live count in the app's navigation whenever any item needs attention.
- **REQ-REV-003**: A failed statement shall offer a retry action (for retryable failures) or a re-upload prompt (for deterministic failures), directly from Review or History.

### 15. Settings and Configuration

- **REQ-SET-001**: The user shall be able to enter, test, and update API keys for Claude and OpenAI independently.
- **REQ-SET-002**: The user shall be able to toggle whether raw PDFs are deleted after processing or retained.
- **REQ-SET-003** (Could): The user shall be able to view and edit the merchant-to-category rule table directly, not only reactively through Review.

### 16. Data Retention and Cleanup

- **REQ-CLEAN-001**: A raw PDF shall exist only for the duration of processing and shall be deleted immediately afterward, unless the user has opted to retain originals (REQ-SET-002).
- **REQ-CLEAN-002**: Normalized application data (statements, transactions, analytics) shall persist independently of the raw PDF's lifecycle.
- **REQ-CLEAN-003**: No raw statement text, full account numbers, or API keys shall appear in application logs.

### 17. Non-Functional Requirements

#### 17.1 Performance

- **NFR-PERF-001** (Should): A single statement with usable embedded text shall complete extraction through validation in under 5 seconds on typical consumer hardware.
- **NFR-PERF-002** (Should): A statement requiring OCR shall complete in under 30 seconds.
- **NFR-PERF-003**: The UI shall remain responsive (no blocked main thread) while any batch, regardless of size, is processing in the background.

#### 17.2 Security

- **NFR-SEC-001**: All requirements in sections 12 (Privacy Gateway) and 16 (retention/cleanup) are treated as security requirements, not optional hardening.
- **NFR-SEC-002**: The Electron renderer shall run with `contextIsolation: true` and `nodeIntegration: false`; all Node/IPC access shall go through an explicit preload bridge.

#### 17.3 Reliability

- **NFR-REL-001**: A single statement failure, at any pipeline stage, shall never crash the application or block unrelated statements or batches.

#### 17.4 Portability

- **NFR-PORT-001**: The app shall build and run as a Windows installer for v1.
- **NFR-PORT-002** (Should): A macOS build is a should-have for v1, not a blocker; timing to be confirmed (open item in `techstack.md` section 20).

#### 17.5 Maintainability

- **NFR-MAINT-001**: Each bank/layout parser shall have its own automated regression test using a real or representative sample statement, per `techstack.md` section 14.
- **NFR-MAINT-002**: Financial reconciliation, deduplication confidence scoring, and retry state transitions shall each have dedicated unit tests, since these are the components most likely to silently produce wrong financial conclusions if broken.

#### 17.6 Cost

- **NFR-COST-001**: The app shall have no required ongoing hosting cost; the only recurring cost is optional, user-initiated LLM API usage on their own key.

### 18. Constraints and Assumptions

- Single local user, single machine, no accounts or authentication in v1.
- PDF is the only supported input format; CSV, OFX/QFX, images, and direct bank API connections are explicitly out of scope (section 19).
- The user has already confirmed API access to both Claude and OpenAI, so REQ-LLM-101 can be built and tested against both from the start.
- Institutions in scope are limited to those the user actually holds statements for (section 1); the parser registry pattern (REQ-DET-003) is what makes adding more later a non-event.
- The "Cardis" credit card issuer needs its real name confirmed before a parser is scoped for it.

### 19. Out of Scope for v1

CSV/OFX/QFX import, direct bank API connections (Plaid or similar), multi-user accounts or authentication, a hosted/server-deployed version, mobile app, local LLM via Ollama, SQLite-at-rest encryption, auto-update, license key / paywall enforcement (tracked separately as a future phase in `techstack.md` section 19), macOS code signing and notarization (only needed once macOS distribution and/or monetization is active).

### 20. v1 Definition of Done

- [ ] A user can drop in PDF statements for at least one confirmed institution (section 1) and reach a working Dashboard end to end, with no manual steps outside the app.
- [ ] Coverage, warnings, and excluded statements are visible on the Dashboard without digging into logs or a separate screen.
- [ ] A batch with a deliberately corrupted or password-protected PDF included still successfully processes the other valid statements in that batch.
- [ ] Reconciliation validation correctly flags a statement where opening balance plus credits minus debits does not match the closing balance.
- [ ] Deduplication correctly auto-collapses an intentionally duplicated statement and correctly flags (without auto-deleting) two genuinely separate same-day, same-amount transactions.
- [ ] The app functions fully (analytics, categorization, dashboard) with no LLM API key configured.
- [ ] With a Claude or OpenAI key configured, the AI summary panel renders and is visibly separated from computed figures.
- [ ] Every transaction on the Dashboard can be clicked through to its source statement and page.
- [ ] Raw PDFs are confirmed deleted from disk after processing (verified by inspecting the temp storage location), unless retention is explicitly enabled in Settings.
- [ ] The app packages into a working Windows installer that runs correctly on a clean machine (no Python or Node installed).

### 21. Traceability

Every REQ/NFR ID above should be referenced in commit messages, PR descriptions, and test names where practical, so a future audit of "did we actually build what we designed" is a grep, not an archaeology project.
