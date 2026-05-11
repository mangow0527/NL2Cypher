from __future__ import annotations

import inspect
from typing import Any, Dict, Optional

import pytest

import services.cypher_generator_agent.app.clients as clients_module
from services.cypher_generator_agent.app.clients import TestingAgentClient
from services.cypher_generator_agent.app.models import CgaGenerationNonSuccessReport, GeneratedCypherSubmissionRequest


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, text: str = "", headers: Optional[Dict[str, str]] = None) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> Dict[str, Any]:
        raise RuntimeError("json() should not be used")


class _FakeAsyncClient:
    last_request: Optional[Dict[str, Any]] = None

    def __init__(self, *, timeout: float) -> None:
        self.timeout = timeout

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def post(self, url: str, *, json: Dict[str, Any]) -> _FakeResponse:
        raise NotImplementedError


def test_clients_module_no_longer_exports_knowledge_agent_client() -> None:
    assert not hasattr(clients_module, "KnowledgeAgentClient")


def test_clients_module_no_longer_contains_prompt_package_call() -> None:
    assert "prompt-package" not in inspect.getsource(clients_module)


class _JsonAckResponse(_FakeResponse):
    def __init__(self, payload: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            text='{"accepted": true}',
            headers={"content-type": "application/json"},
        )
        self.content = self.text.encode("utf-8")
        self._payload = payload or {"accepted": True}

    def json(self) -> Dict[str, Any]:
        return self._payload


class _JsonAckAsyncClient(_FakeAsyncClient):
    async def post(self, url: str, *, json: Dict[str, Any]) -> _FakeResponse:
        type(self).last_request = {"url": url, "json": json}
        return _JsonAckResponse()


class _RejectedAckAsyncClient(_FakeAsyncClient):
    async def post(self, url: str, *, json: Dict[str, Any]) -> _FakeResponse:
        type(self).last_request = {"url": url, "json": json}
        return _JsonAckResponse({"accepted": False})


@pytest.mark.asyncio
async def test_testing_agent_client_requires_accepted_ack_payload(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _JsonAckAsyncClient)

    client = TestingAgentClient(base_url="http://127.0.0.1:8003", timeout_seconds=3.0)
    payload = GeneratedCypherSubmissionRequest(
        id="qa-001",
        question="查询协议版本",
        generation_run_id="cypher-run-001",
        generated_cypher="MATCH (p:Protocol) RETURN p.version",
        input_prompt_snapshot="prompt",
    )

    result = await client.submit(payload)

    assert result == {"accepted": True}
    assert _JsonAckAsyncClient.last_request == {
        "url": "http://127.0.0.1:8003/api/v1/evaluations/submissions",
        "json": payload.model_dump(),
    }


@pytest.mark.asyncio
async def test_testing_agent_client_rejects_non_accepted_ack_payload(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _RejectedAckAsyncClient)

    client = TestingAgentClient(base_url="http://127.0.0.1:8003", timeout_seconds=3.0, max_submit_attempts=1)
    payload = GeneratedCypherSubmissionRequest(
        id="qa-001",
        question="查询协议版本",
        generation_run_id="cypher-run-001",
        generated_cypher="MATCH (p:Protocol) RETURN p.version",
        input_prompt_snapshot="prompt",
    )

    with pytest.raises(ValueError, match="testing-agent submission ack contract violation"):
        await client.submit(payload)


@pytest.mark.asyncio
async def test_testing_agent_client_submits_generation_failure_report(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _JsonAckAsyncClient)

    client = TestingAgentClient(base_url="http://127.0.0.1:8003", timeout_seconds=3.0)
    payload = CgaGenerationNonSuccessReport(
        id="qa-001",
        question="查询协议版本",
        generation_run_id="cypher-run-001",
        generation_status="generation_failed",
        failure_reason="wrapped_in_markdown",
        input_prompt_snapshot="prompt",
        parsed_cypher="MATCH (p:Protocol) RETURN p.version",
        gate_passed=False,
    )

    result = await client.submit_generation_failure(payload)

    assert result == {"accepted": True}
    assert _JsonAckAsyncClient.last_request == {
        "url": "http://127.0.0.1:8003/api/v1/evaluations/generation-failures",
        "json": payload.model_dump(),
    }
