from __future__ import annotations

import asyncio
import pytest

from services.testing_agent.app.grammar import GrammarChecker
from services.testing_agent.app.models import (
    CgaGenerationNonSuccessReport,
    CgaQuestionReceivedReport,
    ExecutionResult,
    GeneratedCypherSubmissionRequest,
    QAGoldenRequest,
    RepairAgentResponse,
)
from services.testing_agent.app.repository import TestingRepository
from services.testing_agent.app.service import TestingAgentService


class StubParser:
    def __init__(self, *, success: bool, parser_error: str | None = None) -> None:
        self.success = success
        self.parser_error = parser_error

    def parse(self, query: str) -> tuple[bool, str | None]:
        return self.success, self.parser_error


class StubGrammarExplainer:
    async def explain(self, generated_cypher: str, parser_error: str) -> str:
        return f"解释: {parser_error}"


class StubSemanticReviewer:
    def __init__(self, payload: dict[str, str] | Exception) -> None:
        self.payload = payload
        self.calls = 0

    async def review(self, **_: object) -> dict[str, str]:
        self.calls += 1
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class StubRepairClient:
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.tickets = []

    async def submit_issue_ticket(self, ticket):
        self.tickets.append(ticket)
        if self.should_fail:
            raise RuntimeError("repair offline")
        return RepairAgentResponse(
            status="applied",
            analysis_id=f"analysis-{ticket.ticket_id}",
            id=ticket.id,
            knowledge_repair_request={
                "id": ticket.id,
                "suggestion": "Add relation guidance.",
                "knowledge_types": ["few_shot"],
            },
            knowledge_agent_response={"status": "ok"},
            applied=True,
        )


class StubTuGraphClient:
    def __init__(self, result: ExecutionResult) -> None:
        self.result = result

    async def execute(self, cypher: str) -> ExecutionResult:
        return self.result


def make_service(
    tmp_path,
    *,
    parser_success: bool,
    parser_error: str | None = None,
    execution_result: ExecutionResult | None = None,
    semantic_payload: dict[str, str] | Exception | None = None,
    repair_should_fail: bool = False,
):
    repository = TestingRepository(str(tmp_path / "testing"))
    service = TestingAgentService(
        repository=repository,
        repair_client=StubRepairClient(should_fail=repair_should_fail),
        tugraph_client=StubTuGraphClient(execution_result or ExecutionResult(success=True, rows=[], row_count=0, error_message=None, elapsed_ms=1)),
        grammar_checker=GrammarChecker(StubParser(success=parser_success, parser_error=parser_error)),
        grammar_explainer=StubGrammarExplainer(),
        semantic_reviewer=StubSemanticReviewer(semantic_payload or {"judgement": "fail", "reasoning": "不等价"}),
        settings=type("Settings", (), {"data_dir": str(tmp_path / "testing"), "repair_service_url": "http://repair", "llm_model": "test-model", "llm_enabled": True})(),
    )
    return repository, service


async def wait_for_state(repository: TestingRepository, qa_id: str, expected_state: str) -> dict:
    for _ in range(20):
        latest = repository.get_submission(qa_id)
        if latest is not None and latest["state"] == expected_state:
            return latest
        await asyncio.sleep(0.01)
    raise AssertionError(f"Timed out waiting for submission state {expected_state!r} for qa_id={qa_id}")


async def wait_for_repair_response(repository: TestingRepository, qa_id: str) -> dict:
    for _ in range(20):
        latest = repository.get_submission(qa_id)
        if latest is not None and latest.get("repair_response") is not None:
            return latest
        await asyncio.sleep(0.01)
    raise AssertionError(f"Timed out waiting for repair response for qa_id={qa_id}")


