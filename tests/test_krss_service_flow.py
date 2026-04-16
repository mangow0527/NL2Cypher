from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
import pytest

from contracts.models import (
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
from services.repair_agent.app.analysis import KRSSAnalyzer
from services.repair_agent.app.main import app
from services.repair_agent.app.service import RepairService


class _DeterministicKRSSDiagnosisClient:
    async def diagnose(self, context: dict[str, object]) -> dict[str, object]:
        dimensions = context["evaluation_summary"]["dimensions"]

        if dimensions["syntax_validity"] == "fail":
            return {
                "primary_knowledge_type": "cypher_syntax",
                "secondary_knowledge_types": ["system_prompt"],
                "confidence": 0.9,
                "suggestion": "Add Cypher syntax guardrails and a system prompt rule that rejects malformed query patterns.",
                "rationale": "The failing ticket shows a syntax-validity error, so the weakest link is syntax guidance rather than business context.",
                "need_validation": False,
                "candidate_patch_types": [],
            }

        if dimensions["question_alignment"] == "fail" or dimensions["result_correctness"] == "fail":
            return {
                "primary_knowledge_type": "few_shot",
                "secondary_knowledge_types": ["business_knowledge"],
                "confidence": 0.85,
                "suggestion": "Add a few_shot example that matches the failed question pattern.",
                "rationale": "The query missed the intended semantics, which usually points to missing business context or missing examples.",
                "need_validation": True,
                "candidate_patch_types": ["few_shot", "business_knowledge"],
            }

        return {
            "primary_knowledge_type": "system_prompt",
            "secondary_knowledge_types": [],
            "confidence": 0.8,
            "suggestion": "Tighten the system prompt so future generations preserve the expected question intent and output contract.",
            "rationale": "Fallback deterministic KRSS diagnosis.",
            "need_validation": False,
            "candidate_patch_types": [],
        }


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
        used_experiments=True,
        primary_knowledge_type="few_shot",
        secondary_knowledge_types=["business_knowledge"],
        candidate_patch_types=["few_shot", "business_knowledge"],
        validation_mode="lightweight",
        validation_result={
            "validated_patch_types": ["few_shot"],
            "rejected_patch_types": ["business_knowledge"],
            "validation_reasoning": ["few_shot best explains the mismatch"],
        },
        diagnosis_context_summary={"failure_diff": {"entity_or_relation_problem": True}},
        to_request=MagicMock(
            return_value=KnowledgeRepairSuggestionRequest(
                id=ticket.id,
                suggestion="Add a few_shot example that matches the failed question pattern.",
                knowledge_types=["few_shot"],
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
                suggestion="Add a few_shot example that matches the failed question pattern.",
                knowledge_types=["few_shot"],
            ),
            applied=True,
        )
    )
    service.get_analysis.return_value = None

    monkeypatch.setattr("services.repair_agent.app.main.get_repair_service", lambda: service)

    with TestClient(app) as client:
        response = client.post("/api/v1/issue-tickets", json=ticket.model_dump(mode="json"))

    assert response.status_code == 200
    assert response.json() == {
        "status": "applied",
        "analysis_id": "analysis-q-001",
            "id": "q-001",
            "knowledge_repair_request": {
                "id": "q-001",
                "suggestion": "Add a few_shot example that matches the failed question pattern.",
                "knowledge_types": ["few_shot"],
            },
        "knowledge_ops_response": None,
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
    analysis_result.used_experiments = True
    analysis_result.primary_knowledge_type = "few_shot"
    analysis_result.secondary_knowledge_types = ["business_knowledge"]
    analysis_result.candidate_patch_types = ["few_shot", "business_knowledge"]
    analysis_result.validation_mode = "lightweight"
    analysis_result.validation_result = {
        "validated_patch_types": ["few_shot"],
        "rejected_patch_types": ["business_knowledge"],
        "validation_reasoning": ["few_shot best explains the mismatch"],
    }
    analysis_result.diagnosis_context_summary = {"failure_diff": {"entity_or_relation_problem": True}}
    analysis_result.to_request.return_value = KnowledgeRepairSuggestionRequest(
        id=ticket.id,
        suggestion="Add a few_shot example that matches the failed question pattern.",
        knowledge_types=["few_shot"],
    )
    analyzer = AsyncMock()
    analyzer.analyze.return_value = analysis_result
    apply_client = AsyncMock()
    apply_client.apply.return_value = {"ok": True}
    repository = MagicMock()
    repository.get_analysis.return_value = None

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
            suggestion="Add a few_shot example that matches the failed question pattern.",
            knowledge_types=["few_shot"],
        )
    )
    repository.save_analysis.assert_called_once()
    assert response == KRSSIssueTicketResponse(
        status="applied",
        analysis_id="analysis-ticket-001",
        id=ticket.id,
        knowledge_repair_request=KnowledgeRepairSuggestionRequest(
            id=ticket.id,
            suggestion="Add a few_shot example that matches the failed question pattern.",
            knowledge_types=["few_shot"],
        ),
        knowledge_ops_response={"ok": True},
        applied=True,
    )


