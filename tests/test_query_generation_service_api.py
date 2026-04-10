from __future__ import annotations

from fastapi.testclient import TestClient

from services.query_generator_service.app.main import app
from services.query_generator_service.app.service import workflow_service


client = TestClient(app)


def test_get_prompt_snapshot_endpoint_returns_prompt(monkeypatch):
    monkeypatch.setattr(
        workflow_service,
        "get_prompt_snapshot",
        lambda task_id: {
            "id": task_id,
            "input_prompt_snapshot": "请返回一个合法 Cypher",
        },
    )

    response = client.get("/api/v1/questions/qa-010/prompt")

    assert response.status_code == 200
    assert response.json() == {
        "id": "qa-010",
        "input_prompt_snapshot": "请返回一个合法 Cypher",
    }


def test_get_prompt_snapshot_endpoint_returns_404_when_missing(monkeypatch):
    monkeypatch.setattr(workflow_service, "get_prompt_snapshot", lambda task_id: None)

    response = client.get("/api/v1/questions/qa-missing/prompt")

    assert response.status_code == 404
