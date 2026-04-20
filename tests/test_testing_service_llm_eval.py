from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from contracts.models import (
    EvaluationDimensions,
    EvaluationSummary,
    ImprovementAssessment,
    TuGraphExecutionResult,
)
from services.testing_agent.app.clients import LLMEvaluationClient, RepairServiceClient
from services.testing_agent.app.models import (
    EvaluationMetrics,
    KnowledgeRepairSuggestionRequest,
    QuestionAlignmentMetrics,
    ResultCorrectnessMetrics,
    SchemaAlignmentMetrics,
    SyntaxValidityMetrics,
)
from services.testing_agent.app.service import EvaluationService


@pytest.fixture
def execution_success():
    return TuGraphExecutionResult(
        success=True,
        rows=[{"name": "router-1"}],
        row_count=1,
        error_message=None,
        elapsed_ms=50,
    )


@pytest.fixture
def execution_fail():
    return TuGraphExecutionResult(
        success=False,
        rows=[],
        row_count=0,
        error_message="Syntax error near 'MATCHH'",
        elapsed_ms=10,
    )


def _make_evaluation(verdict, **dim_overrides):
    defaults = dict(
        syntax_validity="pass",
        schema_alignment="pass",
        result_correctness="fail",
        question_alignment="fail",
    )
    defaults.update(dim_overrides)
    return EvaluationSummary(
        verdict=verdict,
        dimensions=EvaluationDimensions(**defaults),
        symptom="test symptom",
        evidence=["evidence line"],
    )


