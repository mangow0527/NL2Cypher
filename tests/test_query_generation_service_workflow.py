from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from services.cypher_generator_agent.app.outbox import DeliveryOutbox
from services.cypher_generator_agent.app.config import Settings
from services.cypher_generator_agent.app.knowledge_context import FileKnowledgeContextProvider
from services.cypher_generator_agent.app.models import (
    GeneratedCypherSubmissionRequest,
    GenerationRunFailureReport,
    GenerationRunResult,
    PreflightCheck,
    QAQuestionRequest,
)
from services.cypher_generator_agent.app.parser import parse_model_output
from services.cypher_generator_agent.app.preflight import run_preflight_check
from services.cypher_generator_agent.app.service import (
    CypherGeneratorAgentService,
    build_workflow_service,
    get_generator_status,
)


def write_valid_knowledge_docs(knowledge_dir):
    knowledge_dir.mkdir()
    (knowledge_dir / "system_prompt.md").write_text("System prompt", encoding="utf-8")
    (knowledge_dir / "schema.json").write_text('{"nodes":[{"label":"Protocol"}]}', encoding="utf-8")
    (knowledge_dir / "cypher_syntax.md").write_text("Cypher syntax", encoding="utf-8")
    (knowledge_dir / "business_knowledge.md").write_text("Business knowledge", encoding="utf-8")
    (knowledge_dir / "few_shot.md").write_text("Few-shot examples", encoding="utf-8")


def test_build_workflow_service_uses_file_knowledge_context_provider(tmp_path):
    settings = Settings(
        knowledge_docs_dir=str(tmp_path / "knowledge"),
        testing_agent_url="http://testing-agent",
        llm_base_url="http://llm",
        llm_api_key="test-key",
        llm_model="test-model",
        _env_file=None,
    )

    service = build_workflow_service(settings)

    assert isinstance(service.knowledge_context_provider, FileKnowledgeContextProvider)
    assert service.knowledge_context_provider.knowledge_dir == tmp_path / "knowledge"


def test_generator_status_reports_file_knowledge_context_source(monkeypatch, tmp_path):
    knowledge_dir = tmp_path / "knowledge"
    write_valid_knowledge_docs(knowledge_dir)
    settings = Settings(
        knowledge_docs_dir=str(knowledge_dir),
        testing_agent_url="http://testing-agent",
        llm_base_url="http://llm",
        llm_api_key="test-key",
        llm_model="test-model",
        _env_file=None,
    )
    monkeypatch.setattr("services.cypher_generator_agent.app.service.get_settings", lambda: settings)

    status = get_generator_status()

    assert status["knowledge_context_source"] == "file"
    assert status["knowledge_docs_dir_configured"] is True
    assert "knowledge_agent_configured" not in status


def test_generator_status_reports_unconfigured_when_knowledge_docs_are_unusable(monkeypatch, tmp_path):
    settings = Settings(
        knowledge_docs_dir=str(tmp_path / "missing-knowledge"),
        testing_agent_url="http://testing-agent",
        llm_base_url="http://llm",
        llm_api_key="test-key",
        llm_model="test-model",
        _env_file=None,
    )
    monkeypatch.setattr("services.cypher_generator_agent.app.service.get_settings", lambda: settings)

    status = get_generator_status()

    assert status["knowledge_context_source"] == "file"
    assert status["knowledge_docs_dir_configured"] is False


