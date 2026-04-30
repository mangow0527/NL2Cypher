from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
import pytest

from services.repair_agent.app.analysis import RepairAnalyzer
from services.repair_agent.app.main import app
from services.repair_agent.app.models import KnowledgeRepairSuggestionRequest, RepairAnalysisRecord, RepairIssueTicketResponse
from services.repair_agent.app.service import RepairService
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


class _DeterministicRepairDiagnosisClient:
    async def diagnose(self, context: dict[str, object]) -> dict[str, object]:
        failure_diff = context["failure_diff"]
        if failure_diff["syntax_problem"]:
            return {
                "primary_knowledge_type": "cypher_syntax",
                "secondary_knowledge_types": ["system_prompt"],
                "confidence": 0.9,
                "suggestion": "Add Cypher syntax guardrails and parser-oriented examples.",
                "rationale": "The parser failed before semantic evaluation.",
            }

        if failure_diff["entity_or_relation_problem"]:
            return {
                "primary_knowledge_type": "few_shot",
                "secondary_knowledge_types": ["business_knowledge"],
                "confidence": 0.85,
                "suggestion": "Add a few_shot example that matches the failed question pattern.",
                "rationale": "The query missed the intended relation path.",
            }

        return {
            "primary_knowledge_type": "system_prompt",
            "secondary_knowledge_types": [],
            "confidence": 0.8,
            "suggestion": "Tighten the system prompt so future generations preserve the output contract.",
            "rationale": "Fallback deterministic diagnosis.",
        }


def _make_issue_ticket() -> IssueTicket:
    return IssueTicket(
        ticket_id="ticket-001",
        id="q-001",
        difficulty="L3",
        question="查询协议版本对应的隧道",
        expected=ExpectedPayload(cypher="MATCH (t:Tunnel) RETURN t.name AS tunnel_name", answer=[{"tunnel_name": "tunnel-1"}]),
        actual=ActualPayload(
            generated_cypher="MATCH (t:Tunnel) RETURN t",
            execution=ExecutionResult(
                success=True,
                rows=[{"name": "wrong-tunnel"}],
                row_count=1,
                error_message=None,
                elapsed_ms=12,
            ),
        ),
        evaluation=EvaluationSummary(
            verdict="fail",
            primary_metrics=PrimaryMetrics(
                grammar=GrammarMetric(score=1, parser_error=None, message=None),
                execution_accuracy=ExecutionAccuracy(
                    score=0,
                    reason="not_equivalent",
                    strict_check=StrictCheck(
                        status="fail",
                        message="Wrong tunnel returned",
                        order_sensitive=False,
                        expected_row_count=1,
                        actual_row_count=1,
                    ),
                    semantic_check=SemanticCheck(
                        status="fail",
                        message="The generated query missed the protocol-version relation.",
                        raw_output=None,
                    ),
                ),
            ),
            secondary_signals=SecondarySignals(
                gleu=GLEUSignal(score=0.42, tokenizer="whitespace", min_n=1, max_n=4),
                jaro_winkler_similarity=JaroWinklerSimilaritySignal(
                    score=0.73,
                    normalization="lightweight",
                    library="jellyfish",
                ),
            ),
        ),
        generation_evidence=GenerationEvidence(
            generation_run_id="run-001",
            attempt_no=1,
            input_prompt_snapshot="GenerationEvidence prompt snapshot from Testing Service",
        ),
    )


