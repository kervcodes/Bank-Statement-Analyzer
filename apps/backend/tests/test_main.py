from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

import app.main as main_module
from app.main import app
from app.models import StatementJob
from app.workers.queue import claim_next_job


def test_health_check():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_lifespan_reclaims_orphaned_jobs_before_starting_the_worker(
    session: Session,
    session_factory: Callable[[], Session],
    queued_job: StatementJob,
    monkeypatch: pytest.MonkeyPatch,
):
    """A job left PROCESSING by a prior crash/restart must be reclaimed before
    the worker starts -- otherwise it's excluded from CLAIMABLE_JOB_STATUSES
    and never picked up again.

    `get_session` and the worker's start/stop are stubbed so this exercises
    the lifespan wiring without touching the real app database or starting the
    real background thread.
    """
    claim_next_job(session)  # -> PROCESSING, as if orphaned by a crash

    monkeypatch.setattr(main_module, "get_session", session_factory)
    monkeypatch.setattr(main_module.worker, "start", lambda: None)
    monkeypatch.setattr(main_module.worker, "stop", lambda: None)

    with TestClient(main_module.app):
        pass  # lifespan startup runs on context enter

    session.expire_all()
    job = session.get(StatementJob, queued_job.id)
    assert job.status == "RETRYING"
    assert job.attempt_count == 1
