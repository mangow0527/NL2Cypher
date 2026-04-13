from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from services.repair_service.app.clients import KnowledgeOpsRepairApplyClient
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
        knowledge_types=["business_knowledge", "few-shot"],
    )

    await client.apply(payload)

    saved = Path(capture_dir) / "q-001.json"
    assert saved.exists()
    content = saved.read_text(encoding="utf-8")
    assert '"id": "q-001"' in content
    assert '"knowledge_types"' in content