def test_issue_ticket_route_returns_formal_repair_response(monkeypatch):
    ticket = _make_issue_ticket()
    service = MagicMock()
    service.create_issue_ticket_response = AsyncMock(
        return_value=RepairIssueTicketResponse(
            status="applied",
            analysis_id="analysis-ticket-001",
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
        "analysis_id": "analysis-ticket-001",
        "id": "q-001",
        "knowledge_repair_request": {
            "id": "q-001",
            "suggestion": "Add a few_shot example that matches the failed question pattern.",
            "knowledge_types": ["few_shot"],
        },
        "knowledge_agent_response": None,
        "applied": True,
    }


@pytest.mark.asyncio
async def test_repair_service_uses_prompt_snapshot_embedded_in_issue_ticket():
    ticket = _make_issue_ticket()
    analysis_result = MagicMock()
    analysis_result.id = ticket.id
    analysis_result.confidence = 0.91
    analysis_result.rationale = "Prompt misses protocol-version mapping guidance"
    analysis_result.primary_knowledge_type = "few_shot"
    analysis_result.secondary_knowledge_types = ["business_knowledge"]
    analysis_result.diagnosis_context_summary = {"failure_diff": {"entity_or_relation_problem": True}}
    analysis_result.system_prompt_snapshot = "SYSTEM PROMPT SNAPSHOT"
    analysis_result.user_prompt_snapshot = "USER PROMPT SNAPSHOT"
    analysis_result.raw_output = '{"repairable": true}'
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
        analyzer=analyzer,
        apply_client=apply_client,
    )

    response = await service.create_issue_ticket_response(ticket)

    analyzer.analyze.assert_awaited_once_with(ticket, "GenerationEvidence prompt snapshot from Testing Service")
    apply_client.apply.assert_awaited_once_with(
        KnowledgeRepairSuggestionRequest(
            id=ticket.id,
            suggestion="Add a few_shot example that matches the failed question pattern.",
            knowledge_types=["few_shot"],
        )
    )
    assert repository.save_analysis.call_count == 2
    saved_record = repository.save_analysis.call_args_list[-1].args[0]
    assert saved_record.prompt_snapshot == "GenerationEvidence prompt snapshot from Testing Service"
    assert saved_record.system_prompt_snapshot == "SYSTEM PROMPT SNAPSHOT"
    assert saved_record.user_prompt_snapshot == "USER PROMPT SNAPSHOT"
    assert saved_record.raw_output == '{"repairable": true}'
    assert response == RepairIssueTicketResponse(
        status="applied",
        analysis_id="analysis-ticket-001",
        id=ticket.id,
        knowledge_repair_request=KnowledgeRepairSuggestionRequest(
            id=ticket.id,
            suggestion="Add a few_shot example that matches the failed question pattern.",
            knowledge_types=["few_shot"],
        ),
        knowledge_agent_response={"ok": True},
        applied=True,
    )


@pytest.mark.asyncio
async def test_repair_service_persists_analysis_before_apply_failure():
    ticket = _make_issue_ticket()
    analysis_result = MagicMock()
    analysis_result.id = ticket.id
    analysis_result.confidence = 0.91
    analysis_result.rationale = "Prompt misses protocol-version mapping guidance"
    analysis_result.primary_knowledge_type = "few_shot"
    analysis_result.secondary_knowledge_types = ["business_knowledge"]
    analysis_result.diagnosis_context_summary = {"failure_diff": {"entity_or_relation_problem": True}}
    analysis_result.system_prompt_snapshot = "SYSTEM PROMPT SNAPSHOT"
    analysis_result.user_prompt_snapshot = "USER PROMPT SNAPSHOT"
    analysis_result.raw_output = '{"repairable": true}'
    analysis_result.to_request.return_value = KnowledgeRepairSuggestionRequest(
        id=ticket.id,
        suggestion="Add a few_shot example that matches the failed question pattern.",
        knowledge_types=["few_shot"],
    )
    analyzer = AsyncMock()
    analyzer.analyze.return_value = analysis_result
    apply_client = AsyncMock()
    apply_client.apply.side_effect = RuntimeError("apply blocked")
    repository = MagicMock()
    repository.get_analysis.return_value = None

    service = RepairService(
        repository=repository,
        analyzer=analyzer,
        apply_client=apply_client,
    )

    with pytest.raises(RuntimeError, match="apply blocked"):
        await service.create_issue_ticket_response(ticket)

    assert repository.save_analysis.call_count == 2
    pending_record = repository.save_analysis.call_args_list[0].args[0]
    saved_record = repository.save_analysis.call_args_list[-1].args[0]
    assert pending_record.status == "analysis_pending"
    assert pending_record.applied is False
    assert saved_record.status == "apply_failed"
    assert saved_record.prompt_snapshot == "GenerationEvidence prompt snapshot from Testing Service"
    assert saved_record.system_prompt_snapshot == "SYSTEM PROMPT SNAPSHOT"
    assert saved_record.user_prompt_snapshot == "USER PROMPT SNAPSHOT"
    assert saved_record.raw_output == '{"repairable": true}'
    assert saved_record.knowledge_agent_response is None
    assert saved_record.applied is False