class TestLLMEvaluationClientParseResponse:
    def setup_method(self):
        self.client = LLMEvaluationClient(
            base_url="https://fake.api/v1",
            api_key="fake-key",
            model="test-model",
            timeout_seconds=10,
            temperature=0.1,
        )

    @pytest.mark.asyncio
    async def test_clean_json_response(self):
        payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "result_correctness": "pass",
                            "question_alignment": "pass",
                            "reasoning": "Semantically equivalent",
                            "confidence": 0.92,
                        })
                    }
                }
            ]
        }
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = payload
            mock_ctx = AsyncMock()
            mock_ctx.post.return_value = mock_resp
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_ctx

            result = await self.client.evaluate(
                question="有多少设备",
                expected_cypher="MATCH (n:NetworkElement) RETURN count(n) AS count",
                expected_answer=[{"count": 5}],
                actual_cypher="MATCH (n:NetworkElement) RETURN count(n) AS total",
                actual_result=[{"total": 5}],
                rule_based_verdict="fail",
                rule_based_dimensions={"result_correctness": "fail", "question_alignment": "pass"},
            )

        assert result is not None
        assert result["result_correctness"] == "pass"
        assert result["question_alignment"] == "pass"
        assert result["confidence"] == 0.92

    @pytest.mark.asyncio
    async def test_markdown_wrapped_json_response(self):
        raw_content = '```json\n{"result_correctness": "pass", "question_alignment": "fail", "reasoning": "ok", "confidence": 0.8}\n```'
        payload = {"choices": [{"message": {"content": raw_content}}]}
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = payload
            mock_ctx = AsyncMock()
            mock_ctx.post.return_value = mock_resp
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_ctx

            result = await self.client.evaluate(
                question="test", expected_cypher="", expected_answer={},
                actual_cypher="", actual_result={}, rule_based_verdict="fail",
                rule_based_dimensions={},
            )

        assert result is not None
        assert result["result_correctness"] == "pass"

    @pytest.mark.asyncio
    async def test_disables_thinking_for_json_evaluation_requests(self):
        payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "result_correctness": "pass",
                            "question_alignment": "pass",
                            "reasoning": "fast response",
                            "confidence": 0.9,
                        })
                    }
                }
            ]
        }
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = payload
            mock_resp.headers = {}
            mock_ctx = AsyncMock()
            mock_ctx.post.return_value = mock_resp
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_ctx

            await self.client.evaluate(
                question="test", expected_cypher="", expected_answer={},
                actual_cypher="", actual_result={}, rule_based_verdict="fail",
                rule_based_dimensions={},
            )

        request_payload = mock_ctx.post.await_args.kwargs["json"]
        assert request_payload["enable_thinking"] is False

    @pytest.mark.asyncio
    async def test_api_error_raises(self):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_ctx = AsyncMock()
            mock_ctx.post.side_effect = Exception("connection timeout")
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_ctx

            with pytest.raises(Exception, match="connection timeout"):
                await self.client.evaluate(
                    question="test", expected_cypher="", expected_answer={},
                    actual_cypher="", actual_result={}, rule_based_verdict="fail",
                    rule_based_dimensions={},
                )

    @pytest.mark.asyncio
    async def test_retries_after_rate_limit_then_succeeds(self):
        payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "result_correctness": "pass",
                            "question_alignment": "pass",
                            "reasoning": "Recovered after retry",
                            "confidence": 0.91,
                        })
                    }
                }
            ]
        }
        with patch("httpx.AsyncClient") as mock_client_cls:
            rate_limited = MagicMock()
            rate_limited.status_code = 429
            rate_limited.text = '{"error":{"code":"1302","message":"rate limit"}}'
            rate_limited.headers = {}
            rate_limited.raise_for_status.side_effect = httpx.HTTPStatusError(
                "rate limited",
                request=httpx.Request("POST", "https://fake.api/v1/chat/completions"),
                response=httpx.Response(429, request=httpx.Request("POST", "https://fake.api/v1/chat/completions")),
            )
            success = MagicMock()
            success.status_code = 200
            success.raise_for_status = MagicMock()
            success.json.return_value = payload
            success.headers = {}

            mock_ctx = AsyncMock()
            mock_ctx.post.side_effect = [rate_limited, success]
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_ctx

            sleep_calls: list[float] = []

            async def fake_sleep(delay: float) -> None:
                sleep_calls.append(delay)

            client = LLMEvaluationClient(
                base_url="https://fake.api/v1",
                api_key="fake-key",
                model="test-model",
                timeout_seconds=10,
                temperature=0.1,
                sleep_fn=fake_sleep,
                max_retries=1,
                retry_base_delay_seconds=0.25,
            )

            result = await client.evaluate(
                question="test", expected_cypher="", expected_answer={},
                actual_cypher="", actual_result={}, rule_based_verdict="fail",
                rule_based_dimensions={},
            )

        assert result["result_correctness"] == "pass"
        assert mock_ctx.post.await_count == 2
        assert sleep_calls == [0.25]

    @pytest.mark.asyncio
    async def test_retries_after_rate_limit_using_retry_after_header(self):
        payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "result_correctness": "pass",
                            "question_alignment": "pass",
                            "reasoning": "Recovered after server-advised delay",
                            "confidence": 0.93,
                        })
                    }
                }
            ]
        }
        with patch("httpx.AsyncClient") as mock_client_cls:
            request = httpx.Request("POST", "https://fake.api/v1/chat/completions")
            rate_limited = MagicMock()
            rate_limited.status_code = 429
            rate_limited.text = '{"error":{"code":"1302","message":"rate limit"}}'
            rate_limited.headers = {"Retry-After": "3.5"}
            rate_limited.raise_for_status.side_effect = httpx.HTTPStatusError(
                "rate limited",
                request=request,
                response=httpx.Response(
                    429,
                    headers={"Retry-After": "3.5"},
                    request=request,
                    text='{"error":{"code":"1302","message":"rate limit"}}',
                ),
            )
            success = MagicMock()
            success.status_code = 200
            success.raise_for_status = MagicMock()
            success.json.return_value = payload
            success.headers = {}

            mock_ctx = AsyncMock()
            mock_ctx.post.side_effect = [rate_limited, success]
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_ctx

            sleep_calls: list[float] = []

            async def fake_sleep(delay: float) -> None:
                sleep_calls.append(delay)

            client = LLMEvaluationClient(
                base_url="https://fake.api/v1",
                api_key="fake-key",
                model="test-model",
                timeout_seconds=10,
                temperature=0.1,
                sleep_fn=fake_sleep,
                max_retries=1,
                retry_base_delay_seconds=0.25,
            )

            result = await client.evaluate(
                question="test", expected_cypher="", expected_answer={},
                actual_cypher="", actual_result={}, rule_based_verdict="fail",
                rule_based_dimensions={},
            )

        assert result["result_correctness"] == "pass"
        assert mock_ctx.post.await_count == 2
        assert sleep_calls == [3.5]

    @pytest.mark.asyncio
    async def test_does_not_retry_non_retryable_400(self):
        with patch("httpx.AsyncClient") as mock_client_cls:
            bad_request = MagicMock()
            bad_request.status_code = 400
            bad_request.text = '{"error":{"message":"bad request"}}'
            bad_request.headers = {}
            bad_request.raise_for_status.side_effect = httpx.HTTPStatusError(
                "bad request",
                request=httpx.Request("POST", "https://fake.api/v1/chat/completions"),
                response=httpx.Response(400, request=httpx.Request("POST", "https://fake.api/v1/chat/completions")),
            )
            mock_ctx = AsyncMock()
            mock_ctx.post.return_value = bad_request
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_ctx

            sleep_calls: list[float] = []

            async def fake_sleep(delay: float) -> None:
                sleep_calls.append(delay)

            client = LLMEvaluationClient(
                base_url="https://fake.api/v1",
                api_key="fake-key",
                model="test-model",
                timeout_seconds=10,
                temperature=0.1,
                sleep_fn=fake_sleep,
                max_retries=2,
                retry_base_delay_seconds=0.25,
            )

            with pytest.raises(httpx.HTTPStatusError):
                await client.evaluate(
                    question="test", expected_cypher="", expected_answer={},
                    actual_cypher="", actual_result={}, rule_based_verdict="fail",
                    rule_based_dimensions={},
                )

        assert mock_ctx.post.await_count == 1
        assert sleep_calls == []

    @pytest.mark.asyncio
    async def test_serializes_llm_calls_when_concurrency_is_one(self):
        with patch("httpx.AsyncClient") as mock_client_cls:
            enter_count = 0
            max_inflight = 0
            inflight = 0

            class _FakeClient:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, exc_type, exc, tb):
                    return False

                async def post(self, *args, **kwargs):
                    nonlocal enter_count, inflight, max_inflight
                    enter_count += 1
                    inflight += 1
                    max_inflight = max(max_inflight, inflight)
                    await asyncio.sleep(0)
                    inflight -= 1
                    response = MagicMock()
                    response.status_code = 200
                    response.raise_for_status = MagicMock()
                    response.headers = {}
                    response.json.return_value = {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps({
                                        "result_correctness": "pass",
                                        "question_alignment": "pass",
                                        "reasoning": "serialized",
                                        "confidence": 0.9,
                                    })
                                }
                            }
                        ]
                    }
                    return response

            mock_client_cls.return_value = _FakeClient()

            client = LLMEvaluationClient(
                base_url="https://fake.api/v1",
                api_key="fake-key",
                model="test-model",
                timeout_seconds=10,
                temperature=0.1,
                max_retries=0,
                max_concurrency=1,
            )

            await asyncio.gather(
                client.evaluate(
                    question="q1", expected_cypher="", expected_answer={},
                    actual_cypher="", actual_result={}, rule_based_verdict="fail",
                    rule_based_dimensions={},
                ),
                client.evaluate(
                    question="q2", expected_cypher="", expected_answer={},
                    actual_cypher="", actual_result={}, rule_based_verdict="fail",
                    rule_based_dimensions={},
                ),
            )

        assert enter_count == 2
        assert max_inflight == 1


