"""REQ-SET-001: POST /settings/test-llm-key. Stateless -- no DB, no persistence."""

import pytest
from fastapi.testclient import TestClient

import app.api.settings as settings_module
from app.main import app

client = TestClient(app)


def test_ok_when_the_provider_call_succeeds(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings_module, "test_provider_key", lambda *a, **k: None)

    response = client.post(
        "/settings/test-llm-key",
        json={"provider": "anthropic", "api_key": "sk-ant-fake"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "error": None}


def test_reports_the_failure_when_the_provider_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        settings_module,
        "test_provider_key",
        lambda *a, **k: "openai: HTTPStatusError",
    )

    response = client.post(
        "/settings/test-llm-key",
        json={"provider": "openai", "api_key": "sk-bad-key"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"] == "openai: HTTPStatusError"


def test_blank_api_key_is_rejected():
    response = client.post(
        "/settings/test-llm-key", json={"provider": "anthropic", "api_key": "  "}
    )
    assert response.status_code == 422


def test_unknown_provider_is_rejected():
    response = client.post(
        "/settings/test-llm-key", json={"provider": "gemini", "api_key": "x"}
    )
    assert response.status_code == 422


def test_response_never_echoes_the_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings_module, "test_provider_key", lambda *a, **k: None)
    response = client.post(
        "/settings/test-llm-key",
        json={"provider": "anthropic", "api_key": "sk-ant-super-secret"},
    )
    assert "sk-ant-super-secret" not in response.text
