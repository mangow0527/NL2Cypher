from __future__ import annotations

import asyncio
import pytest

from services.testing_agent.app.grammar import GrammarChecker
from services.repair_agent.app.models import RepairIssueTicketResponse
from services.testing_agent.app.models import ExecutionResult, GeneratedCypherSubmissionRequest, QAGoldenRequest
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

    async def review(self, **_: object) -> dict[str, str]:
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
        return RepairIssueTicketResponse(
            status="applied",
            analysis_id=f"analysis-{ticket.ticket_id}",
            id=ticket.id,
            knowledge_repair_request={
                "id": ticket.id,
                "suggestion": "Add relation guidance.",
                "knowledge_types": ["few_shot"],
            },
            knowledge_ops_response={"status": "ok"},
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
    }
    repair_response = RepairIssueTicketResponse.model_validate(latest["repair_response"])
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
async def test_repair_submission_failure_marks_state_after_receipt(tmp_path):
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
    latest = await wait_for_state(repository, "qa-fail", "repair_submission_failed")
    assert latest["state"] == "repair_submission_failed"


def test_testing_agent_models_do_not_export_legacy_submission_aliases():
    from services.testing_agent.app import models

    assert not hasattr(models, "EvaluationSubmissionRequest")
    assert not hasattr(models, "EvaluationSubmissionResponse")