class TestCypherGeneratorAgentWorkflow:
    @pytest.mark.asyncio
    async def test_generates_direct_cypher_and_submits_evidence_without_attempt_no(self):
        knowledge_context_provider = AsyncMock()
        knowledge_context_provider.fetch_context.return_value = "Schema: (:Protocol)-[:HAS_TUNNEL]->(:Tunnel)"
        llm_client = AsyncMock()
        llm_client.generate_from_prompt.return_value = {
            "raw_output": "MATCH (p:Protocol)-[:HAS_TUNNEL]->(t:Tunnel) RETURN p.version, t.name",
            "model_name": "test-model",
        }
        testing_client = AsyncMock()

        service = CypherGeneratorAgentService(
            knowledge_context_provider=knowledge_context_provider,
            llm_client=llm_client,
            testing_client=testing_client,
            generation_run_id_factory=lambda: "cypher-run-001",
        )

        result = await service.ingest_question(QAQuestionRequest(id="qa-001", question="查询所有协议版本对应的隧道名称"))

        assert result.generation_status == "submitted_to_testing"
        assert result.generation_run_id == "cypher-run-001"
        assert result.reason is None
        knowledge_context_provider.fetch_context.assert_awaited_once_with(id="qa-001", question="查询所有协议版本对应的隧道名称")
        prompt = llm_client.generate_from_prompt.await_args.kwargs["llm_prompt"]
        assert "【任务说明】" in prompt
        assert "【用户问题】" in prompt
        assert "【知识文档上下文】" in prompt
        assert "knowledge-agent 上下文" not in prompt
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
            "input_prompt_snapshot": prompt,
            "last_llm_raw_output": "MATCH (p:Protocol)-[:HAS_TUNNEL]->(t:Tunnel) RETURN p.version, t.name",
            "generation_retry_count": 0,
            "generation_failure_reasons": [],
        }

    @pytest.mark.asyncio
    async def test_retries_with_fixed_extra_constraint_after_markdown_wrapped_output(self):
        knowledge_context_provider = AsyncMock()
        knowledge_context_provider.fetch_context.return_value = "Schema: (:Protocol)"
        llm_client = AsyncMock()
        llm_client.generate_from_prompt.side_effect = [
            {"raw_output": "```cypher\nMATCH (p:Protocol) RETURN p.version\n```", "model_name": "test-model"},
            {"raw_output": "MATCH (p:Protocol) RETURN p.version", "model_name": "test-model"},
        ]
        testing_client = AsyncMock()

        service = CypherGeneratorAgentService(
            knowledge_context_provider=knowledge_context_provider,
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
        testing_client.submit.assert_awaited_once()
        submission = testing_client.submit.await_args.kwargs["payload"]
        assert submission.last_llm_raw_output == "MATCH (p:Protocol) RETURN p.version"
        assert submission.generation_retry_count == 1
        assert submission.generation_failure_reasons == ["wrapped_in_markdown"]

    @pytest.mark.asyncio
    async def test_generation_failure_after_three_preflight_failures_submits_failure_report(self):
        knowledge_context_provider = AsyncMock()
        knowledge_context_provider.fetch_context.return_value = "Schema: (:Protocol)"
        llm_client = AsyncMock()
        llm_client.generate_from_prompt.return_value = {
            "raw_output": "MATCH (p:Protocol RETURN p.version",
            "model_name": "test-model",
        }
        testing_client = AsyncMock()

        service = CypherGeneratorAgentService(
            knowledge_context_provider=knowledge_context_provider,
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
        testing_client.submit_generation_failure.assert_awaited_once()
        report = testing_client.submit_generation_failure.await_args.kwargs["payload"]
        assert report.generation_status == "generation_failed"
        assert report.failure_reason == "generation_retry_exhausted"
        assert report.last_generation_failure_reason == "unbalanced_brackets"
        assert report.generation_retry_count == 2
        assert report.generation_failure_reasons == [
            "unbalanced_brackets",
            "unbalanced_brackets",
            "unbalanced_brackets",
        ]
        assert report.last_llm_raw_output == "MATCH (p:Protocol RETURN p.version"
        assert report.parsed_cypher == "MATCH (p:Protocol RETURN p.version"
        assert report.gate_passed is False

    @pytest.mark.asyncio
    async def test_knowledge_context_failure_is_service_failure_without_llm_retry(self):
        knowledge_context_provider = AsyncMock()
        knowledge_context_provider.fetch_context.side_effect = RuntimeError("knowledge docs unavailable")
        llm_client = AsyncMock()
        testing_client = AsyncMock()

        service = CypherGeneratorAgentService(
            knowledge_context_provider=knowledge_context_provider,
            llm_client=llm_client,
            testing_client=testing_client,
            generation_run_id_factory=lambda: "cypher-run-004",
        )

        result = await service.ingest_question(QAQuestionRequest(id="qa-004", question="查询协议版本"))

        assert result.generation_status == "service_failed"
        assert result.reason == "knowledge_context_unavailable"
        llm_client.generate_from_prompt.assert_not_called()
        testing_client.submit.assert_not_called()
        testing_client.submit_generation_failure.assert_awaited_once()
        report = testing_client.submit_generation_failure.await_args.kwargs["payload"]
        assert report.generation_status == "service_failed"
        assert report.failure_reason == "knowledge_context_unavailable"
        assert report.input_prompt_snapshot == ""
        assert report.last_llm_raw_output == ""
        assert report.generation_retry_count == 0
        assert report.generation_failure_reasons == []

    @pytest.mark.asyncio
    async def test_unreadable_llm_response_is_service_failure_without_generation_retry(self):
        knowledge_context_provider = AsyncMock()
        knowledge_context_provider.fetch_context.return_value = "Schema: (:Protocol)"
        llm_client = AsyncMock()
        llm_client.generate_from_prompt.return_value = {"model_name": "test-model"}
        testing_client = AsyncMock()

        service = CypherGeneratorAgentService(
            knowledge_context_provider=knowledge_context_provider,
            llm_client=llm_client,
            testing_client=testing_client,
            generation_run_id_factory=lambda: "cypher-run-005",
        )

        result = await service.ingest_question(QAQuestionRequest(id="qa-005", question="查询协议版本"))

        assert result.generation_status == "service_failed"
        assert result.reason == "model_invocation_failed"
        assert llm_client.generate_from_prompt.await_count == 1
        testing_client.submit.assert_not_called()
        testing_client.submit_generation_failure.assert_awaited_once()
        report = testing_client.submit_generation_failure.await_args.kwargs["payload"]
        assert report.generation_status == "service_failed"
        assert report.failure_reason == "model_invocation_failed"
        assert "【用户问题】" in report.input_prompt_snapshot
        assert report.last_llm_raw_output == ""
        assert report.generation_retry_count == 0
        assert report.generation_failure_reasons == []

    @pytest.mark.asyncio
    async def test_testing_agent_delivery_failure_persists_submission_in_outbox(self, tmp_path):
        knowledge_context_provider = AsyncMock()
        knowledge_context_provider.fetch_context.return_value = "Schema: (:Protocol)"
        llm_client = AsyncMock()
        llm_client.generate_from_prompt.return_value = {
            "raw_output": "MATCH (p:Protocol) RETURN p.version",
            "model_name": "test-model",
        }
        testing_client = AsyncMock()
        testing_client.submit.side_effect = RuntimeError("testing-agent offline")
        outbox = DeliveryOutbox(tmp_path / "outbox")

        service = CypherGeneratorAgentService(
            knowledge_context_provider=knowledge_context_provider,
            llm_client=llm_client,
            testing_client=testing_client,
            generation_run_id_factory=lambda: "cypher-run-outbox-001",
            delivery_outbox=outbox,
        )

        result = await service.ingest_question(QAQuestionRequest(id="qa-001", question="查询协议版本"))

        assert result.generation_status == "service_failed"
        assert result.reason == "testing_agent_submission_failed"
        pending = outbox.list_pending()
        assert len(pending) == 1
        assert pending[0]["payload_type"] == "GeneratedCypherSubmissionRequest"
        assert pending[0]["payload"]["id"] == "qa-001"

    @pytest.mark.asyncio
    async def test_background_delivery_deletes_outbox_record_after_accepted_ack(self, tmp_path):
        testing_client = AsyncMock()
        testing_client.submit.return_value = {"accepted": True}
        outbox = DeliveryOutbox(tmp_path / "outbox")
        outbox.save(
            payload_type="GeneratedCypherSubmissionRequest",
            payload={
                "id": "qa-001",
                "question": "查询协议版本",
                "generation_run_id": "cypher-run-outbox-002",
                "generated_cypher": "MATCH (p:Protocol) RETURN p.version",
                "input_prompt_snapshot": "prompt",
                "last_llm_raw_output": "MATCH (p:Protocol) RETURN p.version",
                "generation_retry_count": 0,
                "generation_failure_reasons": [],
            },
        )
        service = CypherGeneratorAgentService(
            knowledge_context_provider=AsyncMock(),
            llm_client=AsyncMock(),
            testing_client=testing_client,
            delivery_outbox=outbox,
        )

        await service.retry_pending_deliveries()

        assert outbox.list_pending() == []

    @pytest.mark.asyncio
    async def test_background_delivery_retries_current_submission_payload(self, tmp_path):
        testing_client = AsyncMock()
        testing_client.submit.return_value = {"accepted": True}
        outbox = DeliveryOutbox(tmp_path / "outbox")
        outbox.save(
            payload_type="GeneratedCypherSubmissionRequest",
            payload={
                "id": "qa-current",
                "question": "查询协议版本",
                "generation_run_id": "cypher-run-current",
                "generated_cypher": "MATCH (p:Protocol) RETURN p.version",
                "input_prompt_snapshot": "prompt",
                "last_llm_raw_output": "MATCH (p:Protocol) RETURN p.version",
                "generation_retry_count": 0,
                "generation_failure_reasons": [],
            },
        )
        service = CypherGeneratorAgentService(
            knowledge_context_provider=AsyncMock(),
            llm_client=AsyncMock(),
            testing_client=testing_client,
            delivery_outbox=outbox,
        )

        await service.retry_pending_deliveries()

        assert outbox.list_pending() == []
        payload = testing_client.submit.await_args.kwargs["payload"]
        assert payload.last_llm_raw_output == "MATCH (p:Protocol) RETURN p.version"
        assert payload.generation_retry_count == 0
        assert payload.generation_failure_reasons == []

    def test_outbox_retrying_records_are_not_selected_for_parallel_retry(self, tmp_path):
        outbox = DeliveryOutbox(tmp_path / "outbox")
        record = outbox.save(
            payload_type="GeneratedCypherSubmissionRequest",
            payload={
                "id": "qa-001",
                "question": "查询协议版本",
                "generation_run_id": "cypher-run-outbox-004",
                "generated_cypher": "MATCH (p:Protocol) RETURN p.version",
                "input_prompt_snapshot": "prompt",
                "last_llm_raw_output": "MATCH (p:Protocol) RETURN p.version",
                "generation_retry_count": 0,
                "generation_failure_reasons": [],
            },
        )

        outbox.mark_retrying(record["delivery_id"])

        assert outbox.list_retryable() == []

    def test_outbox_stale_retrying_records_become_retryable(self, tmp_path):
        from datetime import datetime, timedelta, timezone

        outbox = DeliveryOutbox(tmp_path / "outbox")
        record = outbox.save(
            payload_type="GeneratedCypherSubmissionRequest",
            payload={
                "id": "qa-001",
                "question": "查询协议版本",
                "generation_run_id": "cypher-run-outbox-005",
                "generated_cypher": "MATCH (p:Protocol) RETURN p.version",
                "input_prompt_snapshot": "prompt",
                "last_llm_raw_output": "MATCH (p:Protocol) RETURN p.version",
                "generation_retry_count": 0,
                "generation_failure_reasons": [],
            },
        )
        outbox.mark_retrying(record["delivery_id"])

        retryable = outbox.list_retryable(
            now=datetime.now(timezone.utc) + timedelta(seconds=301),
            retrying_timeout_seconds=300,
        )

        assert [item["delivery_id"] for item in retryable] == [record["delivery_id"]]

    def test_outbox_mark_pending_schedules_next_retry(self, tmp_path):
        from datetime import datetime, timezone

        outbox = DeliveryOutbox(tmp_path / "outbox")
        record = outbox.save(
            payload_type="GeneratedCypherSubmissionRequest",
            payload={
                "id": "qa-001",
                "question": "查询协议版本",
                "generation_run_id": "cypher-run-outbox-006",
                "generated_cypher": "MATCH (p:Protocol) RETURN p.version",
                "input_prompt_snapshot": "prompt",
                "last_llm_raw_output": "MATCH (p:Protocol) RETURN p.version",
                "generation_retry_count": 0,
                "generation_failure_reasons": [],
            },
        )

        pending = outbox.mark_pending(record["delivery_id"], "temporary failure", delay_seconds=30)

        assert datetime.fromisoformat(pending["next_retry_at"]) > datetime.now(timezone.utc)
        assert outbox.list_retryable() == []

    @pytest.mark.asyncio
    async def test_non_retryable_testing_agent_4xx_goes_to_dead_letter(self, tmp_path):
        knowledge_context_provider = AsyncMock()
        knowledge_context_provider.fetch_context.return_value = "Schema: (:Protocol)"
        llm_client = AsyncMock()
        llm_client.generate_from_prompt.return_value = {
            "raw_output": "MATCH (p:Protocol) RETURN p.version",
            "model_name": "test-model",
        }
        request = httpx.Request("POST", "http://testing-agent/api/v1/evaluations/submissions")
        response = httpx.Response(422, request=request)
        testing_client = AsyncMock()
        testing_client.submit.side_effect = httpx.HTTPStatusError(
            "unprocessable submission",
            request=request,
            response=response,
        )
        outbox = DeliveryOutbox(tmp_path / "outbox")

        service = CypherGeneratorAgentService(
            knowledge_context_provider=knowledge_context_provider,
            llm_client=llm_client,
            testing_client=testing_client,
            generation_run_id_factory=lambda: "cypher-run-outbox-003",
            delivery_outbox=outbox,
        )

        result = await service.ingest_question(QAQuestionRequest(id="qa-001", question="查询协议版本"))

        assert result.generation_status == "service_failed"
        assert outbox.list_pending() == []
        dead_letters = outbox.list_dead_letter()
        assert len(dead_letters) == 1
        assert dead_letters[0]["payload"]["id"] == "qa-001"
        assert dead_letters[0]["last_error"] == "unprocessable submission"


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


def test_preflight_allows_read_only_call_when_it_is_whitelisted():
    result = run_preflight_check(
        "CALL db.labels() YIELD label RETURN label",
        readonly_call_whitelist={"db.labels"},
    )

    assert result.accepted is True


def test_preflight_allows_semicolon_inside_string_literal():
    result = run_preflight_check('MATCH (n {name: "a;b"}) RETURN n')

    assert result.accepted is True


def test_preflight_ignores_semicolons_inside_comments():
    result = run_preflight_check(
        "MATCH (n) // this semicolon should be ignored ;\n"
        "RETURN n /* block ; comment */"
    )

    assert result.accepted is True


def test_preflight_check_enforces_reason_invariant():
    with pytest.raises(ValidationError):
        PreflightCheck(accepted=False)

    with pytest.raises(ValidationError):
        PreflightCheck(accepted=True, reason="empty_output")


def test_submission_payload_matches_testing_agent_contract():
    payload = GeneratedCypherSubmissionRequest(
        id="qa-001",
        question="查询协议版本",
        generation_run_id="cypher-run-001",
        generated_cypher="MATCH (p:Protocol) RETURN p.version",
        input_prompt_snapshot="prompt",
        last_llm_raw_output="MATCH (p:Protocol) RETURN p.version",
    )

    assert payload.model_dump() == {
        "id": "qa-001",
        "question": "查询协议版本",
        "generation_run_id": "cypher-run-001",
        "generated_cypher": "MATCH (p:Protocol) RETURN p.version",
        "input_prompt_snapshot": "prompt",
        "last_llm_raw_output": "MATCH (p:Protocol) RETURN p.version",
        "generation_retry_count": 0,
        "generation_failure_reasons": [],
    }


def test_generation_failure_report_matches_testing_agent_contract():
    payload = GenerationRunFailureReport(
        id="qa-001",
        question="查询协议版本",
        generation_run_id="cypher-run-001",
        generation_status="generation_failed",
        failure_reason="generation_retry_exhausted",
        last_generation_failure_reason="wrapped_in_markdown",
        input_prompt_snapshot="prompt",
        last_llm_raw_output="```cypher\nMATCH (p:Protocol) RETURN p.version\n```",
        generation_retry_count=2,
        generation_failure_reasons=[
            "wrapped_in_markdown",
            "wrapped_in_markdown",
            "wrapped_in_markdown",
        ],
        gate_passed=False,
    )

    assert payload.model_dump() == {
        "id": "qa-001",
        "question": "查询协议版本",
        "generation_run_id": "cypher-run-001",
        "generation_status": "generation_failed",
        "failure_reason": "generation_retry_exhausted",
        "last_generation_failure_reason": "wrapped_in_markdown",
        "input_prompt_snapshot": "prompt",
        "last_llm_raw_output": "```cypher\nMATCH (p:Protocol) RETURN p.version\n```",
        "generation_retry_count": 2,
        "generation_failure_reasons": [
            "wrapped_in_markdown",
            "wrapped_in_markdown",
            "wrapped_in_markdown",
        ],
        "parsed_cypher": None,
        "gate_passed": False,
    }


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
            generation_status="service_failed",
            reason="generator_configuration_invalid",
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
