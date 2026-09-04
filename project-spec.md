# Bank Statement Analyzer — Project Spec

**Written:** 2026-09-03
**Sources:** `resources/Design Architecture Diagrams.pdf` · [[Design-Review-and-Scope]] · [[architecture]]
**Status:** Specification + design artifact. **Nothing built.** The thin vertical slice is
queued behind P2 (BranchBeacon prospect agent) per `Design-Review-and-Scope.md` — this
document does not change that sequencing.
**Purpose of this project:** portfolio / engineering-judgment proof and personal use first.
It is not a validated business and does not become a business priority without evidence.

---

## 1. The problem

People hold money across several banks and cards and have **no trustworthy, private,
consolidated view** of their finances over time.

The existing options are bad:

- **Credential-based aggregators (Mint, Plaid-backed apps):** require handing a third party
  your bank logins, store your financial history on their servers, and still produce shallow,
  often-wrong categorization. Many people won't use them for exactly this reason.
- **Spreadsheets:** hours of manual data entry per month, error-prone, and abandoned within
  weeks.
- **Each bank's own dashboard:** siloed — it only knows about that one bank.

Every bank already produces the one artifact that solves this: the **PDF statement**. It is
authoritative, it is something you already have, and it requires no credentials to share with
a tool.

### What the app offers

Give it multiple months of statements from multiple institutions. It returns a consolidated,
**reconciled**, categorized financial overview you can actually trust:

- Every number is computed by deterministic code, not estimated by an AI.
- Each statement passes a **reconciliation check** (`opening + credits − debits ≈ closing`)
  before its data is trusted — a parser that misread `$800.00` as `$8,000` is caught here.
- Every figure in the report is **traceable** back to a specific statement, page, and parser
  version.
- Processing is **local-first**. Sensitive data is sanitized before it ever reaches a
  language model, and the model only explains numbers that already exist — it never
  calculates them.

The core value proposition is **trust and privacy**, not feature count. A simple consolidated
view the user believes is worth more than a rich dashboard they don't.

---

## 2. Who the users are

**Near-term real user: me.** The first build is dogfooded on my own real statements. That is
the only user the thin vertical slice needs.

**Operative user for the project's actual goal:** a **hiring manager or interviewer**
evaluating engineering judgment — reliability thinking, privacy boundaries, failure handling,
knowing when *not* to use an LLM. This is a proof project before it is a product, and the
design artifact (this spec + [[architecture]] + the architecture diagram) already serves that
purpose without any code being written.

**Target persona if the project is ever extended toward real users:**

- Privacy-conscious individuals and households who refuse to use credential-based aggregators.
- People preparing a **mortgage or loan application** who need a clean, credible, consolidated
  picture of income and spending.
- **Freelancers / sole proprietors** separating business from personal spending across mixed-use
  accounts.
- Anyone doing a deliberate **annual financial review** and wanting the raw work done for them.

These are hypotheses. None are validated. See §6.

---

## 3. MVP features

Two tiers. Both are documented here; only the first is near-term buildable.

### 3a. Thin vertical slice — the near-term build

Deliberately minimal, to prove the trusted-data core without drowning in parser variety.

#### In scope

- One bank, one account type.
- **Native PDF text extraction only** (no OCR).
- Canonical `Statement` + `Transaction` schema (see §4).
- Account identity resolution (stable internal `account_id`, never the full account number).
- **Financial reconciliation validation** with a defined tolerance
  (±$0.01 `VALID` / ±$1.00 `WARNING` / beyond `FAILED`).
- Structural + per-transaction validation checks.
- Traceability fields (`source_statement_id`, `source_page`, `parser_version`).
- **CSV export** of the normalized ledger.
- CLI: `analyze ./statements`.
- Tests against committed **synthetic** fixture statements.

#### Out of scope for the slice

OCR · background queue / workers / batch coordinator · multi-bank parsers · deduplication ·
merchant normalization · categorization · any LLM · dashboard · web UI · privacy gateway.

The honest claim it earns: *"I designed the full system — here is the document and
diagram — and built the trusted-data core: extraction, normalization, and financial
reconciliation with traceability."*

