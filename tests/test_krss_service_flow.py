from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
import pytest

from shared.models import (
    ActualAnswer,
    EvaluationDimensions,
    EvaluationSummary,
    ExpectedAnswer,
    IssueTicket,
    KRSSAnalysisRecord,
    KRSSIssueTicketResponse,
    KnowledgeRepairSuggestionRequest,
    PromptSnapshotResponse,
    TuGraphExecutionResult,
)
from services.repair_service.app.main import app
from services.repair_service.app.service import RepairService


def _make_issue_ticket() -> IssueTicket:
    return IssueTicket(
        ticket_id="ticket-001",
        id="q-001",
        difficulty="L3",
        question="查询协议版本对应的隧道",
        expected=ExpectedAnswer(cypher="MATCH (t:Tunnel) RETURN t", answer=[{"name": "tunnel-1"}]),
        actual=ActualAnswer(
            generated_cypher="MATCH (t:Tunnel) RETURN t",
            execution=TuGraphExecutionResult(
                success=True,
                rows=[{"name": "wrong-tunnel"}],
                row_count=1,
                error_message=None,
                elapsed_ms=12,
            ),
        ),
        evaluation=EvaluationSummary(
            verdict="partial_fail",
            dimensions=EvaluationDimensions(
                syntax_validity="pass",
                schema_alignment="pass",
                result_correctness="fail",
                question_alignment="fail",
            ),
            symptom="Wrong tunnel returned",
            evidence=["result does not match expected tunnel"],
        ),
    )


def test_issue_ticket_flow_fetches_prompt_analyzes_applies_and_returns_krss_response(monkeypatch):
    ticket = _make_issue_ticket()
    prompt_client = AsyncMock()
    prompt_client.fetch.return_value = PromptSnapshotResponse(
        id=ticket.id,
        input_prompt_snapshot="Original CGS prompt snapshot",
    )
    analyzer = AsyncMock()
    analyzer.analyze.return_value = MagicMock(
        id=ticket.id,
        confidence=0.91,
        rationale="Prompt misses protocol-version mapping guidance",
        used_experiments=False,
        to_request=MagicMock(
            return_value=KnowledgeRepairSuggestionRequest(
                id=ticket.id,
                suggestion="Add business mapping and a matching few-shot example",
                knowledge_types=["business_knowledge", "few-shot"],
            )
        ),
    )
    apply_client = AsyncMock()
    repository = MagicMock()
    service = MagicMock()
    service.create_issue_ticket_response = AsyncMock(
        return_value=KRSSIssueTicketResponse(
            status="applied",
            analysis_id="analysis-q-001",
            id=ticket.id,
            knowledge_repair_request=KnowledgeRepairSuggestionRequest(
                id=ticket.id,
                suggestion="Add business mapping and a matching few-shot example",
                knowledge_types=["business_knowledge", "few-shot"],
            ),
            applied=True,
        )
    )
    service.get_analysis.return_value = None

    monkeypatch.setattr("services.repair_service.app.main.repair_service", service)

    with TestClient(app) as client:
        response = client.post("/api/v1/issue-tickets", json=ticket.model_dump(mode="json"))

    assert response.status_code == 200
    assert response.json() == {
        "status": "applied",
        "analysis_id": "analysis-q-001",
        "id": "q-001",
        "knowledge_repair_request": {
            "id": "q-001",
            "suggestion": "Add business mapping and a matching few-shot example",
            "knowledge_types": ["business_knowledge", "few-shot"],
        },
        "applied": True,
    }


