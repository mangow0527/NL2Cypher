from __future__ import annotations

from shared.models import EvaluationSubmissionRequest
from verify_communication import ServiceCommunicationTester


def test_build_submission_payload_uses_current_contract():
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
        "parse_summary": "communication_test_payload",
        "guardrail_summary": "accepted",
        "raw_output_snapshot": "",
        "input_prompt_snapshot": "请只返回 cypher 字段",
    }


def test_evaluation_submission_request_matches_current_fields():
    payload = EvaluationSubmissionRequest(
        id="qa-001",
        question="查询网络设备及其端口",
        generation_run_id="run-001",
        generated_cypher="MATCH (n:NetworkElement) RETURN n.name AS name LIMIT 10",
        parse_summary="parsed_json",
        guardrail_summary="accepted",
        raw_output_snapshot="",
        input_prompt_snapshot="请只返回 cypher 字段",
    )

    assert payload.model_dump().keys() == {
        "id",
        "question",
        "generation_run_id",
        "generated_cypher",
        "parse_summary",
        "guardrail_summary",
        "raw_output_snapshot",
        "input_prompt_snapshot",
    }
