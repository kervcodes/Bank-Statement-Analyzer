# Local real statements — never committed

Drop your **real Santander checking PDF statements** in this folder.

`*.pdf` is already gitignored repo-wide (see the root `.gitignore`), so nothing here except
this README and `.gitkeep` is ever tracked by git. Real financial data does not leave your
machine.

## What to put here

- 3+ months of real Santander checking statements, named however you like
  (e.g. `2026-06.pdf`, `2026-07.pdf`, `2026-08.pdf`).
- If you have one statement you *know* does not reconcile (a missed transaction, a correction),
  include it — it exercises the reconciliation-`FAILED` path directly.

## How they're used

- `tests/test_santander_local_golden.py` parametrizes over `*.pdf` in this folder and parses
  each one. It is **skipped** when the folder is empty, so CI (which never sees these files)
  stays green.
- The committed synthetic fixture (`tests/fixtures/statements/santander_checking_v1.py`) is
  built to mirror the layout of these real statements, so CI has something representative to
  run without any real data.