@pytest.mark.asyncio
async def test_failed_submission_includes_minimal_generation_evidence_in_issue_ticket(tmp_path):
    repository, service = make_service(
        tmp_path,
        parser_success=False,
        parser_error="Unexpected token RETURN",
    )
    repository.save_golden(
        QAGoldenRequest(id="qa-001", cypher="MATCH (n) RETURN n", answer=[{"id": "a"}], difficulty="L3")
    )

    receipt = await service.ingest_submission(
        GeneratedCypherSubmissionRequest(
            id="qa-001",
            question="查询设备",
            generation_run_id="run-001",
            generated_cypher="MATCHH (n) RETURN n",
            input_prompt_snapshot="prompt-1",
        )
    )

    assert receipt.accepted is True
    latest = await wait_for_state(repository, "qa-001", "issue_ticket_created")
    ticket = repository.get_issue_ticket("ticket-qa-001-attempt-1")
    assert ticket is not None
    assert ticket.generation_evidence.model_dump() == {
        "generation_run_id": "run-001",
        "attempt_no": 1,
        "input_prompt_snapshot": "prompt-1",
        "generation_status": "generated",
        "failure_reason": None,
    }
    latest_with_repair = await wait_for_repair_response(repository, "qa-001")
    repair_response = RepairAgentResponse.model_validate(latest_with_repair["repair_response"])
    assert repair_response.analysis_id == "analysis-ticket-qa-001-attempt-1"
    assert repair_response.knowledge_repair_request.knowledge_types == ["few_shot"]


@pytest.mark.asyncio
async def test_duplicate_submission_reuses_existing_attempt_without_creating_new_one(tmp_path):
    repository, service = make_service(
        tmp_path,
        parser_success=True,
        execution_result=ExecutionResult(success=True, rows=[{"id": "a"}], row_count=1, error_message=None, elapsed_ms=1),
    )
    repository.save_golden(
        QAGoldenRequest(id="qa-dup", cypher="MATCH (n) RETURN n", answer=[{"id": "a"}], difficulty="L3")
    )
    request = GeneratedCypherSubmissionRequest(
        id="qa-dup",
        question="查询设备",
        generation_run_id="run-001",
        generated_cypher="MATCH (n) RETURN n",
        input_prompt_snapshot="prompt-1",
    )

    first = await service.ingest_submission(request)
    duplicate = await service.ingest_submission(request)

    assert first.accepted is True
    assert duplicate.accepted is True
    await wait_for_state(repository, "qa-dup", "passed")
    assert len(repository.list_submission_attempts("qa-dup")) == 1


@pytest.mark.asyncio
async def test_repair_submission_failure_does_not_downgrade_issue_ticket_state(tmp_path):
    repository, service = make_service(
        tmp_path,
        parser_success=False,
        parser_error="Unexpected token RETURN",
        repair_should_fail=True,
    )
    repository.save_golden(
        QAGoldenRequest(id="qa-fail", cypher="MATCH (n) RETURN n", answer=[{"id": "a"}], difficulty="L3")
    )

    receipt = await service.ingest_submission(
        GeneratedCypherSubmissionRequest(
            id="qa-fail",
            question="查询设备",
            generation_run_id="run-001",
            generated_cypher="MATCHH (n) RETURN n",
            input_prompt_snapshot="prompt-1",
        )
    )

    assert receipt.accepted is True
    latest = await wait_for_state(repository, "qa-fail", "issue_ticket_created")
    assert latest["state"] == "issue_ticket_created"
    assert latest["issue_ticket_id"] == "ticket-qa-fail-attempt-1"


@pytest.mark.asyncio
async def test_concurrent_evaluation_for_same_attempt_runs_once(tmp_path):
    repository, service = make_service(
        tmp_path,
        parser_success=True,
        execution_result=ExecutionResult(success=True, rows=[{"id": "actual"}], row_count=1, error_message=None, elapsed_ms=1),
        semantic_payload={"judgement": "pass", "reasoning": "语义等价"},
    )
    repository.save_golden(
        QAGoldenRequest(id="qa-concurrent", cypher="MATCH (n) RETURN n", answer=[{"id": "gold"}], difficulty="L3")
    )
    request = GeneratedCypherSubmissionRequest(
        id="qa-concurrent",
        question="查询设备",
        generation_run_id="run-001",
        generated_cypher="MATCH (n) RETURN n",
        input_prompt_snapshot="prompt-1",
    )
    saved = repository.save_submission(request, state="ready_to_evaluate")

    await asyncio.gather(
        service._evaluate_attempt("qa-concurrent", saved.attempt_no),
        service._evaluate_attempt("qa-concurrent", saved.attempt_no),
    )

    latest = repository.get_submission("qa-concurrent")
    assert latest is not None
    assert latest["state"] == "passed"
    assert latest["issue_ticket_id"] is None
    assert service.semantic_reviewer.calls == 1


