from __future__ import annotations

import asyncio
import pytest

from services.testing_agent.app.clients import InvalidSemanticReviewResponse, OpenAIChatCompletionLLMClient
from services.testing_agent.app.grammar import GrammarChecker
from services.testing_agent.app.models import (
    ExecutionResult,
    GeneratedCypherSubmissionRequest,
    GenerationRunFailureReport,
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


class StubRepairClient:
    async def submit_issue_ticket(self, ticket):
        return RepairAgentResponse(
            status="applied",
            analysis_id=f"analysis-{ticket.ticket_id}",
            id=ticket.id,
            knowledge_repair_request={
                "id": ticket.id,
                "suggestion": "Add a few-shot example for semantic mismatch cases.",
                "knowledge_types": ["few_shot"],
            },
            applied=True,
        )


class StubTuGraphClient:
    def __init__(self, result: ExecutionResult) -> None:
        self.result = result

    async def execute(self, cypher: str) -> ExecutionResult:
        return self.result


class FailingTuGraphClient:
    async def execute(self, cypher: str) -> ExecutionResult:
        raise RuntimeError("tugraph offline")


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
            last_llm_raw_output="MATCH (n) RETURN count(n) AS total",
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
            last_llm_raw_output="MATCH (n) RETURN count(n) AS total",
        )
    )

    latest = await wait_for_state(repository, "qa-semantic-fail", "issue_ticket_created")
    assert latest["evaluation"]["primary_metrics"]["execution_accuracy"]["reason"] == "not_equivalent"


@pytest.mark.asyncio
async def test_semantic_review_failure_is_service_error_when_llm_step_is_required(tmp_path):
    class InvalidSemanticReviewer:
        async def review(self, **_: object):
            raise InvalidSemanticReviewResponse(
                raw_text='{"verdict":"fail","reason":"结果不等价"}',
                payload={"verdict": "fail", "reason": "结果不等价"},
                request_id="req-semantic-invalid-001",
                model="glm-5.1",
                prompt_snapshot="Question:\n统计设备数量\n\nStrict Diff:\n{}",
                message="Semantic review returned invalid judgement.",
            )

    repository = TestingRepository(str(tmp_path / "testing"))
    service = TestingAgentService(
        repository=repository,
        repair_client=StubRepairClient(),
        tugraph_client=StubTuGraphClient(
            ExecutionResult(success=True, rows=[{"total": 4}], row_count=1, error_message=None, elapsed_ms=1)
        ),
        grammar_checker=GrammarChecker(StubParser(success=True)),
        grammar_explainer=StubGrammarExplainer(),
        semantic_reviewer=InvalidSemanticReviewer(),
        settings=type("Settings", (), {"data_dir": str(tmp_path / "testing"), "repair_service_url": "http://repair", "llm_model": "test-model", "llm_enabled": True})(),
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
            last_llm_raw_output="MATCH (n) RETURN count(n) AS total",
        )
    )

    assert receipt.accepted is True
    latest = await wait_for_state(repository, "qa-semantic-error", "semantic_review_invalid")
    assert latest is not None
    assert latest["issue_ticket_id"] is None
    assert latest["repair_response"] is None
    assert latest["evaluation"] is None
    assert latest["semantic_review"]["status"] == "invalid"
    assert latest["semantic_review"]["raw_text"] == '{"verdict":"fail","reason":"结果不等价"}'
    assert latest["semantic_review"]["payload"] == {"verdict": "fail", "reason": "结果不等价"}
    assert latest["semantic_review"]["request_id"] == "req-semantic-invalid-001"
    assert latest["semantic_review"]["model"] == "glm-5.1"
    assert "Question:" in latest["semantic_review"]["prompt_snapshot"]
    assert "Strict Diff:" in latest["semantic_review"]["prompt_snapshot"]


