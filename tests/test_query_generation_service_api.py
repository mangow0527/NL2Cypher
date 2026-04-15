from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from services.query_generator_service.app.main import app


client = TestClient(app)


def test_get_prompt_snapshot_endpoint_returns_prompt(monkeypatch):
    service = MagicMock()
    service.get_prompt_snapshot.side_effect = lambda task_id: {
        "id": task_id,
        "input_prompt_snapshot": "请返回一个合法 Cypher",
    }
    monkeypatch.setattr("services.query_generator_service.app.main.get_workflow_service", lambda: service)

    response = client.get("/api/v1/questions/qa-010/prompt")

    assert response.status_code == 200
    assert response.json() == {
        "id": "qa-010",
        "attempt_no": 1,
        "input_prompt_snapshot": "请返回一个合法 Cypher",
    }


def test_get_prompt_snapshot_endpoint_returns_404_when_missing(monkeypatch):
    service = MagicMock()
    service.get_prompt_snapshot.side_effect = lambda task_id: None
    monkeypatch.setattr("services.query_generator_service.app.main.get_workflow_service", lambda: service)

    response = client.get("/api/v1/questions/qa-missing/prompt")

    assert response.status_code == 404
