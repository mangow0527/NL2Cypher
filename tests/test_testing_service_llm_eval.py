from __future__ import annotations

import asyncio
import pytest

from services.repair_agent.app.models import KnowledgeRepairSuggestionRequest, RepairIssueTicketResponse
from services.testing_agent.app.clients import OpenAICompatibleLLMClient
from services.testing_agent.app.grammar import GrammarChecker
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


class StubRepairClient:
    async def submit_issue_ticket(self, ticket):
        return RepairIssueTicketResponse(
            status="applied",
            analysis_id=f"analysis-{ticket.ticket_id}",
            id=ticket.id,
            knowledge_repair_request=KnowledgeRepairSuggestionRequest(
                id=ticket.id,
                suggestion="Add a few-shot example for semantic mismatch cases.",
                knowledge_types=["few_shot"],
            ),
            applied=True,
        )


class StubTuGraphClient:
    def __init__(self, result: ExecutionResult) -> None:
        self.result = result

    async def execute(self, cypher: str) -> ExecutionResult:
        return self.result


class StubSemanticReviewer:
    def __init__(self, payload):
        self.payload = payload

    async def review(self, **_: object):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def build_service(tmp_path, semantic_payload, execution_rows):
    repository = TestingRepository(str(tmp_path / "testing"))
    service = TestingAgentService(
        repository=repository,
        repair_client=StubRepairClient(),
        tugraph_client=StubTuGraphClient(
            ExecutionResult(success=True, rows=execution_rows, row_count=len(execution_rows), error_message=None, elapsed_ms=1)
        ),
        grammar_checker=GrammarChecker(StubParser(success=True)),
        grammar_explainer=StubGrammarExplainer(),
        semantic_reviewer=StubSemanticReviewer(semantic_payload),
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
async def test_semantic_review_can_flip_strict_failure_to_pass(tmp_path):
    repository, service = build_service(
        tmp_path,
        semantic_payload={"judgement": "pass", "reasoning": "字段名不同但语义等价"},
        execution_rows=[{"total": 5}],
    )
    repository.save_golden(
        QAGoldenRequest(
            id="qa-semantic-pass",
            cypher="MATCH (n) RETURN count(n) AS count",
            answer=[{"count": 5}],
            difficulty="L3",
        )
    )

    await service.ingest_submission(
        GeneratedCypherSubmissionRequest(
            id="qa-semantic-pass",
            question="统计设备数量",
            generation_run_id="run-001",
            generated_cypher="MATCH (n) RETURN count(n) AS total",
            input_prompt_snapshot="prompt-1",
        )
    )

    latest = await wait_for_state(repository, "qa-semantic-pass", "passed")
    assert latest["evaluation"]["primary_metrics"]["execution_accuracy"]["reason"] == "semantic_equivalent"


@pytest.mark.asyncio
async def test_semantic_review_failure_keeps_verdict_fail(tmp_path):
    repository, service = build_service(
        tmp_path,
        semantic_payload={"judgement": "fail", "reasoning": "结果不等价"},
        execution_rows=[{"total": 4}],
    )
    repository.save_golden(
        QAGoldenRequest(
            id="qa-semantic-fail",
            cypher="MATCH (n) RETURN count(n) AS count",
            answer=[{"count": 5}],
            difficulty="L3",
        )
    )

    await service.ingest_submission(
        GeneratedCypherSubmissionRequest(
            id="qa-semantic-fail",
            question="统计设备数量",
            generation_run_id="run-001",
            generated_cypher="MATCH (n) RETURN count(n) AS total",
            input_prompt_snapshot="prompt-1",
        )
    )

    latest = await wait_for_state(repository, "qa-semantic-fail", "issue_ticket_created")
    assert latest["evaluation"]["primary_metrics"]["execution_accuracy"]["reason"] == "not_equivalent"


@pytest.mark.asyncio
async def test_semantic_review_failure_is_service_error_when_llm_step_is_required(tmp_path):
    repository, service = build_service(
        tmp_path,
        semantic_payload=RuntimeError("semantic llm offline"),
        execution_rows=[{"total": 4}],
    )
    repository.save_golden(
        QAGoldenRequest(
            id="qa-semantic-error",
            cypher="MATCH (n) RETURN count(n) AS count",
            answer=[{"count": 5}],
            difficulty="L3",
        )
    )

    receipt = await service.ingest_submission(
        GeneratedCypherSubmissionRequest(
            id="qa-semantic-error",
            question="统计设备数量",
            generation_run_id="run-001",
            generated_cypher="MATCH (n) RETURN count(n) AS total",
            input_prompt_snapshot="prompt-1",
        )
    )

    assert receipt.accepted is True
    latest = repository.get_submission("qa-semantic-error")
    assert latest is not None
    assert latest["state"] == "ready_to_evaluate"


@pytest.mark.asyncio
async def test_openai_compatible_llm_client_raises_on_invalid_json(monkeypatch):
    client = OpenAICompatibleLLMClient(
        base_url="https://example.com/v1",
        api_key="secret",
        model="glm-5",
        timeout_seconds=5,
        temperature=0.1,
    )

    class MockResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "not json"}}]}

    class MockClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            return MockResponse()

    monkeypatch.setattr("httpx.AsyncClient", lambda *args, **kwargs: MockClient())

    with pytest.raises(Exception):
        await client.complete_json("hello")


@pytest.mark.asyncio
async def test_semantic_review_client_accepts_result_correctness_alias(monkeypatch):
    from services.testing_agent.app.clients import OpenAICompatibleLLMClient, SemanticReviewClient

    llm = OpenAICompatibleLLMClient(
        base_url="https://example.com/v1",
        api_key="secret",
        model="glm-5",
        timeout_seconds=5,
        temperature=0.1,
    )

    async def fake_complete_json(prompt: str, *, qa_id=None, target="testing.llm"):
        return {"result_correctness": "pass", "reasoning": "语义一致"}

    monkeypatch.setattr(llm, "complete_json", fake_complete_json)

    payload = await SemanticReviewClient(llm).review(
        question="统计设备数量",
        gold_cypher="MATCH (n) RETURN count(n) AS count",
        gold_answer=[{"count": 5}],
        generated_cypher="MATCH (n) RETURN count(n) AS total",
        actual_answer=[{"total": 5}],
        strict_check_message="字段名不同",
        strict_diff={"missing_rows": [], "unexpected_rows": []},
    )

    assert payload["judgement"] == "pass"
    assert payload["reasoning"] == "语义一致"


@pytest.mark.asyncio
async def test_semantic_review_client_accepts_boolean_equivalence_alias(monkeypatch):
    from services.testing_agent.app.clients import OpenAICompatibleLLMClient, SemanticReviewClient

    llm = OpenAICompatibleLLMClient(
        base_url="https://example.com/v1",
        api_key="secret",
        model="glm-5",
        timeout_seconds=5,
        temperature=0.1,
    )

    async def fake_complete_json(prompt: str, *, qa_id=None, target="testing.llm"):
        return {"is_equivalent": False, "reasoning": "结果不满足问题"}

    monkeypatch.setattr(llm, "complete_json", fake_complete_json)

    payload = await SemanticReviewClient(llm).review(
        question="统计设备数量",
        gold_cypher="MATCH (n) RETURN count(n) AS count",
        gold_answer=[{"count": 5}],
        generated_cypher="MATCH (n) RETURN count(n) AS total",
        actual_answer=[{"total": 4}],
        strict_check_message="数量不一致",
        strict_diff={"missing_rows": [{"count": 5}], "unexpected_rows": [{"total": 4}]},
    )

    assert payload["judgement"] == "fail"
