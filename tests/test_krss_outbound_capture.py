from __future__ import annotations

import json
from pathlib import Path
from typing import Literal
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from services.repair_service.app.clients import KnowledgeOpsRepairApplyClient
from shared.models import KnowledgeRepairSuggestionRequest


class _PromptPackageRequest(BaseModel):
    id: str
    question: str


KnowledgeType = Literal["cypher_syntax", "few_shot", "system_prompt", "business_knowledge"]


class _ApplyRepairRequest(BaseModel):
    id: str = Field(min_length=1)
    suggestion: str = Field(min_length=1)
    knowledge_types: list[KnowledgeType]


class _RepairChange(BaseModel):
    doc_type: str
    section: str
    before: str
    after: str


class _ApplyRepairResponse(BaseModel):
    status: str = "ok"
    changes: list[_RepairChange]


app = FastAPI(title="Test Mock Knowledge Ops", version="1.0.0")


@app.post("/api/knowledge/rag/prompt-package")
async def prompt_package(req: _PromptPackageRequest) -> str:
    del req
    return "请只返回 JSON，且必须包含 cypher 字段。"


@app.post("/api/knowledge/repairs/apply", response_model=_ApplyRepairResponse)
async def repairs_apply(payload: _ApplyRepairRequest) -> _ApplyRepairResponse:
    knowledge_types = payload.knowledge_types or []
    out_dir = Path("data/mock_knowledge_ops")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "last_apply.json").write_text(
        json.dumps(
            {
                "id": payload.id,
                "suggestion": payload.suggestion,
                "knowledge_types": list(knowledge_types),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    changes = [
        _RepairChange(doc_type=knowledge_type, section="mock", before="", after=payload.suggestion)
        for knowledge_type in knowledge_types
    ]
    return _ApplyRepairResponse(changes=changes)


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