class TestLLMReEvaluate:
    def setup_method(self):
        self.repo = MagicMock()
        self.repair_client = AsyncMock()
        self.llm_client = AsyncMock(spec=LLMEvaluationClient)
        self.tugraph_client = AsyncMock()
        self.svc = EvaluationService(
            repository=self.repo,
            repair_client=self.repair_client,
            llm_client=self.llm_client,
            tugraph_client=self.tugraph_client,
        )

    @pytest.mark.asyncio
    async def test_llm_flips_result_correctness(self):
        evaluation = _make_evaluation("fail", result_correctness="fail", question_alignment="fail")
        self.llm_client.evaluate.return_value = {
            "result_correctness": "pass",
            "question_alignment": "fail",
            "reasoning": "Same data, different key name",
            "confidence": 0.88,
        }

        result = await self.svc._llm_re_evaluate(
            evaluation=evaluation,
            question="有多少设备",
            expected_cypher="MATCH (n) RETURN count(n) AS count",
            expected_answer=[{"count": 5}],
            actual_cypher="MATCH (n) RETURN count(n) AS total",
            execution=TuGraphExecutionResult(success=True, rows=[{"total": 5}], row_count=1),
        )

        assert result.dimensions.result_correctness == "pass"
        assert result.dimensions.question_alignment == "fail"
        assert result.verdict == "partial_fail"
        assert any("[LLM override]" in e for e in result.evidence)

    @pytest.mark.asyncio
    async def test_llm_flips_both_to_pass(self):
        evaluation = _make_evaluation("fail", result_correctness="fail", question_alignment="fail")
        self.llm_client.evaluate.return_value = {
            "result_correctness": "pass",
            "question_alignment": "pass",
            "reasoning": "Fully equivalent",
            "confidence": 0.95,
        }

        result = await self.svc._llm_re_evaluate(
            evaluation=evaluation,
            question="test",
            expected_cypher="c1",
            expected_answer=[{"a": 1}],
            actual_cypher="c2",
            execution=TuGraphExecutionResult(success=True, rows=[{"a": 1}], row_count=1),
        )

        assert result.dimensions.result_correctness == "pass"
        assert result.dimensions.question_alignment == "pass"
        assert result.verdict == "pass"

    @pytest.mark.asyncio
    async def test_llm_override_updates_metrics_and_overall_score(self):
        evaluation = _make_evaluation("partial_fail", result_correctness="fail", question_alignment="fail")
        evaluation.metrics = EvaluationMetrics(
            syntax_validity=SyntaxValidityMetrics(score=1.0, verdict="pass", parse_success=True, execution_success=True),
            schema_alignment=SchemaAlignmentMetrics(score=1.0, verdict="pass", label_match_score=1.0, relation_match_score=1.0, property_match_score=1.0),
            result_correctness=ResultCorrectnessMetrics(score=0.0, verdict="fail", execution_match_score=0.0, result_set_precision=0.0, result_set_recall=0.0, result_set_f1=0.0),
            question_alignment=QuestionAlignmentMetrics(score=0.5, verdict="partial", entity_match_score=1.0, relation_path_match_score=1.0, filter_match_score=1.0, aggregation_match_score=1.0, projection_match_score=0.0, ordering_limit_match_score=1.0),
        )
        evaluation.overall_score = 0.475
        self.llm_client.evaluate.return_value = {
            "result_correctness": "pass",
            "question_alignment": "pass",
            "reasoning": "Alias-only mismatch; same graph objects.",
            "confidence": 0.95,
        }

        result = await self.svc._llm_re_evaluate(
            evaluation=evaluation,
            question="test",
            expected_cypher="c1",
            expected_answer=[{"a": 1}],
            actual_cypher="c2",
            execution=TuGraphExecutionResult(success=True, rows=[{"t": 1}], row_count=1),
        )

        assert result.metrics is not None
        assert result.verdict == "pass"
        assert result.metrics.result_correctness.score == 1.0
        assert result.metrics.result_correctness.verdict == "pass"
        assert result.metrics.question_alignment.score == 1.0
        assert result.metrics.question_alignment.verdict == "pass"
        assert result.overall_score == 1.0

    @pytest.mark.asyncio
    async def test_llm_cannot_flip_pass_to_fail(self):
        evaluation = _make_evaluation("partial_fail", result_correctness="pass", question_alignment="fail")
        self.llm_client.evaluate.return_value = {
            "result_correctness": "fail",
            "question_alignment": "pass",
            "reasoning": "I disagree",
            "confidence": 0.6,
        }

        result = await self.svc._llm_re_evaluate(
            evaluation=evaluation,
            question="test",
            expected_cypher="c1",
            expected_answer=[],
            actual_cypher="c2",
            execution=TuGraphExecutionResult(success=True, rows=[], row_count=0),
        )

        assert result.dimensions.result_correctness == "pass"
        assert result.dimensions.question_alignment == "pass"
        assert len([e for e in result.evidence if "[LLM override]" in e]) == 1

    @pytest.mark.asyncio
    async def test_llm_failure_bubbles_up(self):
        evaluation = _make_evaluation("fail", result_correctness="fail", question_alignment="fail")
        self.llm_client.evaluate.side_effect = RuntimeError("glm unavailable")

        with pytest.raises(RuntimeError, match="glm unavailable"):
            await self.svc._llm_re_evaluate(
                evaluation=evaluation,
                question="test",
                expected_cypher="c1",
                expected_answer=[],
                actual_cypher="c2",
                execution=TuGraphExecutionResult(success=True, rows=[], row_count=0),
            )


