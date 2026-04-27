from __future__ import annotations

from fastapi.testclient import TestClient

import services.testing_agent.app.main as main_module
from services.testing_agent.app.main import app
from services.testing_agent.app.models import QAGoldenResponse, SubmissionReceipt


class StubService:
    async def ingest_golden(self, request):
        return QAGoldenResponse(id=request.id, status="received_golden_only")

    async def ingest_submission(self, request):
        return SubmissionReceipt(accepted=True)

    def get_evaluation_status(self, id: str):
        return {
            "id": id,
            "golden": None,
            "submission": None,
            "attempts": [],
            "issue_ticket": None,
        }

    def get_issue_ticket(self, ticket_id: str):
        return None

    def get_service_status(self):
        return {"status": "ok"}


def test_testing_service_root_redirects_to_healthcheck():
    client = TestClient(app)

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/health"


def test_testing_service_does_not_host_runtime_console_routes():
    client = TestClient(app)

    assert client.get("/console").status_code == 404
    assert client.get("/api/v1/runtime/architecture").status_code == 404
    assert client.post(
        "/api/v1/runtime/console-runs",
        json={"id": "qa-console-001", "question": "查询网络设备名称"},
    ).status_code == 404


def test_healthcheck_uses_current_service_name():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "testing-agent"}


def test_submission_route_returns_minimal_receipt(monkeypatch):
    monkeypatch.setattr(main_module, "get_testing_service", lambda: StubService())
    client = TestClient(app)

    response = client.post(
        "/api/v1/evaluations/submissions",
        json={
            "id": "qa-001",
            "question": "查询设备",
            "generation_run_id": "run-001",
            "generated_cypher": "MATCH (n) RETURN n",
            "input_prompt_snapshot": "prompt",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"accepted": True}


def test_golden_route_returns_status_response(monkeypatch):
    monkeypatch.setattr(main_module, "get_testing_service", lambda: StubService())
    client = TestClient(app)

    response = client.post(
        "/api/v1/qa/goldens",
        json={
            "id": "qa-001",
            "cypher": "MATCH (n) RETURN n",
            "answer": [],
            "difficulty": "L3",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"id": "qa-001", "status": "received_golden_only", "verdict": None, "issue_ticket_id": None}
