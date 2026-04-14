from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from services.repair_service.app.clients import KnowledgeOpsRepairApplyClient
from tools.mock_knowledge_ops.app import app
from shared.models import KnowledgeRepairSuggestionRequest


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url: str, json: dict):
        return httpx.Response(status_code=200, json={"ok": True})


@pytest.mark.asyncio
async def test_knowledge_ops_apply_capture_writes_payload_file(tmp_path, monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    capture_dir = tmp_path / "captures"
    client = KnowledgeOpsRepairApplyClient(
        apply_url="http://ko/api/knowledge/repairs/apply",
        timeout_seconds=3.0,
        capture_dir=str(capture_dir),
        sleep_fn=AsyncMock(),
    )
    payload = KnowledgeRepairSuggestionRequest(
        id="q-001",
        suggestion="PROMPT",
        knowledge_types=["business_knowledge", "few_shot"],
    )

    await client.apply(payload)

    saved = Path(capture_dir) / "q-001.json"
    assert saved.exists()
    content = json.loads(saved.read_text(encoding="utf-8"))
    assert content == {
        "id": "q-001",
        "suggestion": "PROMPT",
        "knowledge_types": ["business_knowledge", "few_shot"],
    }


def test_mock_knowledge_ops_apply_validates_request_and_writes_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/knowledge/repairs/apply",
            json={
                "id": "q-002",
                "suggestion": "Add a canonical few_shot example.",
                "knowledge_types": ["few_shot", "business_knowledge"],
            },
        )

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["status"] == "ok"
    assert response_json["changes"] == [
        {
            "doc_type": "few_shot",
            "section": "mock",
            "before": "",
            "after": "Add a canonical few_shot example.",
        },
        {
            "doc_type": "business_knowledge",
            "section": "mock",
            "before": "",
            "after": "Add a canonical few_shot example.",
        },
    ]

    saved = tmp_path / "data" / "mock_knowledge_ops" / "last_apply.json"
    assert saved.exists()
    assert json.loads(saved.read_text(encoding="utf-8")) == {
        "id": "q-002",
        "suggestion": "Add a canonical few_shot example.",
        "knowledge_types": ["few_shot", "business_knowledge"],
    }

    with TestClient(app) as client:
        rejected = client.post(
            "/api/knowledge/repairs/apply",
            json={
                "id": "q-003",
                "suggestion": "This should be rejected.",
                "knowledge_types": ["few-shot"],
            },
        )

    assert rejected.status_code == 422

    with TestClient(app) as client:
        missing = client.post(
            "/api/knowledge/repairs/apply",
            json={
                "id": "q-004",
                "suggestion": "This should also be rejected.",
            },
        )

    assert missing.status_code == 422
