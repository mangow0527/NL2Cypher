from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from services.repair_agent.app.models import RepairIssueTicketResponse
from services.testing_agent.app.clients import RepairServiceClient
from services.testing_agent.app.models import (
    ActualPayload,
    EvaluationSummary,
    ExecutionAccuracy,
    ExecutionResult,
    GLEUSignal,
    GrammarMetric,
    IssueTicket,
    JaroWinklerSimilaritySignal,
    PrimaryMetrics,
    SecondarySignals,
    SemanticCheck,
    StrictCheck,
    ExpectedPayload,
    GenerationEvidence,
)


class _FakeResponse:
    def __init__(self, *, payload: Dict[str, Any], status_code: int = 200) -> None:
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> Dict[str, Any]:
        return self._payload


class _FakeAsyncClient:
    last_request: Optional[Dict[str, Any]] = None

    def __init__(self, *, timeout: float) -> None:
        self.timeout = timeout

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def post(self, url: str, *, json: Dict[str, Any]) -> _FakeResponse:
        type(self).last_request = {"url": url, "json": json}
        return _FakeResponse(
            payload={
                "status": "applied",
                "analysis_id": "analysis-ticket-qa-001-attempt-1",
                "id": "qa-001",
                "knowledge_repair_request": {
                    "id": "qa-001",
                    "suggestion": "Add relation guidance.",
                    "knowledge_types": ["few_shot"],
                },
                "knowledge_ops_response": {"status": "ok"},
                "applied": True,
            }
        )


def _make_issue_ticket() -> IssueTicket:
    return IssueTicket(
        ticket_id="ticket-qa-001-attempt-1",
        id="qa-001",
        difficulty="L3",
        question="查询设备",
        expected=ExpectedPayload(cypher="MATCH (n) RETURN n", answer=[]),
        actual=ActualPayload(
            generated_cypher="MATCHH (n) RETURN n",
            execution=ExecutionResult(success=False, rows=[], row_count=0, error_message="syntax error", elapsed_ms=3),
        ),
        evaluation=EvaluationSummary(
            verdict="fail",
            primary_metrics=PrimaryMetrics(
                grammar=GrammarMetric(score=0, parser_error="Unexpected token RETURN", message="Unexpected token RETURN"),
                execution_accuracy=ExecutionAccuracy(
                    score=0,
                    reason="grammar_failed",
                    strict_check=StrictCheck(status="not_run", message=None, order_sensitive=False, expected_row_count=0, actual_row_count=0),
                    semantic_check=SemanticCheck(status="not_run", message=None, raw_output=None),
                ),
            ),
            secondary_signals=SecondarySignals(
                gleu=GLEUSignal(score=0.0, tokenizer="whitespace", min_n=1, max_n=4),
                jaro_winkler_similarity=JaroWinklerSimilaritySignal(
                    score=0.0,
                    normalization="lightweight",
                    library="jellyfish",
                ),
            ),
        ),
        generation_evidence=GenerationEvidence(
            generation_run_id="run-001",
            attempt_no=1,
            input_prompt_snapshot="prompt-1",
        ),
    )


@pytest.mark.asyncio
async def test_repair_service_client_validates_formal_repair_response(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    client = RepairServiceClient(base_url="http://127.0.0.1:8002", timeout_seconds=3.0)

    response = await client.submit_issue_ticket(_make_issue_ticket())

    assert isinstance(response, RepairIssueTicketResponse)
    assert response.analysis_id == "analysis-ticket-qa-001-attempt-1"
    assert response.knowledge_repair_request.knowledge_types == ["few_shot"]
    assert _FakeAsyncClient.last_request is not None
    assert _FakeAsyncClient.last_request["url"] == "http://127.0.0.1:8002/api/v1/issue-tickets"