@pytest.mark.asyncio
async def test_generation_failed_duplicate_reuses_existing_attempt_and_preserves_failure_evidence(tmp_path):
    repository, service = make_service(
        tmp_path,
        parser_success=True,
        execution_result=ExecutionResult(success=True, rows=[{"id": "a"}], row_count=1, error_message=None, elapsed_ms=1),
    )
    repository.save_golden(
        QAGoldenRequest(id="qa-gen-dup", cypher="MATCH (n) RETURN n", answer=[{"id": "a"}], difficulty="L3")
    )
    report = CgaGenerationNonSuccessReport(
        id="qa-gen-dup",
        question="查询设备",
        generation_run_id="run-gen-failed",
        input_prompt_snapshot="prompt-1",
        generation_status="generation_failed",
        failure_reason="no_cypher_found",
        parsed_cypher="",
        gate_passed=False,
    )

    first = await service.ingest_generation_failure(report)
    duplicate = await service.ingest_generation_failure(report)

    assert first.accepted is True
    assert duplicate.accepted is True
    latest = await wait_for_state(repository, "qa-gen-dup", "issue_ticket_created")
    assert len(repository.list_submission_attempts("qa-gen-dup")) == 1
    assert latest["generation_status"] == "generation_failed"
    assert latest["failure_reason"] == "no_cypher_found"
    assert latest["generated_cypher"] == ""


def test_testing_agent_models_do_not_export_legacy_submission_aliases():
    from services.testing_agent.app import models

    assert not hasattr(models, "EvaluationSubmissionRequest")
    assert not hasattr(models, "EvaluationSubmissionResponse")


@pytest.mark.asyncio
async def test_service_failed_report_is_visible_in_evaluation_status(tmp_path):
    repository, service = make_service(tmp_path, parser_success=True)
    report = CgaGenerationNonSuccessReport(
        id="qa-service-failed",
        question="查询设备",
        generation_run_id="run-service-failed",
        input_prompt_snapshot="",
        generation_status="service_failed",
        failure_reason="model_invocation_failed",
        parsed_cypher=None,
        gate_passed=False,
    )

    await service.ingest_generation_failure(report)

    status = service.get_evaluation_status("qa-service-failed")
    assert status.attempts == []
    assert status.generation_failures[0]["generation_status"] == "service_failed"
    assert status.generation_failures[0]["failure_reason"] == "model_invocation_failed"


@pytest.mark.asyncio
async def test_question_received_report_is_visible_until_generation_finishes(tmp_path):
    repository, service = make_service(tmp_path, parser_success=True)
    report = CgaQuestionReceivedReport(
        id="qa-pending",
        question="查询服务使用的隧道",
        generation_run_id="run-pending",
    )

    receipt = await service.ingest_question_received(report)
    golden_response = await service.ingest_golden(
        QAGoldenRequest(
            id="qa-pending",
            cypher="MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel) RETURN t.name AS name",
            answer=[],
            difficulty="L3",
        )
    )

    assert receipt.accepted is True
    assert golden_response.status == "generation_pending"
    status = service.get_evaluation_status("qa-pending")
    assert status.question_receipt is not None
    assert status.question_receipt["generation_status"] == "generation_pending"
    assert status.question_receipt["generation_run_id"] == "run-pending"
    assert status.attempts == []


@pytest.mark.asyncio
async def test_clarification_report_is_visible_without_creating_attempt(tmp_path):
    repository, service = make_service(tmp_path, parser_success=True)
    report = CgaGenerationNonSuccessReport(
        id="qa-clarify",
        question="查询服务 A 对应的网元",
        generation_run_id="run-clarify",
        generation_status="clarification_required",
        input_prompt_snapshot='{"schema_version":"cga_trace_v2"}',
        clarification={
            "source_stage": "semantic_view_matching",
            "reason_code": "ambiguous_path_semantic",
            "question_zh": "你说的对应网元是指源网元还是目的网元？",
            "expected_answer_type": "single_choice",
            "options": [{"id": "source", "label": "源网元"}],
        },
    )

    receipt = await service.ingest_generation_failure(report)

    assert receipt.accepted is True
    status = service.get_evaluation_status("qa-clarify")
    assert status.attempts == []
    assert status.generation_failures[0]["generation_status"] == "clarification_required"
    assert status.generation_failures[0]["clarification"]["reason_code"] == "ambiguous_path_semantic"
