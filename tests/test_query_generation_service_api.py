from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from services.cypher_generator_agent.app.main import app
from services.cypher_generator_agent.app.models import GenerationRunResult


client = TestClient(app)


def test_healthcheck_uses_cypher_generator_agent_name():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "cypher-generator-agent"}


def test_ingest_question_returns_no_business_response_body(monkeypatch):
    service = AsyncMock()
    service.ingest_question.return_value = GenerationRunResult(
        generation_run_id="cypher-run-001",
        generation_status="submitted_to_testing",
    )
    monkeypatch.setattr("services.cypher_generator_agent.app.main.get_workflow_service", lambda: service)

    response = client.post("/api/v1/qa/questions", json={"id": "qa-001", "question": "查询协议版本"})

    assert response.status_code == 204
    assert response.content == b""
    service.ingest_question.assert_awaited_once()


def test_generator_status_returns_file_knowledge_context_fields(monkeypatch):
    monkeypatch.setattr(
        "services.cypher_generator_agent.app.main.get_generator_status",
        lambda: {
            "llm_enabled": False,
            "active_mode": "disabled",
            "knowledge_context_source": "file",
            "knowledge_docs_dir_configured": True,
            "testing_agent_configured": True,
        },
    )

    response = client.get("/api/v1/generator/status")

    assert response.status_code == 200
    assert response.json()["knowledge_context_source"] == "file"
    assert response.json()["knowledge_docs_dir_configured"] is True
    assert "knowledge_agent_configured" not in response.json()


def test_legacy_runtime_and_repair_endpoints_are_not_exposed():
    assert client.get("/api/v1/questions/qa-001").status_code == 404
    assert client.get("/api/v1/questions/qa-001/prompt").status_code == 404
    assert client.post("/api/v1/internal/repair-plans", json={}).status_code == 404
    assert client.get("/api/v1/tugraph/connection-test").status_code == 404


def test_runtime_modules_do_not_export_legacy_cgs_compatibility_names():
    from services.cypher_generator_agent.app import clients, service

    assert not hasattr(service, "QueryWorkflowService")
    assert not hasattr(clients, "PromptServiceClient")
    assert not hasattr(clients, "QwenGeneratorClient")
    assert not hasattr(clients, "TestingServiceClient")
