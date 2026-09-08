"""The background worker: a daemon thread polling for claimable jobs.

techstack.md §6 specifies a ProcessPoolExecutor (OCR/parsing are CPU-bound).
Build-plan #5 deliberately uses a single sequential thread instead: the
queue/retry/coordinator machinery this step is about is identical either way,
and a process pool on Windows (spawn, pickled work functions, a DB engine per
child) makes this far harder to build and test for throughput that is not yet a
measured problem. Revisit to a process pool when OCR throughput is one -- it is
contained to this module.
"""

import logging
import threading
from collections.abc import Callable

from sqlmodel import Session

from app.db import get_session
from app.workers.processor import process_job
from app.workers.queue import claim_next_job

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 1.0

SessionFactory = Callable[[], Session]


def run_worker_once(session_factory: SessionFactory = get_session) -> bool:
    """Claim and process one job. Returns True if a job ran, False if none were
    claimable. This is the seam the tests drive -- no threads involved.
    """
    with session_factory() as session:
        job = claim_next_job(session)
        if job is None:
            return False
        process_job(session, job)
        return True


class BackgroundWorker:
    def __init__(
        self,
        session_factory: SessionFactory = get_session,
        poll_interval: float = POLL_INTERVAL_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._poll_interval = poll_interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="statement-worker", daemon=True
        )
        self._thread.start()
        logger.info("background statement worker started")

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                ran = run_worker_once(self._session_factory)
            except Exception:
                # The loop must survive a bad iteration; the failing job's own
                # state is handled in process_job, this guards against an
                # unexpected error in claim/commit itself.
                logger.exception("worker loop iteration failed")
                ran = False
            if not ran:
                self._stop.wait(self._poll_interval)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None
        logger.info("background statement worker stopped")