@pytest.mark.asyncio
async def test_repair_service_returns_paused_when_knowledge_agent_apply_is_disabled():
    ticket = _make_issue_ticket()
    analysis_result = MagicMock()
    analysis_result.id = ticket.id
    analysis_result.confidence = 0.91
    analysis_result.rationale = "Knowledge repair is valid but apply is disabled."
    analysis_result.primary_knowledge_type = "business_knowledge"
    analysis_result.secondary_knowledge_types = []
    analysis_result.diagnosis_context_summary = {"failure_diff": {"entity_or_relation_problem": True}}
    analysis_result.system_prompt_snapshot = "SYSTEM PROMPT SNAPSHOT"
    analysis_result.user_prompt_snapshot = "USER PROMPT SNAPSHOT"
    analysis_result.raw_output = '{"repairable": true}'
    analysis_result.to_request.return_value = KnowledgeRepairSuggestionRequest(
        id=ticket.id,
        suggestion="Add business knowledge for disabled apply scenario.",
        knowledge_types=["business_knowledge"],
    )
    analyzer = AsyncMock()
    analyzer.analyze.return_value = analysis_result
    apply_client = AsyncMock()
    apply_client.apply.return_value = {
        "status": "paused",
        "code": "KNOWLEDGE_REPAIR_APPLY_DISABLED",
        "message": "Knowledge repair apply is disabled.",
    }
    repository = MagicMock()
    repository.get_analysis.return_value = None

    service = RepairService(
        repository=repository,
        analyzer=analyzer,
        apply_client=apply_client,
    )

    response = await service.create_issue_ticket_response(ticket)

    assert response.status == "repair_apply_paused"
    assert response.applied is False
    assert response.knowledge_agent_response == {
        "status": "paused",
        "code": "KNOWLEDGE_REPAIR_APPLY_DISABLED",
        "message": "Knowledge repair apply is disabled.",
    }
    assert repository.save_analysis.call_count == 2
    saved_record = repository.save_analysis.call_args_list[-1].args[0]
    assert saved_record.status == "repair_apply_paused"
    assert saved_record.applied is False
    assert saved_record.applied_at == ""
    assert saved_record.knowledge_agent_response == response.knowledge_agent_response


@pytest.mark.asyncio
async def test_repair_service_is_idempotent_when_analysis_exists():
    ticket = _make_issue_ticket()
    existing = RepairAnalysisRecord(
        analysis_id="analysis-ticket-001",
        ticket_id="ticket-001",
        id=ticket.id,
        status="applied",
        prompt_snapshot="cached prompt",
        system_prompt_snapshot="cached system prompt",
        user_prompt_snapshot="cached user prompt",
        knowledge_repair_request=KnowledgeRepairSuggestionRequest(
            id=ticket.id,
            suggestion="cached suggestion",
            knowledge_types=["system_prompt"],
        ),
        knowledge_agent_response={"ok": True},
        confidence=0.9,
        rationale="cached",
        primary_knowledge_type="system_prompt",
        secondary_knowledge_types=[],
        diagnosis_context_summary={},
        applied=True,
        created_at="2026-01-01T00:00:00Z",
        applied_at="2026-01-01T00:00:00Z",
    )

    analyzer = AsyncMock()
    apply_client = AsyncMock()
    repository = MagicMock()
    repository.get_analysis.return_value = existing

    service = RepairService(
        repository=repository,
        analyzer=analyzer,
        apply_client=apply_client,
    )

    response = await service.create_issue_ticket_response(ticket)

    analyzer.analyze.assert_not_called()
    apply_client.apply.assert_not_called()
    assert response == RepairIssueTicketResponse(
        status="applied",
        analysis_id=existing.analysis_id,
        id=existing.id,
        knowledge_repair_request=existing.knowledge_repair_request,
        knowledge_agent_response=existing.knowledge_agent_response,
        applied=True,
    )


