# Todo: Build-plan #4 — Extraction pipeline

Source: `build-plan.md` §4, tracing to `requirements.md` §4 (REQ-EXT-001 through 004).

Branch: `feature/extraction-pipeline`, based on `main` (currently `1409beb`, which includes
build-plan #3).

## What already exists vs. what this task adds

- Nothing extraction-related exists yet. `IntakeFile.temp_path` (build-plan #3) points at an
  accepted PDF on disk — this task reads that path and produces text, nothing more.
- Explicitly **not** wiring into the job queue (`statement_jobs` doesn't exist until build-plan
  #5) or into bank detection/parsing (build-plan #6). This is a standalone service: PDF path in,
  extracted text out (or a raised failure).

## System check (done before writing this plan)

- **Poppler** (`pdftoppm`, needed by `pdf2image`): already installed, v24.04.0, on PATH.
- **Tesseract OCR** (needed by `pytesseract`): **not installed** anywhere on this machine.
  `pytesseract` calls out to the `tesseract` binary; without it, any OCR-path call raises
  `TesseractNotFoundError` immediately.

## Three things to confirm before writing code

**1. Installing Tesseract now.** `winget search tesseract` shows two real candidates:
   - **`tesseract-ocr.tesseract` (v5.5.3, official upstream project)** — **Recommended**, this
     is the actively-maintained upstream package.
   - `UB-Mannheim.TesseractOCR` (v5.4.0, community Windows build) — the version most Windows
     install guides point to; also fine, slightly older.

   Either way I'd run `winget install <id>` and then confirm `tesseract --version` resolves in
   a fresh shell (PATH changes need a new terminal). Tell me which one, or say "I'll install it
   myself" and I'll pick back up once it's on PATH.

**2. Native-vs-OCR routing threshold.** techstack.md says usable embedded text means "a
reasonable fraction of pages... with recoverable structure," not an exact number. Per-page, I'm
defining "has usable text" as ≥40 non-whitespace characters extracted by `pdfplumber` (a truly
scanned/blank page yields ~0; even a sparse real page clears this easily). At the document
level:
   - **(a) All pages must pass, or the whole document goes to OCR.** **Recommended** — real
     bank statements are essentially never a mix of native and scanned pages, and silently
     dropping one page's transactions because only that page failed the native-text check is
     exactly the kind of quiet inaccuracy this app is built to avoid (REQ-NORM-004/REQ-VAL-001
     both lean on every page being accounted for).
   - (b) ≥80% of pages must pass, rest OK to lose — closer to techstack.md's literal "reasonable
     fraction" wording, but means a genuinely mixed document silently loses some pages' content
     to whichever method runs.

   Going with **(a)** unless you say otherwise.

**3. CI needs both binaries too.** `.github/workflows/ci.yml` runs on `ubuntu-latest` with
neither Poppler nor Tesseract installed. Adding an `apt-get install -y poppler-utils
tesseract-ocr` step so the OCR-path test actually runs in CI, not just locally. This isn't
really optional — without it the new tests either fail in CI or have to be skipped there, which
defeats having them.

## 1. Dependencies

- [x] `pdfplumber` — native embedded-text extraction (already the plan's chosen library,
      techstack.md §7; permissively licensed, unlike `PyMuPDF`)
- [x] `pdf2image` — renders PDF pages to images for the OCR fallback (needs Poppler, already
      present)
- [x] `pytesseract` — OCR engine wrapper (needs the Tesseract binary, decision 1 above)
- [x] `Pillow` as a **dev** dependency — used only in tests to build a synthetic "scanned"
      (image-only, no text layer) PDF fixture; already an indirect dependency via `pdf2image`
      but declaring it directly since tests import it by name

## 2. Extraction contract (REQ-EXT-003)

- [x] `app/services/extraction.py` (matches `services/intake_validation.py`'s precedent —
      "standalone service", not a new top-level package):
      ```python
      @dataclass(frozen=True)
      class PageText:
          page_number: int  # 1-indexed
          text: str

      @dataclass(frozen=True)
      class ExtractionResult:
          pages: list[PageText]
          method: str  # "NATIVE" or "OCR"

      class ExtractionFailedError(Exception):
          """REQ-EXT-004: OCR failed; never return partial/garbled text instead."""

      def extract_text(pdf_path: Path) -> ExtractionResult: ...
      ```
- [x] `source_page` traceability (REQ-NORM-004, needed by build-plan #6's parsers) is why the
      contract is per-page, not one flat string

## 3. Native-text detection and extraction

- [x] Open with `pdfplumber`, extract each page's text
- [x] Per-page usable-text check: ≥40 non-whitespace characters (decision 2)
- [x] All pages pass → return `ExtractionResult(pages=..., method="NATIVE")` immediately, skip
      OCR entirely (REQ-EXT-002: native attempted first, OCR only as fallback)

## 4. OCR fallback

- [x] Any page fails the native check → re-render the *whole document* via `pdf2image` and run
      `pytesseract` on every page (decision 2a: don't mix methods within one document)
- [x] `pytesseract`/`pdf2image` errors (`TesseractNotFoundError`, a corrupt render, etc.) are
      caught and re-raised as `ExtractionFailedError` — REQ-EXT-004 requires a hard failure, not
      partial or garbled text silently passed downstream

## 5. Tests

- [x] Native-path test: a `pypdf`-generated PDF with real embedded text (following build-plan
      #3's precedent — synthetic, not a committed binary fixture) → asserts `method == "NATIVE"`
      and correct per-page text
- [x] OCR-path test: a synthetic "scanned" PDF — text drawn onto a blank image with Pillow
      (`ImageDraw`), saved as an image-only PDF page (no text layer) — asserts `method == "OCR"`
      and that the OCR'd text contains the known drawn string
- [x] `ExtractionFailedError` test: simulate an OCR failure (e.g. monkeypatch `pytesseract` to
      raise) and assert the error propagates rather than returning partial text
- [x] Keep the 90% coverage gate green

## 6. CI

- [x] `.github/workflows/ci.yml`: add `apt-get install -y poppler-utils tesseract-ocr` before
      the dependency-install step

## 7. Docs

- [x] `docs/activity.md` entry
- [x] `README.md` status section

## Review

**What was completed:** the extraction pipeline from build-plan #4 / REQ-EXT-001–004.
`app/services/extraction.py` exposes `extract_text(pdf_path) -> ExtractionResult`: native text
via `pdfplumber` first, whole-document OCR fallback via `pdf2image` + `pytesseract` when any
page lacks usable embedded text, both converging on the same `ExtractionResult`
(`pages: list[PageText]`, `method`) contract. Not wired into the job queue or bank detection —
exactly as scoped.

**All three confirmed decisions implemented as agreed:** Tesseract installed via
`tesseract-ocr.tesseract` (winget, v5.5.3); all-pages-must-pass routing (one bad page sends the
whole document to OCR, never a per-page split); CI now installs both `poppler-utils` and
`tesseract-ocr` on the Ubuntu runner.

**Deviation from the plan, found while implementing:** the plan's tests section assumed a
`pypdf`-generated native-text fixture, but `pypdf` turned out to have no text-drawing API (it's
built for manipulating existing PDFs, not authoring content from scratch). Rather than add a new
dependency (e.g. `reportlab`) just for a test fixture, wrote a small hand-built PDF constructor
(object graph + xref table) directly in the test file — no new dependency, and it doubles as the
fixture for the mixed-document routing test (one real-text page + one blank page).

**Also found:** the Tesseract winget package doesn't add itself to PATH (unlike some Windows
installers). Added `C:\Program Files\Tesseract-OCR` to the user PATH environment variable
directly so future terminals resolve `tesseract` without extra steps.

**Tests/checks run:**
- `uv run pytest` — 43 passed, 97% coverage (gate: 90%)
- `uv run ruff check .` and `uv run ruff format --check .` — both clean
- OCR path verified against the real Tesseract binary, not mocked: recovered
  "HELLO SCANNED STATEMENT" from a rendered image with no text layer
- `ExtractionFailedError` path verified with a monkeypatched OCR failure — confirms the error
  propagates rather than returning partial/garbled text (REQ-EXT-004)

**Known issues / deliberate gaps:**
- CI has not yet been observed to actually run green with the new `apt-get install` step (that
  only happens once this branch's PR opens and the `backend` check runs) — the step mirrors the
  same packages verified locally, but flagging it as unconfirmed-in-CI until the PR's check
  actually passes.
- No real bank-statement PDF fixtures — intentional, same reasoning as build-plan #3: real
  fixtures belong to build-plan #6 (first parser), this step only needed to prove the
  native/OCR contract works, not validate against actual statement layouts.
- The 40-character per-page "usable text" floor and the all-pages-must-pass routing rule are
  both judgment calls (techstack.md gives no exact numbers) — revisit if build-plan #6 turns up
  a real statement that's borderline (e.g. a mostly-native statement with one oddly-formatted
  page that trips the floor unnecessarily).

**Recommended next step:** build-plan.md #5 — background job queue (`statement_jobs` table,
worker pool, retry logic, `BatchCoordinator`), which is what will actually call
`extract_text()` and `validate_pdf()` against queued `IntakeFile` rows.
