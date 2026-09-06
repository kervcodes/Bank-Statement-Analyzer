"""Background job queue and worker pool (REQ-PROC-001 through 103, techstack.md §6).

SQLite-backed job table + an in-process worker, no external broker. Split into:

- queue.py       -- create/claim/transition statement_job rows (pure DB)
- processor.py   -- run one job through the extraction pipeline, classify outcome
- coordinator.py -- flip a batch to a terminal status once all its jobs finish
- pool.py        -- the background thread that drives it, wired into FastAPI lifespan
"""
