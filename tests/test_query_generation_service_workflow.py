from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from services.query_generator_agent.app.models import (
    GeneratedCypherSubmissionRequest,
    GenerationRunResult,
    PreflightCheck,
    QAQuestionRequest,
)
from services.query_generator_agent.app.parser import parse_model_output
from services.query_generator_agent.app.preflight import run_preflight_check
from services.query_generator_agent.app.service import CypherGeneratorAgentService


class TestCypherGeneratorAgentWorkflow:
    @pytest.mark.asyncio
    async def test_generates_direct_cypher_and_submits_evidence_without_attempt_no(self):
        knowledge_client = AsyncMock()
        knowledge_client.fetch_context.return_value = "Schema: (:Protocol)-[:HAS_TUNNEL]->(:Tunnel)"
        llm_client = AsyncMock()
        llm_client.generate_from_prompt.return_value = {
            "raw_output": "MATCH (p:Protocol)-[:HAS_TUNNEL]->(t:Tunnel) RETURN p.version, t.name",
            "model_name": "test-model",
        }
        testing_client = AsyncMock()

        service = CypherGeneratorAgentService(
            knowledge_client=knowledge_client,
            llm_client=llm_client,
            testing_client=testing_client,
            generation_run_id_factory=lambda: "cypher-run-001",
        )

        result = await service.ingest_question(QAQuestionRequest(id="qa-001", question="查询所有协议版本对应的隧道名称"))

        assert result.generation_status == "submitted_to_testing"
        assert result.generation_run_id == "cypher-run-001"
        assert result.reason is None
        knowledge_client.fetch_context.assert_awaited_once_with(id="qa-001", question="查询所有协议版本对应的隧道名称")
        prompt = llm_client.generate_from_prompt.await_args.kwargs["llm_prompt"]
        assert "【任务说明】" in prompt
        assert "【用户问题】" in prompt
        assert "【knowledge-agent 上下文】" in prompt
        assert "【输出格式】" in prompt
        assert "Schema: (:Protocol)-[:HAS_TUNNEL]->(:Tunnel)" in prompt
        assert "CGS" not in prompt
        assert "KO Prompt" not in prompt

        testing_client.submit.assert_awaited_once()
        submission = testing_client.submit.await_args.kwargs["payload"]
        assert submission.model_dump() == {
            "id": "qa-001",
            "question": "查询所有协议版本对应的隧道名称",
            "generation_run_id": "cypher-run-001",
            "generated_cypher": "MATCH (p:Protocol)-[:HAS_TUNNEL]->(t:Tunnel) RETURN p.version, t.name",
            "parse_summary": "direct_cypher",
            "preflight_check": {"accepted": True},
            "raw_output_snapshot": "MATCH (p:Protocol)-[:HAS_TUNNEL]->(t:Tunnel) RETURN p.version, t.name",
            "input_prompt_snapshot": prompt,
        }
        assert "attempt_no" not in submission.model_dump()

    @pytest.mark.asyncio
    async def test_retries_with_fixed_extra_constraint_after_markdown_wrapped_output(self):
        knowledge_client = AsyncMock()
        knowledge_client.fetch_context.return_value = "Schema: (:Protocol)"
        llm_client = AsyncMock()
        llm_client.generate_from_prompt.side_effect = [
            {"raw_output": "```cypher\nMATCH (p:Protocol) RETURN p.version\n```", "model_name": "test-model"},
            {"raw_output": "MATCH (p:Protocol) RETURN p.version", "model_name": "test-model"},
        ]
        testing_client = AsyncMock()

        service = CypherGeneratorAgentService(
            knowledge_client=knowledge_client,
            llm_client=llm_client,
            testing_client=testing_client,
            generation_run_id_factory=lambda: "cypher-run-002",
        )

        result = await service.ingest_question(QAQuestionRequest(id="qa-002", question="查询协议版本"))

        assert result.generation_status == "submitted_to_testing"
        assert llm_client.generate_from_prompt.await_count == 2
        first_prompt = llm_client.generate_from_prompt.await_args_list[0].kwargs["llm_prompt"]
        second_prompt = llm_client.generate_from_prompt.await_args_list[1].kwargs["llm_prompt"]
        assert "【额外约束】" not in first_prompt
        assert "【额外约束】" in second_prompt
        assert "不要使用 Markdown 或代码块包装查询。" in second_prompt
        assert "上一轮" not in second_prompt

    @pytest.mark.asyncio
    async def test_generation_failure_after_three_preflight_failures(self):
        knowledge_client = AsyncMock()
        knowledge_client.fetch_context.return_value = "Schema: (:Protocol)"
        llm_client = AsyncMock()
        llm_client.generate_from_prompt.return_value = {
            "raw_output": "MATCH (p:Protocol RETURN p.version",
            "model_name": "test-model",
        }
        testing_client = AsyncMock()

        service = CypherGeneratorAgentService(
            knowledge_client=knowledge_client,
            llm_client=llm_client,
            testing_client=testing_client,
            generation_run_id_factory=lambda: "cypher-run-003",
        )

        result = await service.ingest_question(QAQuestionRequest(id="qa-003", question="查询协议版本"))

        assert result.generation_status == "generation_failed"
        assert result.reason == "generation_retry_exhausted"
        assert result.last_reason == "unbalanced_brackets"
        assert llm_client.generate_from_prompt.await_count == 3
        testing_client.submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_knowledge_context_failure_is_service_failure_without_llm_retry(self):
        knowledge_client = AsyncMock()
        knowledge_client.fetch_context.side_effect = RuntimeError("knowledge-agent offline")
        llm_client = AsyncMock()
        testing_client = AsyncMock()

        service = CypherGeneratorAgentService(
            knowledge_client=knowledge_client,
            llm_client=llm_client,
            testing_client=testing_client,
            generation_run_id_factory=lambda: "cypher-run-004",
        )

        result = await service.ingest_question(QAQuestionRequest(id="qa-004", question="查询协议版本"))

        assert result.generation_status == "service_failed"
        assert result.reason == "knowledge_agent_context_unavailable"
        llm_client.generate_from_prompt.assert_not_called()
        testing_client.submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_unreadable_llm_response_is_service_failure_without_generation_retry(self):
        knowledge_client = AsyncMock()
        knowledge_client.fetch_context.return_value = "Schema: (:Protocol)"
        llm_client = AsyncMock()
        llm_client.generate_from_prompt.return_value = {"model_name": "test-model"}
        testing_client = AsyncMock()

        service = CypherGeneratorAgentService(
            knowledge_client=knowledge_client,
            llm_client=llm_client,
            testing_client=testing_client,
            generation_run_id_factory=lambda: "cypher-run-005",
        )

        result = await service.ingest_question(QAQuestionRequest(id="qa-005", question="查询协议版本"))

        assert result.generation_status == "service_failed"
        assert result.reason == "model_invocation_failed"
        assert llm_client.generate_from_prompt.await_count == 1
        testing_client.submit.assert_not_called()


