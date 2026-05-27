from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import services.testing_agent.app.main as main_module
from services.testing_agent.app.main import app
from services.testing_agent.app.models import QAGoldenResponse, SubmissionReceipt


class StubService:
    def __init__(self) -> None:
        self.generation_failure_reports = []

    async def ingest_golden(self, request):
        return QAGoldenResponse(id=request.id, status="received_golden_only")

    async def ingest_submission(self, request):
        return SubmissionReceipt(accepted=True)

    async def ingest_generation_failure(self, request):
        self.generation_failure_reports.append(request)
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
            "generation_status": "generated",
            "generated_cypher": "MATCH (n) RETURN n",
            "input_prompt_snapshot": "prompt",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"accepted": True}


@pytest.mark.parametrize(
    ("payload", "expected_status"),
    [
        (
            {
                "id": "qa-generation-failed",
                "question": "查询设备",
                "generation_run_id": "run-generation-failed",
                "generation_status": "generation_failed",
                "failure_reason": "no_cypher_found",
                "parsed_cypher": "",
                "input_prompt_snapshot": "prompt-before-gate",
            },
            "generation_failed",
        ),
        (
            {
                "id": "qa-unsupported",
                "question": "查询两台设备之间的最短路径",
                "generation_run_id": "run-unsupported",
                "generation_status": "unsupported_query_shape",
                "failure_reason": "unsupported_query_shape",
                "parsed_cypher": None,
                "input_prompt_snapshot": '{"trace_schema_version":"cga_graph_trace_v1"}',
                "gate_passed": False,
            },
            "unsupported_query_shape",
        ),
        (
            {
                "id": "qa-clarification",
                "question": "查询服务 A 对应的网元",
                "generation_run_id": "run-clarification",
                "generation_status": "clarification_required",
                "input_prompt_snapshot": '{"schema_version":"cga_trace_v2"}',
                "clarification": {
                    "source_stage": "semantic_view_matching",
                    "reason_code": "ambiguous_path_semantic",
                    "question_zh": "你说的对应网元是指源网元还是目的网元？",
                    "expected_answer_type": "single_choice",
                    "options": [{"id": "source", "label": "源网元"}],
                },
                "gate_passed": False,
            },
            "clarification_required",
        ),
        (
            {
                "id": "qa-service-failed",
                "question": "查询设备",
                "generation_run_id": "run-service-failed",
                "generation_status": "service_failed",
                "failure_reason": "model_invocation_failed",
                "parsed_cypher": None,
                "input_prompt_snapshot": "",
                "gate_passed": False,
            },
            "service_failed",
        ),
    ],
)
def test_generation_failures_route_accepts_non_success_reports(monkeypatch, payload, expected_status):
    service = StubService()
    monkeypatch.setattr(main_module, "get_testing_service", lambda: service)
    client = TestClient(app)

    response = client.post("/api/v1/evaluations/generation-failures", json=payload)

    assert response.status_code == 200
    assert response.json() == {"accepted": True}
    assert len(service.generation_failure_reports) == 1
    report = service.generation_failure_reports[0]
    assert report.generation_status == expected_status
    assert report.gate_passed is False


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