@pytest.mark.asyncio
async def test_repair_service_is_idempotent_when_analysis_exists():
    ticket = _make_issue_ticket()
    existing = KRSSAnalysisRecord(
        analysis_id="analysis-ticket-001",
        ticket_id="ticket-001",
        id=ticket.id,
        status="applied",
        prompt_snapshot="cached prompt",
        knowledge_repair_request=KnowledgeRepairSuggestionRequest(
            id=ticket.id,
            suggestion="cached suggestion",
            knowledge_types=["system_prompt"],
        ),
        knowledge_ops_response={"ok": True},
        confidence=0.9,
        rationale="cached",
        used_experiments=False,
        primary_knowledge_type="system_prompt",
        secondary_knowledge_types=[],
        candidate_patch_types=[],
        validation_mode="disabled",
        validation_result={"validated_patch_types": [], "rejected_patch_types": []},
        diagnosis_context_summary={},
        applied=True,
        created_at="2026-01-01T00:00:00Z",
        applied_at="2026-01-01T00:00:00Z",
    )

    prompt_client = AsyncMock()
    prompt_client.fetch.return_value = PromptSnapshotResponse(
        id=ticket.id,
        input_prompt_snapshot="should-not-be-used",
    )
    analyzer = AsyncMock()
    analyzer.analyze.return_value = MagicMock(
        id=ticket.id,
        confidence=0.5,
        rationale="should-not-be-used",
        used_experiments=False,
        to_request=MagicMock(
            return_value=KnowledgeRepairSuggestionRequest(
                id=ticket.id,
                suggestion="should-not-be-used",
                knowledge_types=["system_prompt"],
            )
        ),
    )
    apply_client = AsyncMock()
    apply_client.apply.return_value = {"ok": True}
    repository = MagicMock()
    repository.get_analysis.return_value = existing

    service = RepairService(
        repository=repository,
        prompt_snapshot_client=prompt_client,
        analyzer=analyzer,
        apply_client=apply_client,
    )

    response = await service.create_issue_ticket_response(ticket)

    prompt_client.fetch.assert_not_called()
    analyzer.analyze.assert_not_called()
    apply_client.apply.assert_not_called()
    assert response == KRSSIssueTicketResponse(
        status="applied",
        analysis_id=existing.analysis_id,
        id=existing.id,
        knowledge_repair_request=existing.knowledge_repair_request,
        knowledge_ops_response=existing.knowledge_ops_response,
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
    analysis_result.used_experiments = True
    analysis_result.primary_knowledge_type = "few_shot"
    analysis_result.secondary_knowledge_types = ["business_knowledge"]
    analysis_result.candidate_patch_types = ["few_shot", "business_knowledge"]
    analysis_result.validation_mode = "lightweight"
    analysis_result.validation_result = {
        "validated_patch_types": ["few_shot"],
        "rejected_patch_types": ["business_knowledge"],
        "validation_reasoning": ["few_shot best explains the mismatch"],
    }
    analysis_result.diagnosis_context_summary = {"failure_diff": {"entity_or_relation_problem": True}}
    analysis_result.to_request.return_value = KnowledgeRepairSuggestionRequest(
        id=first_ticket.id,
        suggestion="Add a few_shot example that matches the failed question pattern.",
        knowledge_types=["few_shot"],
    )
    analyzer = AsyncMock()
    analyzer.analyze.return_value = analysis_result
    apply_client = AsyncMock()
    apply_client.apply.return_value = {"ok": True}
    repository = MagicMock()
    repository.get_analysis.return_value = None

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
            suggestion="Add a few_shot example that matches the failed question pattern.",
            knowledge_types=["few_shot"],
        ),
        confidence=0.91,
        rationale="Prompt misses protocol-version mapping guidance",
        used_experiments=True,
        primary_knowledge_type="few_shot",
        secondary_knowledge_types=["business_knowledge"],
        candidate_patch_types=["few_shot", "business_knowledge"],
        validation_mode="lightweight",
        validation_result={"validated_patch_types": ["few_shot"], "rejected_patch_types": ["business_knowledge"]},
        diagnosis_context_summary={"failure_diff": {"entity_or_relation_problem": True}},
        applied=True,
        created_at="2026-04-13T00:00:00+00:00",
        applied_at="2026-04-13T00:00:01+00:00",
    )
    service = MagicMock()
    service.create_issue_ticket_response = AsyncMock()
    service.get_analysis.return_value = analysis
    monkeypatch.setattr("services.repair_agent.app.main.get_repair_service", lambda: service)

    with TestClient(app) as client:
        response = client.get("/api/v1/krss-analyses/analysis-ticket-001")

    assert response.status_code == 200
    assert response.json()["analysis_id"] == "analysis-ticket-001"
    assert response.json()["ticket_id"] == "ticket-001"