### 3b. Full MVP — design target, not built now

- Multi-bank support via **independently versioned parsers** (`chase_checking_v1`, …).
- **OCR fallback** (native text first; OCR only when embedded text is unusable).
- **Background processing:** job queue, worker pool, retry handling (max 3 attempts),
  **batch coordinator** tracking per-job state and gating aggregation.
- **Deduplication:** statement-level then transaction-level, conservative
  (auto-collapse only on HIGH confidence; ambiguous matches kept + flagged).
- **Merchant normalization** before categorization.
- **Categorization:** rule-based first, local-LLM fallback for unknowns, degrading to
  `Uncategorized` rather than guessing. User corrections override and feed future runs.
- **Deterministic analytics engine:** cash flow, spending breakdown, recurring charges
  (interval + variable-amount aware), merchant totals, monthly trends, account summaries.
- **Privacy gateway:** mandatory sanitizer + task-specific payload builder in front of every
  model call.
- **Local LLM explanations** of the computed numbers (never replacing them).
- **Outputs:** interactive dashboard, financial summary report, CSV/JSON export, and a
  **coverage + data-quality summary shown before the numbers**.
- **Cleanup:** raw PDFs deleted after processing unless the user opts to keep them;
  provenance metadata retained.

---

## 4. What the data looks like

### Two storage responsibilities (kept separate on purpose)

| | Temporary File Storage | Application Data Store |
|---|---|---|
| Holds | Raw PDF statements | Normalized, non-raw system data |
| Lifetime | Only while processing needs it | Persistent |
| Sensitivity | Highest in the system | Lower — no account numbers, no raw PDF text |
| After processing | **Deleted** (unless user keeps) | Retained; powers reports |

### Canonical schema

**`Statement`** — `statement_id`, `batch_id`, `account_id`, `bank`, `account_type`,
`account_identifier_masked`, `statement_start_date`, `statement_end_date`, `opening_balance`,
`closing_balance`, `currency`, `parser_version`, `extraction_status`.

**`Transaction`** — `transaction_id`, `statement_id`, `account_id`, `transaction_date`,
`posted_date?`, `description_raw`, `description_normalized`, `merchant_normalized`, `amount`
(always positive), `direction` (`DEBIT` / `CREDIT`), `balance_after?`, `category?`,
`category_source`, `category_confidence`, `source_bank`, `source_statement_type`,
`extraction_confidence?`, `source_page`.

**Supporting objects** — `Batch` (selected / uploaded / upload_failed / processed /
processing_failed counts + status), `Account` (bank + type + masked digits → stable id),
`ValidationResult` (status + per-level results + `reconciliation_delta` + findings),
`AnalyticsResult` (cash flow, spending breakdown, recurring, merchant totals, trends, coverage).

### Hierarchy and rules

- `Batch → Statement → Transaction`. `Account` groups statements across time.
- `description_raw` is **never overwritten** — needed for debugging and parser improvement.
- `extraction_confidence` is **nullable**: the native text path has no confidence source
  (`pdfplumber` / `pypdf` do not emit one); only OCR populates it.
- `extraction_confidence` ("were the fields read correctly?") is separate from
  `validation_status` ("do the numbers make sense?").
- Provenance (`source_statement_id`, `source_page`, `parser_version`) is retained even after
  the raw PDF is deleted.