@pytest.mark.asyncio
async def test_resume_pending_evaluations_replays_ready_backlog_after_restart(tmp_path):
    repository, service = build_service(
        tmp_path,
        semantic_payload={"judgement": "pass", "reasoning": "字段名不同但语义等价"},
        execution_rows=[{"total": 5}],
    )
    repository.save_golden(
        QAGoldenRequest(
            id="qa-resume-ready",
            cypher="MATCH (n) RETURN count(n) AS count",
            answer=[{"count": 5}],
            difficulty="L2",
        )
    )
    repository.save_submission(
        GeneratedCypherSubmissionRequest(
            id="qa-resume-ready",
            question="统计设备数量",
            generation_run_id="run-restart",
            generated_cypher="MATCH (n) RETURN count(n) AS total",
            input_prompt_snapshot="prompt-restart",
            last_llm_raw_output="MATCH (n) RETURN count(n) AS total",
        ),
        state="ready_to_evaluate",
    )

    resumed = await service.resume_pending_evaluations()

    assert resumed == 1
    latest = await wait_for_state(repository, "qa-resume-ready", "passed")
    assert latest["evaluation"]["verdict"] == "pass"


@pytest.mark.asyncio
async def test_get_evaluation_status_requeues_single_ready_submission(tmp_path):
    repository, service = build_service(
        tmp_path,
        semantic_payload={"judgement": "fail", "reasoning": "结果不等价"},
        execution_rows=[{"total": 4}],
    )
    repository.save_golden(
        QAGoldenRequest(
            id="qa-lazy-requeue",
            cypher="MATCH (n) RETURN count(n) AS count",
            answer=[{"count": 5}],
            difficulty="L2",
        )
    )
    repository.save_submission(
        GeneratedCypherSubmissionRequest(
            id="qa-lazy-requeue",
            question="统计设备数量",
            generation_run_id="run-lazy",
            generated_cypher="MATCH (n) RETURN count(n) AS total",
            input_prompt_snapshot="prompt-lazy",
            last_llm_raw_output="MATCH (n) RETURN count(n) AS total",
        ),
        state="ready_to_evaluate",
    )

    status = service.get_evaluation_status("qa-lazy-requeue")

    assert status.submission is not None
    latest = await wait_for_state(repository, "qa-lazy-requeue", "issue_ticket_created")
    assert latest["evaluation"]["verdict"] == "fail"


@pytest.mark.asyncio
async def test_tugraph_connection_failure_becomes_terminal_state(tmp_path):
    repository = TestingRepository(str(tmp_path / "testing"))
    service = TestingAgentService(
        repository=repository,
        repair_client=StubRepairClient(),
        tugraph_client=FailingTuGraphClient(),
        grammar_checker=GrammarChecker(StubParser(success=True)),
        grammar_explainer=StubGrammarExplainer(),
        semantic_reviewer=StubSemanticReviewer({"judgement": "pass", "reasoning": "unused"}),
        settings=type("Settings", (), {"data_dir": str(tmp_path / "testing"), "repair_service_url": "http://repair", "llm_model": "test-model", "llm_enabled": True})(),
    )
    repository.save_golden(
        QAGoldenRequest(
            id="qa-tugraph-down",
            cypher="MATCH (n) RETURN count(n) AS count",
            answer=[{"count": 5}],
            difficulty="L2",
        )
    )

    await service.ingest_submission(
        GeneratedCypherSubmissionRequest(
            id="qa-tugraph-down",
            question="统计设备数量",
            generation_run_id="run-tugraph-down",
            generated_cypher="MATCH (n) RETURN count(n) AS total",
            input_prompt_snapshot="prompt-tugraph-down",
            last_llm_raw_output="MATCH (n) RETURN count(n) AS total",
        )
    )

    latest = await wait_for_state(repository, "qa-tugraph-down", "tugraph_execution_failed")
    assert latest["issue_ticket_id"] is None
    assert latest["repair_response"] is None
    assert latest["execution"]["success"] is False
    assert "TuGraph execution failed" in latest["execution"]["error_message"]


