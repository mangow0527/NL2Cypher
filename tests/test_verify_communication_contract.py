from __future__ import annotations

from contracts.models import GenerationEvidence
from services.cypher_generator_agent.app.models import GenerationRunFailureReport as GeneratorFailureReport
from services.testing_agent.app.models import GeneratedCypherSubmissionRequest, GenerationRunFailureReport as ReceiverFailureReport
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
        "generated_cypher": "MATCH (ne:NetworkElement) RETURN ne.name AS device_name LIMIT 10",
        "input_prompt_snapshot": "请只返回 cypher 字段",
        "last_llm_raw_output": "MATCH (ne:NetworkElement) RETURN ne.name AS device_name LIMIT 10",
        "generation_retry_count": 0,
        "generation_failure_reasons": [],
    }


def test_generated_submission_request_matches_current_fields():
    payload = GeneratedCypherSubmissionRequest(
        id="qa-001",
        question="查询网络设备及其端口",
        generation_run_id="run-001",
        generated_cypher="MATCH (n:NetworkElement) RETURN n.name AS name LIMIT 10",
        input_prompt_snapshot="请只返回 cypher 字段",
        last_llm_raw_output="MATCH (n:NetworkElement) RETURN n.name AS name LIMIT 10",
    )

    assert payload.model_dump().keys() == {
        "id",
        "question",
        "generation_run_id",
        "generated_cypher",
        "input_prompt_snapshot",
        "last_llm_raw_output",
        "generation_retry_count",
        "generation_failure_reasons",
    }


def test_generation_failure_report_contract_is_compatible_between_services():
    payload = {
        "id": "qa-001",
        "question": "查询网络设备及其端口",
        "generation_run_id": "run-001",
        "input_prompt_snapshot": "prompt",
        "last_llm_raw_output": "MATCH (n RETURN n",
        "generation_status": "generation_failed",
        "failure_reason": "generation_retry_exhausted",
        "last_generation_failure_reason": "unbalanced_brackets",
        "generation_retry_count": 2,
        "generation_failure_reasons": ["unbalanced_brackets", "unbalanced_brackets", "unbalanced_brackets"],
        "parsed_cypher": "MATCH (n RETURN n",
        "gate_passed": False,
    }

    assert GeneratorFailureReport(**payload).model_dump() == ReceiverFailureReport(**payload).model_dump()


def test_service_failure_report_contract_is_compatible_between_services():
    payload = {
        "id": "qa-001",
        "question": "查询网络设备及其端口",
        "generation_run_id": "run-001",
        "input_prompt_snapshot": "",
        "last_llm_raw_output": "",
        "generation_status": "service_failed",
        "failure_reason": "knowledge_context_unavailable",
        "generation_retry_count": 0,
        "generation_failure_reasons": [],
        "parsed_cypher": None,
        "gate_passed": False,
    }

    assert GeneratorFailureReport(**payload).model_dump() == ReceiverFailureReport(**payload).model_dump()


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
        "last_llm_raw_output": "",
        "generation_retry_count": 0,
        "generation_failure_reasons": [],
        "failure_reason": None,
    }