class TestEvaluateReadyPairWithLLM:
    def setup_method(self):
        self.repo = MagicMock()
        self.repair_client = AsyncMock()
        self.llm_client = AsyncMock(spec=LLMEvaluationClient)
        self.tugraph_client = AsyncMock()
        self.svc = EvaluationService(
            repository=self.repo,
            repair_client=self.repair_client,
            llm_client=self.llm_client,
            tugraph_client=self.tugraph_client,
        )
        self.golden = {
            "id": "test-001",
            "golden_cypher": "MATCH (n:NetworkElement) RETURN n.name AS name LIMIT 5",
            "golden_answer_json": json.dumps([{"name": "router-1"}]),
            "difficulty": "L1",
        }
        self.submission = {
            "id": "test-001",
            "question": "查看设备",
            "generated_cypher": "MATCH (n:NetworkElement) RETURN n.name AS name LIMIT 5",
            "generation_run_id": "run-001",
            "parse_summary": "parsed_json",
            "guardrail_summary": "accepted",
            "raw_output_snapshot": '{"cypher":"MATCH (n:NetworkElement) RETURN n.name AS name LIMIT 5"}',
            "input_prompt_snapshot": "请生成 Cypher",
            "status": "ready_to_evaluate",
        }
        self.tugraph_client.execute.return_value = TuGraphExecutionResult(
            success=True,
            rows=[{"name": "router-1"}],
            row_count=1,
            error_message=None,
            elapsed_ms=50,
        )

    @pytest.mark.asyncio
    async def test_rule_pass_skips_llm(self):
        self.repo.get_golden.return_value = self.golden
        self.repo.get_submission.return_value = self.submission
        self.repo.mark_submission_status = MagicMock()

        result = await self.svc._evaluate_ready_pair("test-001")

        self.tugraph_client.execute.assert_awaited_once_with(self.submission["generated_cypher"])
        self.llm_client.evaluate.assert_not_called()
        assert result.verdict == "pass"

    @pytest.mark.asyncio
    async def test_rule_fail_triggers_llm_and_flips_to_pass(self):
        self.golden["golden_answer_json"] = json.dumps([{"name": "router-2"}])
        self.repo.get_golden.return_value = self.golden
        self.repo.get_submission.return_value = self.submission
        self.repo.mark_submission_status = MagicMock()

        self.llm_client.evaluate.return_value = {
            "result_correctness": "pass",
            "question_alignment": "pass",
            "reasoning": "Data is equivalent",
            "confidence": 0.9,
        }

        result = await self.svc._evaluate_ready_pair("test-001")

        self.llm_client.evaluate.assert_called_once()
        assert result.verdict == "pass"

    @pytest.mark.asyncio
    async def test_rule_fail_llm_agrees_creates_ticket(self):
        self.golden["golden_answer_json"] = json.dumps([{"name": "router-999"}])
        self.repo.get_golden.return_value = self.golden
        self.repo.get_submission.return_value = self.submission
        self.repo.save_issue_ticket = MagicMock()

        self.llm_client.evaluate.return_value = {
            "result_correctness": "fail",
            "question_alignment": "fail",
            "reasoning": "Truly different",
            "confidence": 0.85,
        }

        result = await self.svc._evaluate_ready_pair("test-001")

        self.llm_client.evaluate.assert_called_once()
        assert result.status == "issue_ticket_created"
        assert result.verdict == "partial_fail"

    @pytest.mark.asyncio
    async def test_no_llm_client_uses_rules_only(self):
        svc_no_llm = EvaluationService(
            repository=self.repo,
            repair_client=self.repair_client,
            llm_client=None,
            tugraph_client=self.tugraph_client,
        )
        self.golden["golden_answer_json"] = json.dumps([{"name": "different"}])
        self.repo.get_golden.return_value = self.golden
        self.repo.get_submission.return_value = self.submission
        self.repo.save_issue_ticket = MagicMock()

        result = await svc_no_llm._evaluate_ready_pair("test-001")

        assert result.status == "issue_ticket_created"

    @pytest.mark.asyncio
    async def test_repair_timeout_bubbles_up_instead_of_returning_fake_success(self):
        self.golden["golden_answer_json"] = json.dumps([{"name": "router-999"}])
        self.repo.get_golden.return_value = self.golden
        self.repo.get_submission.return_value = self.submission
        self.repo.save_issue_ticket = MagicMock()
        self.llm_client.evaluate.return_value = {
            "result_correctness": "fail",
            "question_alignment": "fail",
            "reasoning": "Truly different",
            "confidence": 0.85,
        }
        self.repair_client.submit_issue_ticket.side_effect = TimeoutError("krss timeout")

        with pytest.raises(TimeoutError, match="krss timeout"):
            await self.svc._evaluate_ready_pair("test-001")

        self.repo.save_submission_krss_response.assert_not_called()


