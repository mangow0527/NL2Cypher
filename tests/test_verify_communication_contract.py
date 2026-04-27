from __future__ import annotations

from contracts.models import GenerationEvidence
from services.testing_agent.app.models import GeneratedCypherSubmissionRequest
from verify_communication import ServiceCommunicationTester


def test_build_submission_payload_uses_minimal_submission_contract():
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
        "generated_cypher",
        "input_prompt_snapshot",
    }


def test_generation_evidence_is_minimal_issue_ticket_snapshot():
    evidence = GenerationEvidence(
        generation_run_id="run-001",
        attempt_no=2,
        input_prompt_snapshot="请只返回 cypher 字段",
    )

    assert evidence.model_dump() == {
        "generation_run_id": "run-001",
        "attempt_no": 2,
        "input_prompt_snapshot": "请只返回 cypher 字段",
    }
