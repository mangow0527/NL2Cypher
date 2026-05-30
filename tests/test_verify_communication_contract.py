from __future__ import annotations

from contracts.models import GenerationEvidence
from services.cypher_generator_agent.app.api.models import GenerationFailureReason as GeneratorGenerationFailureReason
from services.cypher_generator_agent.app.api.models import CgaGenerationNonSuccessReport as GeneratorNonSuccessReport
from services.cypher_generator_agent.app.api.models import CgaQuestionReceivedReport as GeneratorQuestionReceivedReport
from services.testing_agent.app.models import (
    CgaGenerationNonSuccessReport as ReceiverNonSuccessReport,
    CgaQuestionReceivedReport as ReceiverQuestionReceivedReport,
    GeneratedCypherSubmissionRequest,
    GenerationFailureReason as ReceiverGenerationFailureReason,
)
from verify_communication import ServiceCommunicationTester


def test_build_submission_payload_uses_submission_contract():
    tester = ServiceCommunicationTester()

    payload = tester.build_submission_payload(
        task_id="comm-test-001",
        question_text="查询网络设备及其端口",
        generated_cypher="MATCH (ne:NetworkElement) RETURN ne.name AS device_name LIMIT 10",
        generation_run_id="run-001",
        input_prompt_snapshot="请只返回 cypher 字段",
    )

    assert payload == {
        "id": "comm-test-001",
        "question": "查询网络设备及其端口",
        "generation_run_id": "run-001",
        "generation_status": "generated",
        "generated_cypher": "MATCH (ne:NetworkElement) RETURN ne.name AS device_name LIMIT 10",
        "input_prompt_snapshot": "请只返回 cypher 字段",
    }


def test_generated_submission_request_matches_current_fields():
    payload = GeneratedCypherSubmissionRequest(
        id="qa-001",
        question="查询网络设备及其端口",
        generation_run_id="run-001",
        generated_cypher="MATCH (n:NetworkElement) RETURN n.name AS name LIMIT 10",
        input_prompt_snapshot="请只返回 cypher 字段",
    )

    assert payload.model_dump().keys() == {
        "id",
        "question",
        "generation_run_id",
        "generation_status",
        "generated_cypher",
        "input_prompt_snapshot",
    }


def test_generation_failed_non_success_report_contract_is_compatible_between_services():
    payload = {
        "id": "qa-001",
        "question": "查询网络设备及其端口",
        "generation_run_id": "run-001",
        "generation_status": "generation_failed",
        "input_prompt_snapshot": "prompt",
        "failure_reason": "unbalanced_brackets",
        "parsed_cypher": "MATCH (n RETURN n",
        "gate_passed": False,
    }

    assert GeneratorNonSuccessReport(**payload).model_dump() == ReceiverNonSuccessReport(**payload).model_dump()


def test_semantic_generation_failed_report_contract_is_compatible_between_services():
    payload = {
        "id": "qa-001",
        "question": "查询网络设备及其端口",
        "generation_run_id": "run-001",
        "generation_status": "generation_failed",
        "input_prompt_snapshot": "{\"semantic_view_matching\": {}}",
        "failure_reason": "unauthorized_schema_reference",
        "parsed_cypher": "MATCH (x:Secret) RETURN x",
        "gate_passed": False,
    }

    assert GeneratorNonSuccessReport(**payload).model_dump() == ReceiverNonSuccessReport(**payload).model_dump()


def test_service_failure_report_contract_is_compatible_between_services():
    payload = {
        "id": "qa-001",
        "question": "查询网络设备及其端口",
        "generation_run_id": "run-001",
        "generation_status": "service_failed",
        "input_prompt_snapshot": "",
        "failure_reason": "knowledge_context_unavailable",
        "parsed_cypher": None,
        "gate_passed": False,
    }

    assert GeneratorNonSuccessReport(**payload).model_dump() == ReceiverNonSuccessReport(**payload).model_dump()


