from __future__ import annotations

import json
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.models import (
    EvaluationDimensions,
    EvaluationSummary,
    KnowledgeRepairSuggestionRequest,
    TuGraphExecutionResult,
)
from services.testing_service.app.clients import LLMEvaluationClient, RepairServiceClient
from services.testing_service.app.service import EvaluationService


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
    async def test_api_error_returns_none(self):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_ctx = AsyncMock()
            mock_ctx.post.side_effect = Exception("connection timeout")
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_ctx

            result = await self.client.evaluate(
                question="test", expected_cypher="", expected_answer={},
                actual_cypher="", actual_result={}, rule_based_verdict="fail",
                rule_based_dimensions={},
            )

        assert result is None


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
    async def test_llm_returns_none_keeps_original(self):
        evaluation = _make_evaluation("fail", result_correctness="fail", question_alignment="fail")
        self.llm_client.evaluate.return_value = None

        result = await self.svc._llm_re_evaluate(
            evaluation=evaluation,
            question="test",
            expected_cypher="c1",
            expected_answer=[],
            actual_cypher="c2",
            execution=TuGraphExecutionResult(success=True, rows=[], row_count=0),
        )

        assert result.dimensions.result_correctness == "fail"
        assert result.dimensions.question_alignment == "fail"
        assert result.verdict == "fail"


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
        from shared.evaluation import evaluate_submission

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
        from shared.evaluation import evaluate_submission

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
        from shared.evaluation import evaluate_submission

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
        from shared.evaluation import evaluate_submission

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
