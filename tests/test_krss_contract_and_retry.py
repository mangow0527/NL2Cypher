from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from pydantic import ValidationError

from shared.models import KnowledgeRepairSuggestionRequest
from services.repair_service.app.clients import CGSPromptSnapshotClient, KnowledgeOpsRepairApplyClient


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, json_data: Optional[Dict[str, Any]] = None) -> None:
        self.status_code = status_code
        self._json_data = json_data or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> Dict[str, Any]:
        return self._json_data


class _FakeAsyncClient:
    last_request: Optional[Dict[str, Any]] = None
    responses: List[_FakeResponse] = []
    post_side_effects: List[object] = []
    init_count: int = 0

    def __init__(self, *, timeout: float) -> None:
        self.timeout = timeout
        type(self).init_count += 1

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def get(self, url: str) -> _FakeResponse:
        type(self).last_request = {"method": "GET", "url": url}
        return _FakeResponse(
            status_code=200,
            json_data={"id": "q-123", "input_prompt_snapshot": "PROMPT SNAPSHOT"},
        )

    async def post(self, url: str, *, json: Dict[str, Any]) -> _FakeResponse:
        type(self).last_request = {"method": "POST", "url": url, "json": json}
        if type(self).post_side_effects:
            effect = type(self).post_side_effects.pop(0)
            if isinstance(effect, Exception):
                raise effect
            return effect
        if not type(self).responses:
            return _FakeResponse(status_code=200)
        return type(self).responses.pop(0)


@pytest.fixture(autouse=True)
def reset_fake_async_client_state():
    _FakeAsyncClient.last_request = None
    _FakeAsyncClient.responses = []
    _FakeAsyncClient.post_side_effects = []
    _FakeAsyncClient.init_count = 0
    yield
    _FakeAsyncClient.last_request = None
    _FakeAsyncClient.responses = []
    _FakeAsyncClient.post_side_effects = []
    _FakeAsyncClient.init_count = 0


def test_knowledge_repair_suggestion_request_rejects_invalid_knowledge_type():
    with pytest.raises(ValidationError):
        KnowledgeRepairSuggestionRequest(
            id="q-123",
            suggestion="Use a tighter schema hint.",
            knowledge_types=["not-a-real-knowledge-type"],
        )


@pytest.mark.asyncio
async def test_cgs_prompt_snapshot_client_uses_prompt_snapshot_contract(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    client = CGSPromptSnapshotClient(base_url="http://127.0.0.1:8000", timeout_seconds=3.0)
    snapshot = await client.fetch(id="q-123")

    assert snapshot.model_dump() == {
        "id": "q-123",
        "input_prompt_snapshot": "PROMPT SNAPSHOT",
    }
    assert _FakeAsyncClient.last_request == {
        "method": "GET",
        "url": "http://127.0.0.1:8000/api/v1/questions/q-123/prompt",
    }


@pytest.mark.asyncio
async def test_knowledge_ops_repair_apply_client_retries_until_http_200(monkeypatch):
    import httpx

    _FakeAsyncClient.responses = [
        _FakeResponse(status_code=500),
        _FakeResponse(status_code=502),
        _FakeResponse(status_code=200),
    ]
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    sleep_calls: List[float] = []

    async def fake_sleep(delay_seconds: float) -> None:
        sleep_calls.append(delay_seconds)

    client = KnowledgeOpsRepairApplyClient(
        apply_url="http://127.0.0.1:8010/api/knowledge/repairs/apply",
        timeout_seconds=3.0,
        sleep_fn=fake_sleep,
        retry_delay_seconds=0.01,
    )
    payload = KnowledgeRepairSuggestionRequest(
        id="q-123",
        suggestion="Prefer schema-aligned relations and add an example.",
        knowledge_types=["schema", "few-shot"],
    )

    await client.apply(payload)

    assert _FakeAsyncClient.last_request == {
        "method": "POST",
        "url": "http://127.0.0.1:8010/api/knowledge/repairs/apply",
        "json": {
            "id": "q-123",
            "suggestion": "Prefer schema-aligned relations and add an example.",
            "knowledge_types": ["schema", "few-shot"],
        },
    }
    assert sleep_calls == [0.01, 0.01]


@pytest.mark.asyncio
async def test_knowledge_ops_repair_apply_client_retries_202_or_204_until_later_200(monkeypatch):
    import httpx

    _FakeAsyncClient.responses = [
        _FakeResponse(status_code=204),
        _FakeResponse(status_code=200),
    ]
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    sleep_calls: List[float] = []

    async def fake_sleep(delay_seconds: float) -> None:
        sleep_calls.append(delay_seconds)

    client = KnowledgeOpsRepairApplyClient(
        apply_url="http://127.0.0.1:8010/api/knowledge/repairs/apply",
        timeout_seconds=3.0,
        sleep_fn=fake_sleep,
        retry_delay_seconds=0.03,
    )
    payload = KnowledgeRepairSuggestionRequest(
        id="q-204",
        suggestion="Treat 204 as retryable, only 200 counts as success.",
        knowledge_types=["cypher_syntax"],
    )

    await client.apply(payload)

    assert sleep_calls == [0.03]


@pytest.mark.asyncio
async def test_knowledge_ops_repair_apply_client_retries_after_transport_exception(monkeypatch):
    import httpx

    _FakeAsyncClient.responses = []
    _FakeAsyncClient.post_side_effects = [
        httpx.ConnectError("connect failed", request=httpx.Request("POST", "http://127.0.0.1:8010/api/knowledge/repairs/apply")),
        _FakeResponse(status_code=200),
    ]
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    sleep_calls: List[float] = []

    async def fake_sleep(delay_seconds: float) -> None:
        sleep_calls.append(delay_seconds)

    client = KnowledgeOpsRepairApplyClient(
        apply_url="http://127.0.0.1:8010/api/knowledge/repairs/apply",
        timeout_seconds=3.0,
        sleep_fn=fake_sleep,
        retry_delay_seconds=0.02,
    )
    payload = KnowledgeRepairSuggestionRequest(
        id="q-123",
        suggestion="Retry after transport errors.",
        knowledge_types=["system_prompt"],
    )

    await client.apply(payload)

    assert sleep_calls == [0.02]


@pytest.mark.asyncio
async def test_knowledge_ops_repair_apply_client_reuses_single_async_client(monkeypatch):
    import httpx

    _FakeAsyncClient.responses = [
        _FakeResponse(status_code=500),
        _FakeResponse(status_code=200),
    ]
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    sleep_calls: List[float] = []

    async def fake_sleep(delay_seconds: float) -> None:
        sleep_calls.append(delay_seconds)

    client = KnowledgeOpsRepairApplyClient(
        apply_url="http://127.0.0.1:8010/api/knowledge/repairs/apply",
        timeout_seconds=3.0,
        sleep_fn=fake_sleep,
        retry_delay_seconds=0.04,
    )
    payload = KnowledgeRepairSuggestionRequest(
        id="q-555",
        suggestion="Reuse one AsyncClient instance across retries.",
        knowledge_types=["business_knowledge"],
    )

    await client.apply(payload)

    assert _FakeAsyncClient.init_count == 1
    assert sleep_calls == [0.04]