def test_preflight_rejects_unsupported_and_malformed_cypher_with_single_reason():
    cases = {
        "": "empty_output",
        "MATCH (n) RETURN n; MATCH (m) RETURN m": "multiple_statements",
        "MATCH (n RETURN n": "unbalanced_brackets",
        "MATCH (n) RETURN 'abc": "unclosed_string",
        "CREATE (n) RETURN n": "write_operation",
        "CALL db.labels()": "unsupported_call",
        "RETURN 1": "unsupported_start_clause",
    }

    for cypher, expected_reason in cases.items():
        result = run_preflight_check(cypher)
        assert result.accepted is False
        assert result.reason == expected_reason


def test_preflight_does_not_treat_write_keywords_inside_strings_as_write_operations():
    result = run_preflight_check('MATCH (n {name: "DELETE"}) RETURN n')

    assert result.accepted is True


def test_preflight_uses_clause_boundaries_for_start_and_write_checks():
    assert run_preflight_check("MATCHED (n) RETURN n").reason == "unsupported_start_clause"
    assert run_preflight_check("MATCH (n:Set) RETURN n").accepted is True
    assert run_preflight_check("MATCH (n) SET n.name = 'x' RETURN n").reason == "write_operation"
    assert run_preflight_check("MATCH (n) RETURN n.set").accepted is True


def test_preflight_rejects_call_clause_even_when_it_is_not_the_start_clause():
    result = run_preflight_check("MATCH (n) CALL db.labels() YIELD label RETURN label")

    assert result.accepted is False
    assert result.reason == "unsupported_call"


def test_preflight_allows_semicolon_inside_string_literal():
    result = run_preflight_check('MATCH (n {name: "a;b"}) RETURN n')

    assert result.accepted is True


def test_preflight_check_enforces_reason_invariant():
    with pytest.raises(ValidationError):
        PreflightCheck(accepted=False)

    with pytest.raises(ValidationError):
        PreflightCheck(accepted=True, reason="empty_output")


def test_submission_payload_requires_accepted_preflight_check():
    with pytest.raises(ValidationError):
        GeneratedCypherSubmissionRequest(
            id="qa-001",
            question="查询协议版本",
            generation_run_id="cypher-run-001",
            generated_cypher="MATCH (p:Protocol) RETURN p.version",
            parse_summary="direct_cypher",
            preflight_check=PreflightCheck(accepted=False, reason="unsupported_start_clause"),
            raw_output_snapshot="MATCH (p:Protocol) RETURN p.version",
            input_prompt_snapshot="prompt",
        )


def test_generation_run_result_enforces_status_reason_invariants():
    GenerationRunResult(generation_run_id="run-ok", generation_status="submitted_to_testing")

    with pytest.raises(ValidationError):
        GenerationRunResult(
            generation_run_id="run-invalid",
            generation_status="submitted_to_testing",
            reason="empty_output",
        )

    with pytest.raises(ValidationError):
        GenerationRunResult(generation_run_id="run-invalid", generation_status="generation_failed")

    with pytest.raises(ValidationError):
        GenerationRunResult(
            generation_run_id="run-invalid",
            generation_status="service_failed",
            reason="empty_output",
        )

    with pytest.raises(ValidationError):
        GenerationRunResult(
            generation_run_id="run-invalid",
            generation_status="generation_failed",
            reason="generation_retry_exhausted",
        )


def test_parser_rejects_cypher_with_explanation_text_after_query():
    parsed = parse_model_output(
        "MATCH (p:Protocol) RETURN p.version\n"
        "This query returns all protocol versions."
    )

    assert parsed.parsed_cypher == ""
    assert parsed.reason == "contains_explanation"