@pytest.mark.asyncio
async def test_repair_service_uses_ticket_scoped_analysis_id_uniqueness():
    first_ticket = _make_issue_ticket()
    second_ticket = _make_issue_ticket().model_copy(deep=True)
    second_ticket.ticket_id = "ticket-002"
    second_ticket.generation_evidence = GenerationEvidence(
        generation_run_id="run-002",
        attempt_no=2,
        input_prompt_snapshot="second ticket prompt snapshot",
    )

    analysis_result = MagicMock()
    analysis_result.id = first_ticket.id
    analysis_result.confidence = 0.91
    analysis_result.rationale = "Prompt misses protocol-version mapping guidance"
    analysis_result.primary_knowledge_type = "few_shot"
    analysis_result.secondary_knowledge_types = ["business_knowledge"]
    analysis_result.diagnosis_context_summary = {"failure_diff": {"entity_or_relation_problem": True}}
    analysis_result.system_prompt_snapshot = "SYSTEM PROMPT SNAPSHOT"
    analysis_result.user_prompt_snapshot = "USER PROMPT SNAPSHOT"
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
        analyzer=analyzer,
        apply_client=apply_client,
    )

    first_response = await service.create_issue_ticket_response(first_ticket)
    second_response = await service.create_issue_ticket_response(second_ticket)

    assert first_response.analysis_id == "analysis-ticket-001"
    assert second_response.analysis_id == "analysis-ticket-002"
    assert first_response.analysis_id != second_response.analysis_id


