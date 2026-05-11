from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.testing_agent.app.models import CgaGenerationNonSuccessReport, GeneratedCypherSubmissionRequest
from services.testing_agent.app.repository import TestingRepository


def test_repository_assigns_attempt_numbers_for_new_submissions(tmp_path):
    repository = TestingRepository(str(tmp_path / "testing"))

    first_attempt = repository.save_submission(
        GeneratedCypherSubmissionRequest(
            id="qa-001",
            question="查询设备",
            generation_run_id="run-001",
            generated_cypher="MATCH (n) RETURN n",
            input_prompt_snapshot="prompt-1",
        ),
        state="received_submission_only",
    )
    second_attempt = repository.save_submission(
        GeneratedCypherSubmissionRequest(
            id="qa-001",
            question="查询设备",
            generation_run_id="run-002",
            generated_cypher="MATCH (n) RETURN n LIMIT 1",
            input_prompt_snapshot="prompt-2",
        ),
        state="received_submission_only",
    )

    assert first_attempt.attempt_no == 1
    assert second_attempt.attempt_no == 2
    assert repository.get_submission_attempt("qa-001", 1)["generation_run_id"] == "run-001"
    assert repository.get_submission_attempt("qa-001", 2)["generation_run_id"] == "run-002"


def test_repository_treats_identical_submission_as_idempotent(tmp_path):
    repository = TestingRepository(str(tmp_path / "testing"))
    request = GeneratedCypherSubmissionRequest(
        id="qa-001",
        question="查询设备",
        generation_run_id="run-001",
        generated_cypher="MATCH (n) RETURN n",
        input_prompt_snapshot="prompt-1",
    )

    first = repository.save_submission(request, state="received_submission_only")
    duplicate = repository.save_submission(request, state="ready_to_evaluate")

    assert first.attempt_no == 1
    assert duplicate.attempt_no == 1
    assert duplicate.created is False
    latest = repository.get_submission("qa-001")
    assert latest["state"] == "received_submission_only"


def test_repository_rejects_conflicting_submission_for_same_generation_run_id(tmp_path):
    repository = TestingRepository(str(tmp_path / "testing"))
    repository.save_submission(
        GeneratedCypherSubmissionRequest(
            id="qa-001",
            question="查询设备",
            generation_run_id="run-001",
            generated_cypher="MATCH (n) RETURN n",
            input_prompt_snapshot="prompt-1",
        ),
        state="received_submission_only",
    )

    with pytest.raises(ValueError, match="Submission conflict"):
        repository.save_submission(
            GeneratedCypherSubmissionRequest(
                id="qa-001",
                question="查询设备",
                generation_run_id="run-001",
                generated_cypher="MATCH (n) RETURN n LIMIT 1",
                input_prompt_snapshot="prompt-2",
            ),
            state="received_submission_only",
        )


def test_repository_persists_service_failed_report_without_assigning_attempt_number(tmp_path):
    repository = TestingRepository(str(tmp_path / "testing"))
    report = CgaGenerationNonSuccessReport(
        id="qa-001",
        question="查询设备",
        generation_run_id="run-service-failed",
        input_prompt_snapshot="prompt-before-model-call",
        generation_status="service_failed",
        failure_reason="model_invocation_failed",
        parsed_cypher=None,
        gate_passed=False,
    )

    repository.save_generation_failure_report(report)

    assert repository.list_submission_attempts("qa-001") == []
    persisted = repository.get_generation_failure_report("qa-001", "run-service-failed")
    assert persisted is not None
    assert persisted["generation_status"] == "service_failed"
    assert "attempt_no" not in persisted


def test_generation_failed_report_defaults_gate_passed_to_false():
    report = CgaGenerationNonSuccessReport(
        id="qa-001",
        question="查询设备",
        generation_run_id="run-generation-failed",
        input_prompt_snapshot="prompt-before-gate",
        generation_status="generation_failed",
        failure_reason="no_cypher_found",
        parsed_cypher="",
    )

    assert report.gate_passed is False


def test_generation_failed_report_rejects_gate_passed_true():
    with pytest.raises(ValidationError, match="gate_passed=true"):
        CgaGenerationNonSuccessReport(
            id="qa-001",
            question="查询设备",
            generation_run_id="run-generation-failed",
            input_prompt_snapshot="prompt-before-gate",
            generation_status="generation_failed",
            failure_reason="no_cypher_found",
            parsed_cypher="",
            gate_passed=True,
        )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "id": "qa-clarification",
            "question": "查询服务 A 对应的网元",
            "generation_run_id": "run-clarification",
            "input_prompt_snapshot": '{"schema_version":"cga_trace_v2"}',
            "generation_status": "clarification_required",
            "clarification": {
                "source_stage": "semantic_view_matching",
                "reason_code": "ambiguous_path_semantic",
                "question_zh": "你说的对应网元是指源网元还是目的网元？",
                "expected_answer_type": "single_choice",
                "options": [{"id": "source", "label": "源网元"}],
            },
            "gate_passed": True,
        },
        {
            "id": "qa-service-failed",
            "question": "查询设备",
            "generation_run_id": "run-service-failed",
            "input_prompt_snapshot": "",
            "generation_status": "service_failed",
            "failure_reason": "model_invocation_failed",
            "parsed_cypher": None,
            "gate_passed": True,
        },
    ],
)
def test_non_generation_attempt_reports_reject_gate_passed_true(payload):
    with pytest.raises(ValidationError, match="gate_passed=true"):
        CgaGenerationNonSuccessReport(**payload)