Full field-level ER diagram: [[architecture#5 Data model]].

---

## 5. Tech stack

| Layer | Choice | Rationale |
|---|---|---|
| Language | **Python** | Strongest PDF/text + data ecosystem; my active learning track. |
| Native PDF text | **pdfplumber** (layout-aware), `pypdf` fallback | Bank statements are table-heavy; layout matters. |
| Slice storage | **SQLite** (stdlib `sqlite3`) | Local-first, single file, zero setup. Real state model from day one. |
| CSV/JSON export | stdlib `csv` / `json` | No dependency needed. |
| Tests | **pytest** against synthetic fixtures | Fixtures must be committable → synthetic, not real. |
| Interface | **CLI first** (`analyze ./statements`) | Web UI is a later concern; the core is the value. |
| OCR *(full MVP)* | **ocrmypdf / Tesseract**, fallback only | OCR is slower and more error-prone than embedded text. |
| Queue *(full MVP)* | **DB-backed job table + simple worker loop** | Not Redis/Celery for v1 — the design proves the understanding; the implementation stays minimal. |
| Local LLM *(full MVP)* | **Ollama** (Llama 3.x / Mistral) behind the Privacy Gateway | Strong privacy story; swappable for a hosted API without moving the boundary. |
| Analytics *(full MVP)* | pure Python / pandas | Deterministic math owns the numbers. |
| Web / dashboard *(full MVP)* | **FastAPI + server-rendered templates** (Streamlit as the fast-dashboard alternative) | Simple, deployable; demo runs on synthetic statements. |

**Architectural constant across all of it:** *model location is not the privacy control —
sanitization is.* If the LLM later moves from Ollama to a hosted API, the Privacy Gateway
still holds.

---

## 6. How the app makes money

**Current answer: it doesn't, and that's fine.** The purpose is portfolio proof and personal
use. Per the brain's rules, it does not become a business priority without evidence that it
deserves one.

**Monetization hypotheses (documented, not chosen, not validated):**

- **One-time desktop-app purchase** — leans on the privacy angle: "your financial data never
  leaves your machine."
- **Freemium** — local processing free; a hosted convenience tier (sync, sharing, storage)
  paid.
- **Paid "loan-ready financial summary" export** — a clean, credible per-report artifact for
  people in a mortgage/loan process.
- **B2B2C via bookkeepers and financial coaches** — professionals who need clean, normalized
  client transaction data and currently do it by hand.

**Strategic value even if it never earns directly:** PDF extraction + reconciliation +
normalization is a **reusable capability**. Document-extraction and expense-reconciliation
work is exactly the kind of expensive, frustrating bottleneck BranchBeacon is looking for in
small businesses. This project de-risks that offer.

**Recommendation:** revisit monetization only after the slice ships and has been dogfooded on
real statements. Not before.

---

## 7. How the app should look and feel

### Principles

- **Trust-first.** The coverage + data-quality summary is shown *before* any totals. The user
  learns how complete and reliable the analysis is before they read a single number.
- **Auditable.** Every figure is clickable to its source: account, statement, page, parser
  version. Even after the raw PDF is deleted, the provenance trail remains.
- **Honest about uncertainty.** Explicit `VALID` / `WARNING` / `FAILED` per statement and
  `COMPLETED_WITH_WARNINGS` per batch. Excluded statements are listed, not buried in logs.
  No false precision.
- **The AI never replaces the numbers.** If the explanation says "transportation spending rose
  sharply," the metric (`$2,140 → $2,890, +35%`) sits right next to it.
- **Plain language.** No jargon where a normal word works.
- **No dark patterns.** This is a tool that tells you the truth about your money, not an app
  optimizing engagement.

### Visual direction

A quiet, neutral **ledger tool** — closer to a well-made accounting utility than a gamified
budgeting app. Generous whitespace, restrained color (reserved for status: green/amber/red),
**monospaced numerals** so columns align and figures are easy to scan. Light and dark themes.
Data-dense but calm.

---

## 8. Staged implementation plan — thin vertical slice

**Gated behind P2 shipping.** Documented now so it is ready to execute later; this section
does not start any work.

### Step 0 — Repo hygiene (before any statement touches the tree)

- `git init`; in the **first commit**, add `.gitignore` covering `data/`, `*.pdf`, and any
  local statement directory.
- Keep real statements **outside the repo tree** entirely during development.
- One misconfigured ignore rule in a public repo is a real financial-data leak — this step is
  not optional and not deferrable.

### Step 1 — Module layout

```text
bank_statement_analyzer/
  extract/      native PDF text extraction (pdfplumber → pypdf fallback)
  detect/       identify the one supported bank + account type + layout version
  parse/        one versioned parser → raw statement + transactions
  canonical/    Statement / Transaction / Account dataclasses + schema
  accounts/     account identity resolution (masked digits → stable account_id)
  validate/     structural + per-transaction + reconciliation checks
  store/        SQLite persistence (stdlib sqlite3)
  export/       CSV writer
  cli.py        `analyze ./statements`
```

Data flows strictly left to right. `parse/` output is never consumed downstream — only
`canonical/` output is.

### Step 2 — Reconciliation validation (the point of the slice)

- Implement all three levels: structural, per-transaction, financial reconciliation.
- Tolerance bands: `VALID` ≤ ±$0.01, `WARNING` ≤ ±$1.00, `FAILED` beyond.
- `reconciliation_delta` is always recorded, even on `VALID`.
- A statement that fails validation is flagged and excluded from any aggregate output — it
  does not silently contribute numbers.

### Step 3 — Synthetic statement generator

- Build a generator that produces PDF statements matching the **real layout** of the target
  bank, with known-correct totals.
- Required because real statements cannot be committed — without this there are **no
  regression tests**.
- Risk to manage: writing the generator *after* the parser can produce a generator that only
  emits what the parser already handles, proving nothing. Mitigation: derive the generator's
  layout from a real statement's structure, not from the parser's assumptions, and include
  deliberately malformed cases (missing fee line, transposed digits) that the parser should
  catch.

### Step 4 — Tests

- `pytest`. Fixtures = synthetic statements committed to the repo.
- Golden canonical output per fixture.
- Reconciliation cases: clean pass, rounding-noise warning, missed-transaction failure,
  transposed-digit failure.

### Step 5 — CSV export + CLI

- `analyze ./statements` → runs extract → detect → parse → normalize → resolve account →
  validate → persist → export.
- Output: `ledger.csv` + a validation/coverage summary printed to stdout.

### Verification (end-to-end)

1. Run `analyze` against a folder of synthetic statements with known totals.
2. Confirm `ledger.csv` transaction sum reconciles to the statement totals within tolerance.
3. Confirm a deliberately corrupted fixture produces `FAILED` and is excluded from the summary.
4. Confirm every row in `ledger.csv` carries `source_statement_id`, `source_page`,
   `parser_version`.
5. `pytest` green.

---

## 9. Bonus feature (vNext) — household / partner overview

### The idea

Invite a partner (spouse, boyfriend/girlfriend, etc.) to contribute their statements so the
two of you get a **joint household view**: combined cash flow, combined spending, a
shared-vs-individual breakdown, household recurring charges, and — for the mortgage-prep
persona especially — a household income picture a lender would recognize.

### Why it is gated, not in the MVP

This is the feature that changes the project's nature. Everything above is a single-user,
local-first, "your data never leaves your machine" tool. A joint view means one person's
financial data reaches another person, and possibly another device or a server — a direct
tension with the core thesis. It does not start until the single-user core ships, is
dogfooded, and there is a concrete reason to build it. **No evidence yet says it is needed;
this section exists to capture the thinking, not to authorize work.**

### How it could work — three options

#### Option A — Sanitized bundle exchange (recommended)

Each partner runs their own local instance. Either can export a **household-share bundle** —
not raw statements, not the full ledger, but the sanitized, PII-stripped, per-party data a
joint view needs (merchant-normalized descriptions, amounts, categories, account labels,
provenance IDs; transaction- vs. monthly-aggregate granularity is an open decision). The
other person imports it; the joint view is a separate read-only overlay computed from both
parties' data. Revoke by deleting the imported bundle; bundles can carry an expiry.

- **Pro:** no server, no shared account, no credentials, no auth system to build. Each person
  controls exactly what they share and keeps their raw data. Consent is an explicit act — you
  export and hand over a file. It is a purpose-built extension of the CSV export that already
  exists in the slice.
- **Con:** manual (send a file), not live; re-share when new statements are added. Once the
  other party has the bundle, they have that data — same as sharing a spreadsheet.

#### Option B — One host, partner contributes

Kervintz's instance is the host. The partner uploads their statements to it through an invite
(a LAN service or a hosted relay); it processes them through the same pipeline; the joint
view lives on the host machine. The partner's raw statements are deleted after processing
(existing cleanup rule).

- **Pro:** closer to the "invite" UX; one always-current joint view; reuses the whole pipeline.
- **Con:** the partner's normalized financial history now lives on Kervintz's machine —
  asymmetric (he holds and controls everything). Needs a real invite/auth mechanism, which
  local-first otherwise avoids. Ugly at relationship end.

#### Option C — Shared hosted household workspace

Both upload to a hosted multi-user workspace. This is the "real product" version and the
natural **paid tier** (monetization hypothesis #2 in §6).

- **Pro:** best UX, live, cross-location.
- **Con:** fully abandons local-first for this feature — two complete financial histories on a
  server. Only sane if the project deliberately becomes a hosted product with a serious
  security posture (per-user encryption, deletion guarantees, legal review). That is a pivot
  decision, not a bonus feature.

**Recommendation:** Option A. It is the only one that keeps the privacy thesis intact, it is
a small extension of the existing canonical schema + export, and it has nothing to run and
nothing to secure server-side. Option B is the fallback if a single live view matters more
than symmetry. Option C only if the project pivots to hosted.

### What the joint view shows

- **Per-party attribution always.** Accounts and transactions keep their owner
  ("Partner A · Checking"); the two ledgers are never merged into one owned dataset.
- **Household cash flow** — combined income, spending, net — with **inter-party transfers
  netted out** (a transfer from A to B, or into a joint account, is internal movement, not
  household income or spending).
- **Shared vs. individual** — accounts tagged "joint" are analyzed separately from each
  person's individual accounts.
- **Household category breakdown, recurring charges** (deduped across parties — one Netflix,
  not two), **top merchants**.
- **Contribution view** — who covered what share of shared expenses.
- **Coverage per party** — "Partner A: 24/24 months · Partner B: 18/24 months"; the joint
  analysis is only as complete as the thinner side, and says so.
- Drill-down to a source statement works only for your own documents.

### New invariants this introduces

- The joint view is read-only and derived; it never merges the two ledgers into one owned dataset.
- Every account and transaction in the joint view stays attributed to the party that owns it.
- Sharing is an explicit, revocable action; revoking removes the other party's ongoing
  access. What was already imported cannot be un-copied — the UI must say so at share time.
- The shared bundle is sanitized to the household-view minimum — never the raw ledger, never
  raw statements.
- Household cash-flow analytics net out inter-party transfers.
- Household coverage is reported per party; the joint view is only as complete as the
  least-covered party.
- No shared credentials or shared account (Options A and B).

### Risks

- **Relationship end.** Shared data is already copied; "revoke + delete" cannot claw back an
  imported bundle. Be explicit at share time.
- **Coercion.** A "show me all your finances" feature can be misused in a controlling
  relationship. Sharing must always be opt-in, granular, and revocable — never a precondition
  to using the tool. The per-instance, deliberate-share design is the mitigation.
- **Scope.** This turns a single-user tool into multi-user software with sharing, consent,
  and expiry. Keep it a clearly-marked bonus that follows a working, used core.
- **Categorization conflicts.** The same merchant categorized differently by each party — the
  joint view needs a rule (show both / flag, do not silently pick one).

### Open decisions

1. Bundle granularity — per-transaction (richer joint view, more data shared) vs.
   monthly-aggregate (less exposure, weaker drill-down).
2. Whether "joint account" tagging is manual or inferred from both parties reporting the same
   masked account.
3. Option A vs. B — only decide when the feature is actually on the table.

---

## 10. Related

- [[architecture]] — diagrams, invariant catalog, state enums, data model.
- [[Design-Review-and-Scope]] — the scope decision and sequencing (authoritative).
- `resources/Design Architecture Diagrams.pdf` — the original 79-page design session.
- Interactive architecture diagram (HTML artifact): <https://claude.ai/code/artifact/dded2d38-66f4-4dc9-b355-e880c15cd392>
- `architecture-diagram.html` — the artifact source, in this folder.