def test_improvement_assessment_marks_first_run_when_no_previous_attempt():
    repo = MagicMock()
    svc = EvaluationService(repository=repo, repair_client=AsyncMock(), tugraph_client=AsyncMock())

    assessment = svc._build_improvement_assessment(
        id="qa-1",
        current_submission={"id": "qa-1", "attempt_no": 1, "status": "passed", "execution_json": '{"success": true}'},
    )

    assert isinstance(assessment, ImprovementAssessment)
    assert assessment.status == "first_run"
    assert assessment.previous_attempt_no is None


def test_improvement_assessment_marks_improved_when_verdict_and_semantics_get_better():
    repo = MagicMock()
    repo.get_submission_attempt.side_effect = [
        {
            "id": "qa-2",
            "attempt_no": 1,
            "status": "issue_ticket_created",
            "execution_json": '{"success": false, "rows": [], "row_count": 0, "error_message": "bad", "elapsed_ms": 1}',
            "issue_ticket_id": "ticket-qa-2-attempt-1",
            "krss_response": {"status": "applied"},
        }
    ]
    repo.get_issue_snapshot_by_submission_id.return_value = {
        "evaluation": {
            "verdict": "partial_fail",
            "dimensions": {
                "syntax_validity": "pass",
                "schema_alignment": "pass",
                "result_correctness": "fail",
                "question_alignment": "pass",
            },
            "evidence": ["limit mismatch"],
        }
    }
    repo.get_issue_ticket.return_value = MagicMock(
        model_dump=MagicMock(
            return_value={
                "evaluation": {
                    "verdict": "fail",
                    "dimensions": {
                        "syntax_validity": "fail",
                        "schema_alignment": "pass",
                        "result_correctness": "fail",
                        "question_alignment": "fail",
                    },
                    "evidence": ["missing ORDER BY", "limit mismatch", "return shape mismatch"],
                }
            }
        )
    )
    svc = EvaluationService(repository=repo, repair_client=AsyncMock(), tugraph_client=AsyncMock())

    assessment = svc._build_improvement_assessment(
        id="qa-2",
        current_submission={
            "id": "qa-2",
            "attempt_no": 2,
            "status": "issue_ticket_created",
            "execution_json": '{"success": true, "rows": [], "row_count": 0, "error_message": null, "elapsed_ms": 1}',
            "issue_ticket_id": "ticket-qa-2-attempt-2",
        },
    )

    assert assessment.status == "improved"
    assert assessment.dimensions.verdict_change == "improved"
    assert assessment.dimensions.semantic_change == "improved"


