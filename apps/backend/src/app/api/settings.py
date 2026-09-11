"""REQ-SET-001: test an LLM API key before it's saved.

Stateless -- persistence lives entirely in Electron (`safeStorage`, never the
SQLite DB or this backend). The actual provider call goes through
`app.services.llm_gateway` (the one module allowed to import `app.llm` --
enforced by `tests/test_llm_gateway.py`), which never logs or persists the key
(REQ-CLEAN-003).
"""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.llm_gateway import test_provider_key

router = APIRouter(prefix="/settings", tags=["settings"])


class TestLlmKeyRequest(BaseModel):
    provider: Literal["anthropic", "openai"]
    api_key: str
    model: str | None = None


class TestLlmKeyResponse(BaseModel):
    ok: bool
    error: str | None = None


@router.post("/test-llm-key", response_model=TestLlmKeyResponse)
def test_llm_key(body: TestLlmKeyRequest) -> TestLlmKeyResponse:
    if not body.api_key.strip():
        raise HTTPException(status_code=422, detail="api_key is required")

    error = test_provider_key(body.provider, body.api_key, body.model)
    return TestLlmKeyResponse(ok=error is None, error=error)
