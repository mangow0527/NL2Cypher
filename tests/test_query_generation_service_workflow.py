from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from services.cypher_generator_agent.app.outbox import DeliveryOutbox
from services.cypher_generator_agent.app.config import Settings
from services.cypher_generator_agent.app.knowledge_selection import RagKnowledgeSelector
from services.cypher_generator_agent.app.models import (
    CgaGenerationNonSuccessReport,
    GeneratedCypherSubmissionRequest,
    GenerationRunResult,
    PreflightCheck,
    QAQuestionRequest,
)
from services.cypher_generator_agent.app.parser import parse_model_output
from services.cypher_generator_agent.app.preflight import run_preflight_check
from services.cypher_generator_agent.app.semantic_alignment import (
    SemanticAlignmentDiagnostic,
    SemanticAlignmentReport,
)
from services.cypher_generator_agent.app.service import (
    CypherGeneratorAgentService,
    build_workflow_service,
    get_generator_status,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "services/testing_agent/docs/reference/schema.json"


def write_valid_knowledge_docs(knowledge_dir):
    knowledge_dir.mkdir()
    (knowledge_dir / "system_prompt.md").write_text("System prompt", encoding="utf-8")
    (knowledge_dir / "schema.json").write_text('{"nodes":[{"label":"Protocol"}]}', encoding="utf-8")
    (knowledge_dir / "cypher_syntax.md").write_text("Cypher syntax", encoding="utf-8")
    (knowledge_dir / "business_knowledge.md").write_text("Business knowledge", encoding="utf-8")
    (knowledge_dir / "few_shot.md").write_text("Few-shot examples", encoding="utf-8")


def test_build_workflow_service_uses_semantic_pipeline_with_rag_selector(tmp_path):
    settings = Settings(
        knowledge_docs_dir=str(tmp_path / "knowledge"),
        knowledge_context_source="rag",
        rag_service_url="http://rag-service",
        testing_agent_url="http://testing-agent",
        llm_base_url="http://llm",
        llm_api_key="test-key",
        llm_model="test-model",
        _env_file=None,
    )

    service = build_workflow_service(settings)

    assert service.semantic_pipeline is not None
    assert isinstance(service.semantic_pipeline.knowledge_selector, RagKnowledgeSelector)
    assert service.semantic_pipeline.knowledge_selector.base_url == "http://rag-service"
    assert not hasattr(service, "knowledge_context_provider")
    assert not hasattr(service, "llm_client")


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
    assert status["knowledge_selection_configured"] is False
    assert "knowledge_agent_configured" not in status


def test_generator_status_reports_semantic_alignment(monkeypatch, tmp_path):
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "system_prompt.md").write_text("只能使用 Schema 中存在的节点、关系、属性。", encoding="utf-8")
    (knowledge_dir / "schema.json").write_text(SCHEMA_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    (knowledge_dir / "cypher_syntax.md").write_text("聚合使用 RETURN/WITH 隐式分组。", encoding="utf-8")
    (knowledge_dir / "business_knowledge.md").write_text(
        "- “链路类型”映射为 `Link.elem_type`。\n"
        "- “链路目的端口”表示 `(l:Link)-[:LINK_DST]->(p:Port)`。",
        encoding="utf-8",
    )
    (knowledge_dir / "few_shot.md").write_text(
        "Question: 按类型统计隧道数量\n"
        "Cypher: MATCH (t:Tunnel) RETURN t.elem_type AS group_key, count(t) AS total",
        encoding="utf-8",
    )
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

    assert status["semantic_alignment"]["accepted"] is True
    assert status["semantic_alignment"]["diagnostics"] == []
    assert "semantic_layer.yaml" in status["semantic_alignment"]["checked_sources"]
    assert "knowledge/schema.json" in status["semantic_alignment"]["checked_sources"]


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
    assert status["knowledge_selection_configured"] is False


class TestCypherGeneratorAgentWorkflow:
    @pytest.mark.asyncio
    async def test_workflow_service_has_no_direct_llm_generation_branch(self):
        class FakeSemanticPipeline:
            async def parse_with_fallback(self, *, id, question, generation_run_id):
                return type(
                    "SemanticResult",
                    (),
                    {
                        "generated_cypher": "MATCH (s:Service) RETURN s.name AS service_name",
                        "preflight": PreflightCheck(accepted=True),
                        "generation_mode": "deterministic_renderer",
                        "to_dict": lambda self: {
                            "generation_mode": "deterministic_renderer",
                            "semantic_query": {"kind": "record_selection"},
                            "generated_cypher": "MATCH (s:Service) RETURN s.name AS service_name",
                            "preflight": {"accepted": True},
                        },
                    },
                )()

        service = CypherGeneratorAgentService(
            testing_client=AsyncMock(),
            generation_run_id_factory=lambda: "cypher-run-semantic-only",
            semantic_pipeline=FakeSemanticPipeline(),
        )

        result = await service.ingest_question(QAQuestionRequest(id="qa-semantic-only", question="查询服务名称"))

        assert result.generation_status == "submitted_to_testing"
        assert not hasattr(service, "knowledge_context_provider")
        assert not hasattr(service, "llm_client")

    @pytest.mark.asyncio
    async def test_semantic_pipeline_result_is_submitted_without_legacy_knowledge_fetch(self):
        class FakeSemanticPipeline:
            def __init__(self) -> None:
                self.calls = []

            async def parse_with_fallback(self, *, id, question, generation_run_id):
                self.calls.append({"id": id, "question": question, "generation_run_id": generation_run_id})
                return type(
                    "SemanticResult",
                    (),
                    {
                        "generated_cypher": "MATCH (s:Service) RETURN s.name AS service_name",
                        "preflight": PreflightCheck(accepted=True),
                        "generation_mode": "deterministic_renderer",
                        "to_dict": lambda self: {
                            "generation_mode": "deterministic_renderer",
                            "semantic_query": {"kind": "record_selection"},
                            "generated_cypher": "MATCH (s:Service) RETURN s.name AS service_name",
                            "preflight": {"accepted": True},
                        },
                    },
                )()

        testing_client = AsyncMock()
        semantic_pipeline = FakeSemanticPipeline()

        service = CypherGeneratorAgentService(
            testing_client=testing_client,
            generation_run_id_factory=lambda: "cypher-run-semantic-001",
            semantic_pipeline=semantic_pipeline,
        )

        result = await service.ingest_question(QAQuestionRequest(id="qa-semantic", question="查询服务名称"))

        assert result.generation_status == "submitted_to_testing"
        assert semantic_pipeline.calls == [
            {"id": "qa-semantic", "question": "查询服务名称", "generation_run_id": "cypher-run-semantic-001"}
        ]
        testing_client.submit.assert_awaited_once()
        submission = testing_client.submit.await_args.kwargs["payload"]
        assert submission.generated_cypher == "MATCH (s:Service) RETURN s.name AS service_name"
        assert '"semantic_query"' in submission.input_prompt_snapshot
        assert submission.generation_status == "generated"

    @pytest.mark.asyncio
    async def test_semantic_pipeline_rejection_submits_generation_failure(self):
        class FakeSemanticPipeline:
            async def parse_with_fallback(self, *, id, question, generation_run_id):
                return type(
                    "SemanticResult",
                    (),
                    {
                        "generated_cypher": None,
                        "preflight": None,
                        "generation_mode": None,
                        "to_dict": lambda self: {
                            "validation": {
                                "accepted": False,
                                "diagnostics": [{"code": "unsupported_business_slot_schema"}],
                            },
                            "semantic_query": None,
                            "generated_cypher": None,
                            "preflight": None,
                        },
                    },
                )()

        service = CypherGeneratorAgentService(
            testing_client=AsyncMock(),
            generation_run_id_factory=lambda: "cypher-run-semantic-002",
            semantic_pipeline=FakeSemanticPipeline(),
        )

        result = await service.ingest_question(QAQuestionRequest(id="qa-semantic-fail", question="查询链路状态历史变化"))

        assert result.generation_status == "generation_failed"
        assert result.reason == "semantic_match_rejected"
        service.testing_client.submit.assert_not_called()
        service.testing_client.submit_generation_failure.assert_awaited_once()
        report = service.testing_client.submit_generation_failure.await_args.kwargs["payload"]
        assert report.failure_reason == "semantic_match_rejected"
        assert report.parsed_cypher is None

    @pytest.mark.asyncio
    async def test_semantic_contract_misalignment_is_service_failure_without_knowledge_fetch(self):
        testing_client = AsyncMock()
        semantic_pipeline = AsyncMock()

        service = CypherGeneratorAgentService(
            testing_client=testing_client,
            generation_run_id_factory=lambda: "cypher-run-semantic-contract",
            semantic_pipeline=semantic_pipeline,
            semantic_alignment_report_factory=lambda: SemanticAlignmentReport(
                accepted=False,
                diagnostics=[
                    SemanticAlignmentDiagnostic(
                        code="knowledge_schema_mismatch",
                        message="knowledge schema references unknown TuGraph property Link.type",
                        source="knowledge/schema.json",
                    )
                ],
                checked_sources=["semantic_layer.yaml", "schema.json", "knowledge/schema.json"],
            ),
        )

        result = await service.ingest_question(QAQuestionRequest(id="qa-contract", question="查询链路类型"))

        assert result.generation_status == "service_failed"
        assert result.reason == "semantic_contract_unaligned"
        semantic_pipeline.parse_with_fallback.assert_not_awaited()
        testing_client.submit_generation_failure.assert_awaited_once()
        report = testing_client.submit_generation_failure.await_args.kwargs["payload"]
        assert report.failure_reason == "semantic_contract_unaligned"
        assert "knowledge schema references unknown TuGraph property Link.type" in report.input_prompt_snapshot

    @pytest.mark.asyncio
    async def test_alignment_context_unavailable_blocks_before_semantic_parse(self):
        testing_client = AsyncMock()
        semantic_pipeline = AsyncMock()

        service = CypherGeneratorAgentService(
            testing_client=testing_client,
            generation_run_id_factory=lambda: "cypher-run-knowledge-unavailable",
            semantic_pipeline=semantic_pipeline,
            semantic_alignment_report_factory=lambda: SemanticAlignmentReport(
                accepted=False,
                diagnostics=[
                    SemanticAlignmentDiagnostic(
                        code="knowledge_context_unavailable",
                        message="knowledge context directory does not exist",
                        source="knowledge",
                    )
                ],
                checked_sources=["semantic_layer.yaml", "schema.json"],
            ),
        )

        result = await service.ingest_question(QAQuestionRequest(id="qa-missing-knowledge", question="查询协议版本"))

        assert result.generation_status == "service_failed"
        assert result.reason == "knowledge_context_unavailable"
        semantic_pipeline.parse_with_fallback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_alignment_invalid_knowledge_schema_blocks_generation(self):
        testing_client = AsyncMock()
        semantic_pipeline = AsyncMock()

        service = CypherGeneratorAgentService(
            testing_client=testing_client,
            generation_run_id_factory=lambda: "cypher-run-invalid-knowledge-schema",
            semantic_pipeline=semantic_pipeline,
            semantic_alignment_report_factory=lambda: SemanticAlignmentReport(
                accepted=False,
                diagnostics=[
                    SemanticAlignmentDiagnostic(
                        code="knowledge_schema_invalid",
                        message="knowledge/schema.json is not valid JSON",
                        source="knowledge/schema.json",
                    )
                ],
                checked_sources=["semantic_layer.yaml", "schema.json", "knowledge/schema.json"],
            ),
        )

        result = await service.ingest_question(QAQuestionRequest(id="qa-invalid-schema", question="查询链路类型"))

        assert result.generation_status == "service_failed"
        assert result.reason == "semantic_contract_unaligned"
        semantic_pipeline.parse_with_fallback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_testing_agent_delivery_failure_persists_submission_in_outbox(self, tmp_path):
        class FakeSemanticPipeline:
            async def parse_with_fallback(self, *, id, question, generation_run_id):
                return type(
                    "SemanticResult",
                    (),
                    {
                        "generated_cypher": "MATCH (p:Protocol) RETURN p.version",
                        "preflight": PreflightCheck(accepted=True),
                        "to_dict": lambda self: {
                            "generated_cypher": "MATCH (p:Protocol) RETURN p.version",
                            "preflight": {"accepted": True},
                        },
                    },
                )()

        testing_client = AsyncMock()
        testing_client.submit.side_effect = RuntimeError("testing-agent offline")
        outbox = DeliveryOutbox(tmp_path / "outbox")

        service = CypherGeneratorAgentService(
            testing_client=testing_client,
            generation_run_id_factory=lambda: "cypher-run-outbox-001",
            delivery_outbox=outbox,
            semantic_pipeline=FakeSemanticPipeline(),
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
                "generation_status": "generated",
                "generated_cypher": "MATCH (p:Protocol) RETURN p.version",
                "input_prompt_snapshot": "prompt",
            },
        )
        service = CypherGeneratorAgentService(
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
                "generation_status": "generated",
                "generated_cypher": "MATCH (p:Protocol) RETURN p.version",
                "input_prompt_snapshot": "prompt",
            },
        )
        service = CypherGeneratorAgentService(
            testing_client=testing_client,
            delivery_outbox=outbox,
        )

        await service.retry_pending_deliveries()

        assert outbox.list_pending() == []
        payload = testing_client.submit.await_args.kwargs["payload"]
        assert payload.generation_status == "generated"

    def test_outbox_retrying_records_are_not_selected_for_parallel_retry(self, tmp_path):
        outbox = DeliveryOutbox(tmp_path / "outbox")
        record = outbox.save(
            payload_type="GeneratedCypherSubmissionRequest",
            payload={
                "id": "qa-001",
                "question": "查询协议版本",
                "generation_run_id": "cypher-run-outbox-004",
                "generation_status": "generated",
                "generated_cypher": "MATCH (p:Protocol) RETURN p.version",
                "input_prompt_snapshot": "prompt",
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
                "generation_status": "generated",
                "generated_cypher": "MATCH (p:Protocol) RETURN p.version",
                "input_prompt_snapshot": "prompt",
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
                "generation_status": "generated",
                "generated_cypher": "MATCH (p:Protocol) RETURN p.version",
                "input_prompt_snapshot": "prompt",
            },
        )

        pending = outbox.mark_pending(record["delivery_id"], "temporary failure", delay_seconds=30)

        assert datetime.fromisoformat(pending["next_retry_at"]) > datetime.now(timezone.utc)
        assert outbox.list_retryable() == []

    @pytest.mark.asyncio
    async def test_non_retryable_testing_agent_4xx_goes_to_dead_letter(self, tmp_path):
        class FakeSemanticPipeline:
            async def parse_with_fallback(self, *, id, question, generation_run_id):
                return type(
                    "SemanticResult",
                    (),
                    {
                        "generated_cypher": "MATCH (p:Protocol) RETURN p.version",
                        "preflight": PreflightCheck(accepted=True),
                        "to_dict": lambda self: {
                            "generated_cypher": "MATCH (p:Protocol) RETURN p.version",
                            "preflight": {"accepted": True},
                        },
                    },
                )()

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
            testing_client=testing_client,
            generation_run_id_factory=lambda: "cypher-run-outbox-003",
            delivery_outbox=outbox,
            semantic_pipeline=FakeSemanticPipeline(),
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
        generation_status="generated",
        generated_cypher="MATCH (p:Protocol) RETURN p.version",
        input_prompt_snapshot="prompt",
    )

    assert payload.model_dump() == {
        "id": "qa-001",
        "question": "查询协议版本",
        "generation_run_id": "cypher-run-001",
        "generation_status": "generated",
        "generated_cypher": "MATCH (p:Protocol) RETURN p.version",
        "input_prompt_snapshot": "prompt",
    }


