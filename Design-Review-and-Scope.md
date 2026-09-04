# Bank Statement Analyzer — Design Review & Scope Decision

**Reviewed:** 2026-08-30
**Source:** `resources/Design Architecture Diagrams.pdf` (79pp ChatGPT design session)
**Status:** Design complete. **Not started.** Queued behind P2.
**Related:** [[03 Projects/courses-projects/Agentic-Course-Study-Plan.md]]

---

## Decision (2026-08-30)

- **Sequence:** P2 (BranchBeacon prospect agent, Section 2) **first**, then the analyzer slice. Sequential, not parallel.
- **Scope when built:** **thin vertical slice** — one bank, native text only, no OCR, no queue,
  no LLM. Canonical schema + reconciliation validation + traceability + CSV export. 1–2 weeks.
- **Test data:** develop against own real statements; generate synthetic statements when ready to demo.

This overrides the CLAUDE.md line that the analyzer is "not receiving execution time yet" —
**deliberately and with a date**, which is what that line asked for. It is now queued work,
not an active project, and it does not start until P2 ships.

---

## What the design gets right (verified against the PDF)

- **Upload failure ≠ validation failure**; one bad file does not kill the batch.
- **Canonical schema boundary** — bank-specific world → canonical → bank-independent world.
- **`extraction_confidence` separated from `validation_status`** — "the parser was confident and
  still produced financially impossible data." Sharpest idea in the document.
- **Reconciliation as the trust gate**: `opening + credits − debits ≈ closing`.
- **Conservative dedup** — missing a duplicate beats deleting a real $500 transaction.
- **"Model location is not the privacy control; sanitization is the privacy control."**
- **Traceability survives raw-file deletion** (source_statement_id, source_page, parser_version).
- **Deterministic analytics own the numbers; the LLM only explains them.**

This is interview-ready **as a design artifact today**, without building anything.

---

## Open design gaps (not addressed in 79 pages)

| # | Gap | Why it matters |
|---|-----|----------------|
| 1 | **Test/demo data strategy** — never mentioned. | Decided 2026-08-30: own statements for dev, synthetic for demo. **Risks below.** |
| 2 | **`extraction_confidence` has no source on the native path.** OCR engines emit confidence; `pypdf` does not. | The schema consumes a field that may not exist. Define how it's computed or make it nullable and say so. |
| 3 | **The `≈` reconciliation tolerance is undefined.** | This single constant sets the false-positive rate on the strongest check. Pick ±$0.01 or ±0.5% and justify it. |
| 4 | **Queue + worker pool + batch coordinator is unjustified for v1.** | Zero users. Design it (done, and it's good interview material); implement the simplest thing honoring the boundaries. |
| 5 | **Versioned per-bank parsers don't scale for one person.** 5 banks × types × versions ≈ 10–15 parsers. | Parsers #3+ teach nothing new and eat all the time. Slice scope exists to avoid this. |
| 6 | **Local LLM vs. live demo.** Local-first privacy story = no URL for a recruiter. | Unresolved. Slice has no LLM, so deferred. |

### Risk on the chosen test-data path

Developing against personal statements then generating synthetics later means:
- **Fixtures cannot be committed**, so there are no regression tests until the generator exists.
- The **generator must reproduce a layout the parser already assumes** — writing it after the
  parser risks a generator that only emits what the parser already handles, proving nothing.
- **One misconfigured `.gitignore` is a real financial-data leak** in a public repo.

Mitigation: `.gitignore` the data directory **in the first commit, before any statement is
placed in the repo**, and keep real files outside the repo tree entirely if possible.

---

## Thin vertical slice — target scope

**In:** one bank, one account type. Native PDF text extraction only. Canonical Statement +
Transaction schema. Account identity resolution. Financial reconciliation validation with a
defined tolerance. Traceability fields. CSV export. Tests against fixtures.

**Out:** OCR, queue/workers/batch coordinator, multi-bank parsers, dedup, merchant
normalization, categorization, LLM of any kind, dashboard, privacy gateway.

**Honest claim it earns:** *"I designed the full system — here is the document — and built the
trusted-data core: extraction, normalization, and financial reconciliation with traceability."*