class TestRepairServiceClientContract:
    @pytest.mark.asyncio
    async def test_submit_issue_ticket_parses_krss_response(self):
        client = RepairServiceClient(base_url="http://repair-service", timeout_seconds=10)
        ticket = MagicMock()
        ticket.model_dump.return_value = {"id": "q-001"}

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = {
                "status": "applied",
                "analysis_id": "analysis-q-001",
                "id": "q-001",
                "knowledge_repair_request": {
                    "id": "q-001",
                    "suggestion": "Add protocol mapping guidance",
                    "knowledge_types": ["business_knowledge", "few_shot"],
                },
                "applied": True,
            }
            mock_ctx = AsyncMock()
            mock_ctx.post.return_value = mock_response
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_ctx

            result = await client.submit_issue_ticket(ticket)

        assert result.status == "applied"
        assert result.id == "q-001"
        assert result.applied is True
        assert result.knowledge_repair_request == KnowledgeRepairSuggestionRequest(
            id="q-001",
            suggestion="Add protocol mapping guidance",
            knowledge_types=["business_knowledge", "few_shot"],
        )


class TestRuleBasedEvaluation:
    def test_pass_all_dimensions(self, execution_success):
        from contracts.evaluation import evaluate_submission

        result = evaluate_submission(
            question="查看所有设备",
            expected_cypher="MATCH (n:NetworkElement) RETURN n.name AS name LIMIT 5",
            expected_answer=[{"name": "router-1"}],
            actual_cypher="MATCH (n:NetworkElement) RETURN n.name AS name LIMIT 5",
            execution=execution_success,
            loaded_knowledge_tags=["network_element"],
        )

        assert result.verdict == "pass"
        assert result.dimensions.syntax_validity == "pass"
        assert result.dimensions.schema_alignment == "pass"
        assert result.dimensions.result_correctness == "pass"

    def test_result_mismatch(self, execution_success):
        from contracts.evaluation import evaluate_submission

        result = evaluate_submission(
            question="查看所有设备",
            expected_cypher="MATCH (n:NetworkElement) RETURN n.name AS name LIMIT 5",
            expected_answer=[{"name": "router-999"}],
            actual_cypher="MATCH (n:NetworkElement) RETURN n.name AS name LIMIT 5",
            execution=execution_success,
            loaded_knowledge_tags=["network_element"],
        )

        assert result.dimensions.result_correctness == "fail"
        assert result.verdict != "pass"

    def test_syntax_error(self, execution_fail):
        from contracts.evaluation import evaluate_submission

        result = evaluate_submission(
            question="查看所有设备",
            expected_cypher="MATCH (n:NetworkElement) RETURN n",
            expected_answer=[],
            actual_cypher="MATCHH (n:NetworkElement) RETURN n",
            execution=execution_fail,
            loaded_knowledge_tags=["network_element"],
        )

        assert result.dimensions.syntax_validity == "fail"
        assert result.verdict == "fail"

    def test_schema_alignment_invalid_label(self):
        from contracts.evaluation import evaluate_submission

        execution = TuGraphExecutionResult(
            success=True, rows=[], row_count=0, error_message=None, elapsed_ms=10
        )
        result = evaluate_submission(
            question="test",
            expected_cypher="MATCH (n:NetworkElement) RETURN n",
            expected_answer=[],
            actual_cypher="MATCH (n:InvalidLabel) RETURN n",
            execution=execution,
            loaded_knowledge_tags=[],
        )

        assert result.dimensions.schema_alignment == "fail"