def test_non_success_report_matches_testing_agent_generation_failed_contract():
    payload = CgaGenerationNonSuccessReport(
        id="qa-001",
        question="查询协议版本",
        generation_run_id="cypher-run-001",
        generation_status="generation_failed",
        failure_reason="unbalanced_brackets",
        input_prompt_snapshot="prompt",
        parsed_cypher="MATCH (p:Protocol RETURN p.version",
        gate_passed=False,
    )

    assert payload.model_dump() == {
        "id": "qa-001",
        "question": "查询协议版本",
        "generation_run_id": "cypher-run-001",
        "generation_status": "generation_failed",
        "input_prompt_snapshot": "prompt",
        "failure_reason": "unbalanced_brackets",
        "clarification": None,
        "parsed_cypher": "MATCH (p:Protocol RETURN p.version",
        "gate_passed": False,
    }


def test_non_success_report_matches_testing_agent_clarification_contract():
    clarification = {
        "source_stage": "semantic_view_matching",
        "reason_code": "ambiguous_path_semantic",
        "question_zh": "你说的对应网元是指源网元还是目的网元？",
        "expected_answer_type": "single_choice",
        "options": [{"id": "source", "label": "源网元"}],
    }
    payload = CgaGenerationNonSuccessReport(
        id="qa-002",
        question="查询服务 A 对应的网元",
        generation_run_id="cypher-run-002",
        generation_status="clarification_required",
        input_prompt_snapshot="prompt",
        clarification=clarification,
    )

    assert payload.model_dump() == {
        "id": "qa-002",
        "question": "查询服务 A 对应的网元",
        "generation_run_id": "cypher-run-002",
        "generation_status": "clarification_required",
        "input_prompt_snapshot": "prompt",
        "failure_reason": None,
        "clarification": clarification,
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
            reason="not_a_generation_reason",
        )


def test_parser_rejects_cypher_with_explanation_text_after_query():
    parsed = parse_model_output(
        "MATCH (p:Protocol) RETURN p.version\n"
        "This query returns all protocol versions."
    )

    assert parsed.parsed_cypher == ""
    assert parsed.reason == "contains_explanation"