@pytest.mark.asyncio
async def test_repair_service_orchestrates_krss_apply_flow():
    ticket = _make_issue_ticket()
    prompt_client = AsyncMock()
    prompt_client.fetch.return_value = PromptSnapshotResponse(
        id=ticket.id,
        input_prompt_snapshot="Original CGS prompt snapshot",
    )
    analysis_result = MagicMock()
    analysis_result.id = ticket.id
    analysis_result.confidence = 0.91
    analysis_result.rationale = "Prompt misses protocol-version mapping guidance"
    analysis_result.used_experiments = False
    analysis_result.to_request.return_value = KnowledgeRepairSuggestionRequest(
        id=ticket.id,
        suggestion="Add business mapping and a matching few-shot example",
        knowledge_types=["business_knowledge", "few-shot"],
    )
    analyzer = AsyncMock()
    analyzer.analyze.return_value = analysis_result
    apply_client = AsyncMock()
    repository = MagicMock()

    service = RepairService(
        repository=repository,
        prompt_snapshot_client=prompt_client,
        analyzer=analyzer,
        apply_client=apply_client,
    )

    response = await service.create_issue_ticket_response(ticket)

    prompt_client.fetch.assert_awaited_once_with(ticket.id)
    analyzer.analyze.assert_awaited_once_with(ticket, "Original CGS prompt snapshot")
    apply_client.apply.assert_awaited_once_with(
        KnowledgeRepairSuggestionRequest(
            id=ticket.id,
            suggestion="Add business mapping and a matching few-shot example",
            knowledge_types=["business_knowledge", "few-shot"],
        )
    )
    repository.save_analysis.assert_called_once()
    assert response == KRSSIssueTicketResponse(
        status="applied",
        analysis_id="analysis-ticket-001",
        id=ticket.id,
        knowledge_repair_request=KnowledgeRepairSuggestionRequest(
            id=ticket.id,
            suggestion="Add business mapping and a matching few-shot example",
            knowledge_types=["business_knowledge", "few-shot"],
        ),
        applied=True,
    )


@pytest.mark.asyncio
async def test_repair_service_uses_ticket_scoped_analysis_id_uniqueness():
    first_ticket = _make_issue_ticket()
    second_ticket = _make_issue_ticket()
    second_ticket.ticket_id = "ticket-002"

    prompt_client = AsyncMock()
    prompt_client.fetch.return_value = PromptSnapshotResponse(
        id=first_ticket.id,
        input_prompt_snapshot="Original CGS prompt snapshot",
    )
    analysis_result = MagicMock()
    analysis_result.id = first_ticket.id
    analysis_result.confidence = 0.91
    analysis_result.rationale = "Prompt misses protocol-version mapping guidance"
    analysis_result.used_experiments = False
    analysis_result.to_request.return_value = KnowledgeRepairSuggestionRequest(
        id=first_ticket.id,
        suggestion="Add business mapping and a matching few-shot example",
        knowledge_types=["business_knowledge", "few-shot"],
    )
    analyzer = AsyncMock()
    analyzer.analyze.return_value = analysis_result
    apply_client = AsyncMock()
    repository = MagicMock()

    service = RepairService(
        repository=repository,
        prompt_snapshot_client=prompt_client,
        analyzer=analyzer,
        apply_client=apply_client,
    )

    first_response = await service.create_issue_ticket_response(first_ticket)
    second_response = await service.create_issue_ticket_response(second_ticket)

    assert first_response.analysis_id == "analysis-ticket-001"
    assert second_response.analysis_id == "analysis-ticket-002"
    assert first_response.analysis_id != second_response.analysis_id


def test_get_krss_analysis_endpoint_returns_record(monkeypatch):
    analysis = KRSSAnalysisRecord(
        analysis_id="analysis-ticket-001",
        ticket_id="ticket-001",
        id="q-001",
        status="applied",
        prompt_snapshot="Original CGS prompt snapshot",
        knowledge_repair_request=KnowledgeRepairSuggestionRequest(
            id="q-001",
            suggestion="Add business mapping and a matching few-shot example",
            knowledge_types=["business_knowledge", "few-shot"],
        ),
        confidence=0.91,
        rationale="Prompt misses protocol-version mapping guidance",
        used_experiments=False,
        applied=True,
        created_at="2026-04-13T00:00:00+00:00",
        applied_at="2026-04-13T00:00:01+00:00",
    )
    service = MagicMock()
    service.create_issue_ticket_response = AsyncMock()
    service.get_analysis.return_value = analysis
    monkeypatch.setattr("services.repair_service.app.main.repair_service", service)

    with TestClient(app) as client:
        response = client.get("/api/v1/krss-analyses/analysis-ticket-001")

    assert response.status_code == 200
    assert response.json()["analysis_id"] == "analysis-ticket-001"
    assert response.json()["ticket_id"] == "ticket-001"


def test_legacy_repair_plan_read_path_is_not_exposed():
    with TestClient(app) as client:
        response = client.get("/api/v1/repair-plans/analysis-ticket-001")

    assert response.status_code == 404
