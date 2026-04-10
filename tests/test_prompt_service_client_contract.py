from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from services.query_generator_service.app.clients import PromptServiceClient


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, text: str = "") -> None:
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeAsyncClient:
    last_request: Optional[Dict[str, Any]] = None

    def __init__(self, *, timeout: float) -> None:
        self.timeout = timeout

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def post(self, url: str, *, json: Dict[str, Any]) -> _FakeResponse:
        type(self).last_request = {"url": url, "json": json}
        return _FakeResponse(text="PROMPT_FROM_KNOWLEDGE_OPS")


@pytest.mark.asyncio
async def test_prompt_service_client_uses_prompt_package_contract(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    client = PromptServiceClient(base_url="http://127.0.0.1:8003", timeout_seconds=3.0)

    prompt = await client.fetch_prompt(id="qa-001", question="查询网络设备名称")

    assert prompt == "PROMPT_FROM_KNOWLEDGE_OPS"
    assert _FakeAsyncClient.last_request == {
        "url": "http://127.0.0.1:8003/api/knowledge/rag/prompt-package",
        "json": {"id": "qa-001", "question": "查询网络设备名称"},
    }