@pytest.mark.asyncio
async def test_generation_failed_report_creates_failed_attempt_without_external_evaluation_steps(tmp_path):
    class CountingTuGraphClient:
        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, cypher: str) -> ExecutionResult:
            self.calls += 1
            return ExecutionResult(success=True, rows=[{"unused": True}], row_count=1, error_message=None, elapsed_ms=1)

    class CountingSemanticReviewer:
        def __init__(self) -> None:
            self.calls = 0

        async def review(self, **_: object):
            self.calls += 1
            return {"judgement": "pass", "reasoning": "unused"}

    repository = TestingRepository(str(tmp_path / "testing"))
    tugraph_client = CountingTuGraphClient()
    semantic_reviewer = CountingSemanticReviewer()
    service = TestingAgentService(
        repository=repository,
        repair_client=StubRepairClient(),
        tugraph_client=tugraph_client,
        grammar_checker=GrammarChecker(StubParser(success=True)),
        grammar_explainer=StubGrammarExplainer(),
        semantic_reviewer=semantic_reviewer,
        settings=type("Settings", (), {"data_dir": str(tmp_path / "testing"), "repair_service_url": "http://repair", "llm_model": "test-model", "llm_enabled": True})(),
    )
    repository.save_golden(
        QAGoldenRequest(
            id="qa-generation-failed",
            cypher="MATCH (p:Protocol) RETURN p.version",
            answer=[{"version": "v1"}],
            difficulty="L3",
        )
    )
    report = GenerationRunFailureReport(
        id="qa-generation-failed",
        question="查询协议版本",
        generation_run_id="run-generation-failed",
        input_prompt_snapshot="prompt-with-extra-constraints",
        last_llm_raw_output="```cypher\nMATCH (p:Protocol) RETURN p.version\n```",
        generation_status="generation_failed",
        failure_reason="generation_retry_exhausted",
        last_generation_failure_reason="wrapped_in_markdown",
        generation_retry_count=2,
        generation_failure_reasons=["wrapped_in_markdown", "wrapped_in_markdown", "wrapped_in_markdown"],
        parsed_cypher="MATCH (p:Protocol) RETURN p.version",
        gate_passed=False,
    )

    receipt = await service.ingest_generation_failure(report)

    assert receipt.accepted is True
    latest = await wait_for_state(repository, "qa-generation-failed", "issue_ticket_created")
    attempt = repository.get_submission_attempt("qa-generation-failed", 1)
    assert attempt is not None
    assert attempt["generation_status"] == "generation_failed"
    assert attempt["generated_cypher"] == "MATCH (p:Protocol) RETURN p.version"
    assert latest["evaluation"]["verdict"] == "fail"
    assert latest["evaluation"]["primary_metrics"]["grammar"]["score"] == 0
    assert latest["evaluation"]["primary_metrics"]["execution_accuracy"]["reason"] == "grammar_failed"
    assert latest["evaluation"]["primary_metrics"]["execution_accuracy"]["strict_check"]["status"] == "not_run"
    assert latest["evaluation"]["primary_metrics"]["execution_accuracy"]["semantic_check"]["status"] == "not_run"
    assert latest["evaluation"]["secondary_signals"]["gleu"]["score"] >= 0.0
    assert latest["evaluation"]["secondary_signals"]["jaro_winkler_similarity"]["score"] >= 0.0
    assert latest["execution"] is None
    assert tugraph_client.calls == 0
    assert semantic_reviewer.calls == 0
    ticket = repository.get_issue_ticket("ticket-qa-generation-failed-attempt-1")
    assert ticket is not None
    assert ticket.generation_evidence.last_llm_raw_output == report.last_llm_raw_output
    assert ticket.generation_evidence.generation_status == "generation_failed"
    assert ticket.generation_evidence.failure_reason == "generation_retry_exhausted"
    assert ticket.generation_evidence.generation_retry_count == 2
    assert ticket.generation_evidence.generation_failure_reasons == [
        "wrapped_in_markdown",
        "wrapped_in_markdown",
        "wrapped_in_markdown",
    ]


