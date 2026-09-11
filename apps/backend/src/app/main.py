from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.accounts import router as accounts_router
from app.api.analytics import router as analytics_router
from app.api.batches import router as batches_router
from app.api.category_rules import router as category_rules_router
from app.api.review import router as review_router
from app.api.settings import router as settings_router
from app.api.transactions import router as transactions_router
from app.db import get_session
from app.workers.coordinator import refresh_batch
from app.workers.pool import BackgroundWorker
from app.workers.queue import reclaim_processing_jobs

# Started on app startup, stopped on shutdown. Bare TestClient(app) does not
# trigger lifespan events, so the suite runs with the worker off and drives it
# explicitly via run_worker_once().
worker = BackgroundWorker()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # No worker has run yet, so any job still PROCESSING was orphaned by a
    # previous crash or restart -- reclaim all of them before starting.
    with get_session() as session:
        for reclaimed_batch_id in set(reclaim_processing_jobs(session)):
            refresh_batch(session, reclaimed_batch_id)
    worker.start()
    try:
        yield
    finally:
        worker.stop()


app = FastAPI(lifespan=lifespan)
app.include_router(batches_router)
app.include_router(review_router)
app.include_router(analytics_router)
app.include_router(transactions_router)
app.include_router(category_rules_router)
app.include_router(accounts_router)
app.include_router(settings_router)

# Single-user local desktop app: the renderer (Vite dev server or a packaged
# file:// origin) is always cross-origin from this sidecar on 127.0.0.1, and
# nothing outside this machine can reach it, so an open CORS policy here
# doesn't widen the app's actual attack surface.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
