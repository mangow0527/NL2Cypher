from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from services.cypher_generator_agent.app.clients import KnowledgeAgentClient, TestingAgentClient
from services.cypher_generator_agent.app.models import GeneratedCypherSubmissionRequest, PreflightCheck


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, text: str = "", headers: Optional[Dict[str, str]] = None) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> Dict[str, Any]:
        raise RuntimeError("json() should not be used for knowledge-agent context contract")


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
        return _FakeResponse(
            text="KNOWLEDGE_AGENT_CONTEXT",
            headers={"content-type": "text/plain; charset=utf-8"},
        )


@pytest.mark.asyncio
async def test_knowledge_agent_client_uses_context_contract(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    client = KnowledgeAgentClient(base_url="http://127.0.0.1:8010", timeout_seconds=3.0)

    context = await client.fetch_context(id="qa-001", question="查询网络设备名称")

    assert context == "KNOWLEDGE_AGENT_CONTEXT"
    assert _FakeAsyncClient.last_request == {
        "url": "http://127.0.0.1:8010/api/knowledge/rag/prompt-package",
        "json": {"id": "qa-001", "question": "查询网络设备名称"},
    }


class _JsonContextResponse(_FakeResponse):
    def __init__(self) -> None:
        super().__init__(
            text='{"context":"KNOWLEDGE_AGENT_CONTEXT"}',
            headers={"content-type": "application/json"},
        )

    def json(self) -> Dict[str, Any]:
        return {"context": "KNOWLEDGE_AGENT_CONTEXT"}


class _JsonContextAsyncClient(_FakeAsyncClient):
    async def post(self, url: str, *, json: Dict[str, Any]) -> _FakeResponse:
        type(self).last_request = {"url": url, "json": json}
        return _JsonContextResponse()


@pytest.mark.asyncio
async def test_knowledge_agent_client_rejects_json_context_response(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _JsonContextAsyncClient)

    client = KnowledgeAgentClient(base_url="http://127.0.0.1:8010", timeout_seconds=3.0)

    with pytest.raises(ValueError, match="knowledge-agent context contract violation"):
        await client.fetch_context(id="qa-001", question="查询网络设备名称")


class _TextAckResponse(_FakeResponse):
    def __init__(self) -> None:
        super().__init__(
            text="accepted",
            headers={"content-type": "text/plain; charset=utf-8"},
        )
        self.content = b"accepted"

    def json(self) -> Dict[str, Any]:
        raise RuntimeError("cypher-generator-agent should not parse testing-agent ack body")


class _TextAckAsyncClient(_FakeAsyncClient):
    async def post(self, url: str, *, json: Dict[str, Any]) -> _FakeResponse:
        type(self).last_request = {"url": url, "json": json}
        return _TextAckResponse()


@pytest.mark.asyncio
async def test_testing_agent_client_treats_success_status_as_success_without_parsing_body(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _TextAckAsyncClient)

    client = TestingAgentClient(base_url="http://127.0.0.1:8003", timeout_seconds=3.0)
    payload = GeneratedCypherSubmissionRequest(
        id="qa-001",
        question="查询协议版本",
        generation_run_id="cypher-run-001",
        generated_cypher="MATCH (p:Protocol) RETURN p.version",
        parse_summary="direct_cypher",
        preflight_check=PreflightCheck(accepted=True),
        raw_output_snapshot="MATCH (p:Protocol) RETURN p.version",
        input_prompt_snapshot="prompt",
    )

    result = await client.submit(payload)

    assert result == {}
    assert _TextAckAsyncClient.last_request == {
        "url": "http://127.0.0.1:8003/api/v1/evaluations/submissions",
        "json": payload.model_dump(),
    }