@pytest.mark.asyncio
async def test_repair_service_deterministic_diagnosis_uses_formal_contract_types_only():
    ticket = _make_issue_ticket()
    prompt_client = AsyncMock()
    prompt_client.fetch.return_value = PromptSnapshotResponse(
        id=ticket.id,
        input_prompt_snapshot="Original CGS prompt snapshot",
    )
    repository = MagicMock()
    repository.get_analysis.return_value = None
    apply_client = AsyncMock()
    apply_client.apply.return_value = {"ok": True}

    service = RepairService(
        repository=repository,
        prompt_snapshot_client=prompt_client,
        analyzer=KRSSAnalyzer(diagnosis_client=_DeterministicKRSSDiagnosisClient()),
        apply_client=apply_client,
    )

    response = await service.create_issue_ticket_response(ticket)

    apply_client.apply.assert_awaited_once()
    request = apply_client.apply.await_args.args[0]
    assert request.knowledge_types == ["few_shot"]
    assert response.knowledge_repair_request.knowledge_types == ["few_shot"]


@pytest.mark.asyncio
async def test_repair_service_propagates_primary_analyzer_timeout():
    ticket = _make_issue_ticket()
    prompt_client = AsyncMock()
    prompt_client.fetch.return_value = PromptSnapshotResponse(
        id=ticket.id,
        input_prompt_snapshot="Original CGS prompt snapshot",
    )
    repository = MagicMock()
    repository.get_analysis.return_value = None
    apply_client = AsyncMock()
    apply_client.apply.return_value = {"ok": True}
    analyzer = AsyncMock()
    analyzer.analyze.side_effect = TimeoutError("llm timeout")

    service = RepairService(
        repository=repository,
        prompt_snapshot_client=prompt_client,
        analyzer=analyzer,
        apply_client=apply_client,
    )

    with pytest.raises(TimeoutError, match="llm timeout"):
        await service.create_issue_ticket_response(ticket)

    apply_client.apply.assert_not_awaited()


def test_legacy_repair_plan_read_path_is_not_exposed():
    with TestClient(app) as client:
        response = client.get("/api/v1/repair-plans/analysis-ticket-001")

    assert response.status_code == 404
