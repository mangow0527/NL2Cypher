from __future__ import annotations

import pytest

from services.testing_agent.app.models import GeneratedCypherSubmissionRequest
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