@pytest.mark.asyncio
async def test_openai_chat_llm_client_raises_on_invalid_json(monkeypatch):
    client = OpenAIChatCompletionLLMClient(
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
async def test_semantic_review_client_rejects_result_correctness_alias(monkeypatch):
    from services.testing_agent.app.clients import JSONCompletionResponse, OpenAIChatCompletionLLMClient, SemanticReviewClient

    llm = OpenAIChatCompletionLLMClient(
        base_url="https://example.com/v1",
        api_key="secret",
        model="glm-5",
        timeout_seconds=5,
        temperature=0.1,
    )

    async def fake_complete_json_response(prompt: str, *, qa_id=None, target="testing.llm"):
        return JSONCompletionResponse(
            payload={"result_correctness": "pass", "reasoning": "语义一致"},
            raw_text='{"result_correctness":"pass","reasoning":"语义一致"}',
            request_id="req-alias-001",
            model="glm-5",
        )

    monkeypatch.setattr(llm, "complete_json_response", fake_complete_json_response)

    with pytest.raises(InvalidSemanticReviewResponse):
        await SemanticReviewClient(llm).review(
            question="统计设备数量",
            gold_cypher="MATCH (n) RETURN count(n) AS count",
            gold_answer=[{"count": 5}],
            generated_cypher="MATCH (n) RETURN count(n) AS total",
            actual_answer=[{"total": 5}],
            strict_check_message="字段名不同",
            strict_diff={"missing_rows": [], "unexpected_rows": []},
        )


@pytest.mark.asyncio
async def test_semantic_review_client_requires_chinese_reasoning_in_prompt(monkeypatch):
    from services.testing_agent.app.clients import JSONCompletionResponse, OpenAIChatCompletionLLMClient, SemanticReviewClient

    llm = OpenAIChatCompletionLLMClient(
        base_url="https://example.com/v1",
        api_key="secret",
        model="glm-5",
        timeout_seconds=5,
        temperature=0.1,
    )
    captured = {}

    async def fake_complete_json_response(prompt: str, *, qa_id=None, target="testing.llm"):
        captured["prompt"] = prompt
        return JSONCompletionResponse(
            payload={"judgement": "fail", "reasoning": "实际结果包含了未被服务使用的隧道节点。"},
            raw_text='{"judgement":"fail","reasoning":"实际结果包含了未被服务使用的隧道节点。"}',
            request_id="req-cn-001",
            model="glm-5",
        )

    monkeypatch.setattr(llm, "complete_json_response", fake_complete_json_response)

    await SemanticReviewClient(llm).review(
        question="查询服务使用的隧道节点",
        gold_cypher="MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel) RETURN t",
        gold_answer=[{"t": "Tunnel_001"}],
        generated_cypher="MATCH (t:Tunnel) RETURN t",
        actual_answer=[{"t": "Tunnel_001"}, {"t": "Tunnel_002"}],
        strict_check_message="结果行数不一致",
        strict_diff={"missing_rows": [], "unexpected_rows": [{"t": "Tunnel_002"}]},
    )

    assert "reasoning 必须使用中文" in captured["prompt"]
    assert "不能使用英文解释" in captured["prompt"]


@pytest.mark.asyncio
async def test_semantic_review_client_rejects_english_reasoning(monkeypatch):
    from services.testing_agent.app.clients import JSONCompletionResponse, OpenAIChatCompletionLLMClient, SemanticReviewClient

    llm = OpenAIChatCompletionLLMClient(
        base_url="https://example.com/v1",
        api_key="secret",
        model="glm-5",
        timeout_seconds=5,
        temperature=0.1,
    )

    async def fake_complete_json_response(prompt: str, *, qa_id=None, target="testing.llm"):
        return JSONCompletionResponse(
            payload={"judgement": "fail", "reasoning": "The actual answer contains extra tunnel nodes."},
            raw_text='{"judgement":"fail","reasoning":"The actual answer contains extra tunnel nodes."}',
            request_id="req-en-001",
            model="glm-5",
        )

    monkeypatch.setattr(llm, "complete_json_response", fake_complete_json_response)

    with pytest.raises(InvalidSemanticReviewResponse, match="Chinese reasoning"):
        await SemanticReviewClient(llm).review(
            question="查询服务使用的隧道节点",
            gold_cypher="MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel) RETURN t",
            gold_answer=[{"t": "Tunnel_001"}],
            generated_cypher="MATCH (t:Tunnel) RETURN t",
            actual_answer=[{"t": "Tunnel_001"}, {"t": "Tunnel_002"}],
            strict_check_message="结果行数不一致",
            strict_diff={"missing_rows": [], "unexpected_rows": [{"t": "Tunnel_002"}]},
        )


@pytest.mark.asyncio
async def test_semantic_review_client_rejects_boolean_equivalence_alias(monkeypatch):
    from services.testing_agent.app.clients import JSONCompletionResponse, OpenAIChatCompletionLLMClient, SemanticReviewClient

    llm = OpenAIChatCompletionLLMClient(
        base_url="https://example.com/v1",
        api_key="secret",
        model="glm-5",
        timeout_seconds=5,
        temperature=0.1,
    )

    async def fake_complete_json_response(prompt: str, *, qa_id=None, target="testing.llm"):
        return JSONCompletionResponse(
            payload={"is_equivalent": False, "reasoning": "结果不满足问题"},
            raw_text='{"is_equivalent":false,"reasoning":"结果不满足问题"}',
            request_id="req-alias-002",
            model="glm-5",
        )

    monkeypatch.setattr(llm, "complete_json_response", fake_complete_json_response)

    with pytest.raises(InvalidSemanticReviewResponse):
        await SemanticReviewClient(llm).review(
            question="统计设备数量",
            gold_cypher="MATCH (n) RETURN count(n) AS count",
            gold_answer=[{"count": 5}],
            generated_cypher="MATCH (n) RETURN count(n) AS total",
            actual_answer=[{"total": 4}],
            strict_check_message="数量不一致",
            strict_diff={"missing_rows": [{"count": 5}], "unexpected_rows": [{"total": 4}]},
        )


@pytest.mark.asyncio
async def test_semantic_review_client_rejects_invalid_judgement_tokens(monkeypatch):
    from services.testing_agent.app.clients import JSONCompletionResponse, OpenAIChatCompletionLLMClient, SemanticReviewClient

    llm = OpenAIChatCompletionLLMClient(
        base_url="https://example.com/v1",
        api_key="secret",
        model="glm-5",
        timeout_seconds=5,
        temperature=0.1,
    )

    responses = [
        JSONCompletionResponse(
            payload={"judgement": "valid", "reasoning": "结果满足问题"},
            raw_text='{"judgement":"valid","reasoning":"结果满足问题"}',
            request_id="req-valid-001",
            model="glm-5",
        ),
        JSONCompletionResponse(
            payload={"judgement": "invalid", "reasoning": "结果不满足问题"},
            raw_text='{"judgement":"invalid","reasoning":"结果不满足问题"}',
            request_id="req-invalid-001",
            model="glm-5",
        ),
    ]

    async def fake_complete_json_response(prompt: str, *, qa_id=None, target="testing.llm"):
        return responses.pop(0)

    monkeypatch.setattr(llm, "complete_json_response", fake_complete_json_response)

    reviewer = SemanticReviewClient(llm)
    for _ in range(2):
        with pytest.raises(InvalidSemanticReviewResponse):
            await reviewer.review(
                question="统计设备数量",
                gold_cypher="MATCH (n) RETURN count(n) AS count",
                gold_answer=[{"count": 5}],
                generated_cypher="MATCH (n) RETURN count(n) AS total",
                actual_answer=[{"total": 5}],
                strict_check_message="字段名不同",
                strict_diff={"missing_rows": [], "unexpected_rows": []},
            )