def test_get_repair_analysis_endpoint_returns_record(monkeypatch):
    analysis = RepairAnalysisRecord(
        analysis_id="analysis-ticket-001",
        ticket_id="ticket-001",
        id="q-001",
        status="applied",
        prompt_snapshot="Prompt snapshot from testing-agent",
        system_prompt_snapshot="System prompt snapshot from repair-agent",
        user_prompt_snapshot="User prompt snapshot from repair-agent",
        knowledge_repair_request=KnowledgeRepairSuggestionRequest(
            id="q-001",
            suggestion="Add a few_shot example that matches the failed question pattern.",
            knowledge_types=["few_shot"],
        ),
        confidence=0.91,
        rationale="Prompt misses protocol-version mapping guidance",
        primary_knowledge_type="few_shot",
        secondary_knowledge_types=["business_knowledge"],
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
        response = client.get("/api/v1/analyses/analysis-ticket-001")

    assert response.status_code == 200
    assert response.json()["analysis_id"] == "analysis-ticket-001"
    assert response.json()["ticket_id"] == "ticket-001"


@pytest.mark.asyncio
async def test_repair_service_deterministic_diagnosis_uses_formal_contract_types_only():
    ticket = _make_issue_ticket()
    repository = MagicMock()
    repository.get_analysis.return_value = None
    apply_client = AsyncMock()
    apply_client.apply.return_value = {"ok": True}

    service = RepairService(
        repository=repository,
        analyzer=RepairAnalyzer(diagnosis_client=_DeterministicRepairDiagnosisClient()),
        apply_client=apply_client,
    )

    response = await service.create_issue_ticket_response(ticket)

    apply_client.apply.assert_awaited_once()
    request = apply_client.apply.await_args.args[0]
    assert request.knowledge_types == ["few_shot"]
    assert response.knowledge_repair_request.knowledge_types == ["few_shot"]


@pytest.mark.asyncio
async def test_repair_service_marks_record_applied_only_after_apply_success():
    ticket = _make_issue_ticket()
    analysis_result = MagicMock()
    analysis_result.id = ticket.id
    analysis_result.confidence = 0.91
    analysis_result.rationale = "Prompt misses protocol-version mapping guidance"
    analysis_result.primary_knowledge_type = "few_shot"
    analysis_result.secondary_knowledge_types = ["business_knowledge"]
    analysis_result.diagnosis_context_summary = {"failure_diff": {"entity_or_relation_problem": True}}
    analysis_result.system_prompt_snapshot = "SYSTEM PROMPT SNAPSHOT"
    analysis_result.user_prompt_snapshot = "USER PROMPT SNAPSHOT"
    analysis_result.repairable = True
    analysis_result.non_repairable_reason = ""
    analysis_result.to_request.return_value = KnowledgeRepairSuggestionRequest(
        id=ticket.id,
        suggestion="Add a few_shot example that matches the failed question pattern.",
        knowledge_types=["few_shot"],
    )
    analyzer = AsyncMock()
    analyzer.analyze.return_value = analysis_result
    repository = MagicMock()
    repository.get_analysis.return_value = None

    async def apply_after_pending_record(_request):
        pending_record = repository.save_analysis.call_args.args[0]
        assert pending_record.status == "analysis_pending"
        assert pending_record.applied is False
        return {"ok": True}

    apply_client = AsyncMock()
    apply_client.apply.side_effect = apply_after_pending_record

    service = RepairService(
        repository=repository,
        analyzer=analyzer,
        apply_client=apply_client,
    )

    response = await service.create_issue_ticket_response(ticket)

    assert response.status == "applied"
    assert response.applied is True
    assert repository.save_analysis.call_count == 2
    final_record = repository.save_analysis.call_args_list[-1].args[0]
    assert final_record.status == "applied"
    assert final_record.applied is True


@pytest.mark.asyncio
async def test_repair_service_skips_apply_for_non_repairable_diagnosis():
    ticket = _make_issue_ticket()
    analysis_result = MagicMock()
    analysis_result.id = ticket.id
    analysis_result.confidence = 0.88
    analysis_result.rationale = "The failure points to testing-agent evaluator behavior."
    analysis_result.primary_knowledge_type = "system_prompt"
    analysis_result.secondary_knowledge_types = []
    analysis_result.diagnosis_context_summary = {"failure_diff": {"syntax_problem": False}}
    analysis_result.system_prompt_snapshot = "SYSTEM PROMPT SNAPSHOT"
    analysis_result.user_prompt_snapshot = "USER PROMPT SNAPSHOT"
    analysis_result.repairable = False
    analysis_result.non_repairable_reason = "testing-agent evaluator bug"
    analyzer = AsyncMock()
    analyzer.analyze.return_value = analysis_result
    apply_client = AsyncMock()
    repository = MagicMock()
    repository.get_analysis.return_value = None

    service = RepairService(
        repository=repository,
        analyzer=analyzer,
        apply_client=apply_client,
    )

    response = await service.create_issue_ticket_response(ticket)

    apply_client.apply.assert_not_awaited()
    repository.save_analysis.assert_called_once()
    saved_record = repository.save_analysis.call_args.args[0]
    assert saved_record.status == "not_repairable"
    assert saved_record.applied is False
    assert saved_record.knowledge_repair_request is None
    assert saved_record.non_repairable_reason == "testing-agent evaluator bug"
    assert response.status == "not_repairable"
    assert response.applied is False
    assert response.knowledge_repair_request is None


@pytest.mark.asyncio
async def test_repair_service_propagates_primary_analyzer_timeout():
    ticket = _make_issue_ticket()
    repository = MagicMock()
    repository.get_analysis.return_value = None
    apply_client = AsyncMock()
    apply_client.apply.return_value = {"ok": True}
    analyzer = AsyncMock()
    analyzer.analyze.side_effect = TimeoutError("llm timeout")

    service = RepairService(
        repository=repository,
        analyzer=analyzer,
        apply_client=apply_client,
    )

    with pytest.raises(TimeoutError, match="llm timeout"):
        await service.create_issue_ticket_response(ticket)

    apply_client.apply.assert_not_awaited()


def test_health_and_status_routes_follow_repair_agent_contract(monkeypatch):
    service = MagicMock()
    service.get_service_status.return_value = {
        "storage": "/tmp/repair",
        "knowledge_agent_apply_url": "http://knowledge-agent/api/v1/repairs/apply",
        "llm_enabled": True,
        "llm_model": "glm-5",
        "llm_configured": True,
        "mode": "repair_apply",
        "diagnosis_mode": "llm",
    }
    monkeypatch.setattr("services.repair_agent.app.main.get_repair_service", lambda: service)

    with TestClient(app) as client:
        health = client.get("/health")
        status = client.get("/api/v1/status")

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "service": "repair-agent"}
    assert status.status_code == 200
    assert status.json()["mode"] == "repair_apply"
    assert "knowledge_agent_apply_url" in status.json()


def test_repair_service_constructor_exposes_current_dependencies_only():
    signature = inspect.signature(RepairService)

    assert "prompt_snapshot_client" not in signature.parameters


def test_repair_agent_models_export_current_response_contract_only():
    from services.repair_agent.app.models import RepairIssueTicketResponse

    assert set(RepairIssueTicketResponse.model_fields) == {
        "status",
        "analysis_id",
        "id",
        "knowledge_repair_request",
        "knowledge_agent_response",
        "applied",
    }