def test_semantic_contract_service_failure_report_contract_is_compatible_between_services():
    payload = {
        "id": "qa-001",
        "question": "查询网络设备及其端口",
        "generation_run_id": "run-001",
        "generation_status": "service_failed",
        "input_prompt_snapshot": "{\"accepted\": false}",
        "failure_reason": "semantic_contract_unaligned",
        "parsed_cypher": None,
        "gate_passed": False,
    }

    assert GeneratorNonSuccessReport(**payload).model_dump() == ReceiverNonSuccessReport(**payload).model_dump()


def test_clarification_report_contract_is_compatible_between_services():
    payload = {
        "id": "qa-001",
        "question": "查询网络设备对应网元",
        "generation_run_id": "run-001",
        "generation_status": "clarification_required",
        "input_prompt_snapshot": "{\"clarification\": {}}",
        "clarification": {
            "source_stage": "semantic_view_matching",
            "reason_code": "ambiguous_path_semantic",
            "question_zh": "你说的对应网元是指源网元还是目的网元？",
            "expected_answer_type": "single_choice",
            "options": [{"id": "source", "label": "源网元"}],
        },
        "parsed_cypher": None,
        "gate_passed": False,
    }

    assert GeneratorNonSuccessReport(**payload).model_dump() == ReceiverNonSuccessReport(**payload).model_dump()


def test_unsupported_query_shape_report_contract_is_compatible_between_services():
    payload = {
        "id": "qa-unsupported",
        "question": "查询两台设备之间的最短路径",
        "generation_run_id": "run-unsupported",
        "generation_status": "unsupported_query_shape",
        "input_prompt_snapshot": "{\"trace_schema_version\":\"cga_graph_trace_v1\"}",
        "failure_reason": "unsupported_query_shape",
        "parsed_cypher": None,
        "gate_passed": False,
    }

    assert GeneratorNonSuccessReport(**payload).model_dump() == ReceiverNonSuccessReport(**payload).model_dump()


def test_question_received_report_contract_is_compatible_between_services():
    payload = {
        "id": "qa-pending",
        "question": "查询服务使用的隧道",
        "generation_run_id": "run-pending",
        "generation_status": "generation_pending",
    }

    assert GeneratorQuestionReceivedReport(**payload).model_dump() == ReceiverQuestionReceivedReport(**payload).model_dump()


def test_graph_generation_failure_reasons_are_compatible_between_services():
    for reason in [
        "cypher_syntax_invalid",
        "cypher_readonly_violation",
        "cypher_schema_reference_invalid",
        "compiler_shape_mismatch",
        "target_dialect_static_error",
        "coverage_failure",
        "literal_unresolved",
        "repair_binding_oscillation",
        "repair_requirements_unsatisfiable",
        "max_repair_attempts_exceeded",
    ]:
        payload = {
            "id": f"qa-{reason}",
            "question": "查询设备",
            "generation_run_id": f"run-{reason}",
            "generation_status": "generation_failed",
            "input_prompt_snapshot": "{}",
            "failure_reason": reason,
            "parsed_cypher": "",
            "gate_passed": False,
        }

        assert GeneratorNonSuccessReport(**payload).model_dump() == ReceiverNonSuccessReport(**payload).model_dump()


def test_generation_failure_reason_enums_are_synchronized_between_services():
    assert set(GeneratorGenerationFailureReason.__args__) == set(ReceiverGenerationFailureReason.__args__)


def test_generation_evidence_is_current_issue_ticket_snapshot():
    evidence = GenerationEvidence(
        generation_run_id="run-001",
        attempt_no=2,
        input_prompt_snapshot="请只返回 cypher 字段",
    )

    assert evidence.model_dump() == {
        "generation_run_id": "run-001",
        "attempt_no": 2,
        "input_prompt_snapshot": "请只返回 cypher 字段",
        "generation_status": "generated",
        "failure_reason": None,
    }
