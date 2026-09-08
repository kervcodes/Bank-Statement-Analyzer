from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.batches import router as batches_router
from app.workers.pool import BackgroundWorker

# Started on app startup, stopped on shutdown. Bare TestClient(app) does not
# trigger lifespan events, so the suite runs with the worker off and drives it
# explicitly via run_worker_once().
worker = BackgroundWorker()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    worker.start()
    try:
        yield
    finally:
        worker.stop()


app = FastAPI(lifespan=lifespan)
app.include_router(batches_router)

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
