from __future__ import annotations

import json

from contracts.models import EvaluationSubmissionRequest
from services.query_generator_agent.app.repository import QueryGeneratorRepository
from services.testing_agent.app.repository import TestingRepository as TestingRepo

QueryGeneratorRepository.__test__ = False
TestingRepo.__test__ = False


def test_query_repository_infers_next_attempt_from_legacy_latest_run(tmp_path):
    repository = QueryGeneratorRepository(str(tmp_path / "query"))
    repository.upsert_question(id="qa_legacy", question="旧题", status="generated")

    question_path = tmp_path / "query" / "questions" / "qa_legacy.json"
    question = json.loads(question_path.read_text(encoding="utf-8"))
    question.pop("latest_attempt_no", None)
    question_path.write_text(json.dumps(question, ensure_ascii=False, indent=2), encoding="utf-8")

    latest_run_path = tmp_path / "query" / "generation_runs" / "qa_legacy.json"
    latest_run_path.parent.mkdir(parents=True, exist_ok=True)
    latest_run_path.write_text(
        json.dumps(
            {
                "id": "qa_legacy",
                "generation_run_id": "run-001",
                "generation_status": "generated",
                "generated_cypher": "MATCH (n) RETURN n LIMIT 5",
                "parse_summary": "parsed",
                "guardrail_summary": "accepted",
                "raw_output_snapshot": "MATCH (n) RETURN n LIMIT 5",
                "failure_stage": None,
                "failure_reason_summary": None,
                "input_prompt_snapshot": "legacy prompt",
                "finished_at": "2026-04-14T00:00:00+00:00",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    assert repository.next_attempt_no("qa_legacy") == 2

    repository.save_generation_run(
        id="qa_legacy",
        generation_run_id="run-002",
        attempt_no=2,
        generation_status="generated",
        generated_cypher="MATCH (n) RETURN n LIMIT 3",
        parse_summary="parsed",
        guardrail_summary="accepted",
        raw_output_snapshot="MATCH (n) RETURN n LIMIT 3",
        failure_stage=None,
        failure_reason_summary=None,
        input_prompt_snapshot="new prompt",
    )

    legacy_attempt = repository.list_generation_runs("qa_legacy")[0]
    latest_question = repository.get_question("qa_legacy")

    assert legacy_attempt["generation_run_id"] == "run-001"
    assert legacy_attempt["attempt_no"] == 1
    assert latest_question is not None
    assert latest_question["latest_attempt_no"] == 2


def test_testing_repository_archives_legacy_latest_submission_before_attempt_two(tmp_path):
    repository = TestingRepo(str(tmp_path / "testing"))
    latest_path = tmp_path / "testing" / "submissions" / "qa_legacy.json"
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(
        json.dumps(
            {
                "id": "qa_legacy",
                "question": "旧题",
                "generation_run_id": "run-001",
                "generated_cypher": "MATCH (n) RETURN n LIMIT 5",
                "parse_summary": "parsed",
                "guardrail_summary": "accepted",
                "raw_output_snapshot": "MATCH (n) RETURN n LIMIT 5",
                "input_prompt_snapshot": "legacy prompt",
                "execution_json": None,
                "issue_ticket_id": None,
                "krss_response": None,
                "improvement_assessment": None,
                "status": "waiting_for_golden",
                "received_at": "2026-04-14T00:00:00+00:00",
                "updated_at": "2026-04-14T00:00:00+00:00",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    repository.save_submission(
        EvaluationSubmissionRequest(
            id="qa_legacy",
            question="旧题",
            generation_run_id="run-002",
            attempt_no=2,
            generated_cypher="MATCH (n) RETURN n LIMIT 3",
            parse_summary="parsed",
            guardrail_summary="accepted",
            raw_output_snapshot="MATCH (n) RETURN n LIMIT 3",
            input_prompt_snapshot="new prompt",
        ),
        status="ready_to_evaluate",
    )

    previous = repository.get_submission_attempt("qa_legacy", 1)
    current = repository.get_submission_attempt("qa_legacy", 2)

    assert previous is not None
    assert previous["generation_run_id"] == "run-001"
    assert previous["attempt_no"] == 1
    assert current is not None
    assert current["generation_run_id"] == "run-002"
    assert current["attempt_no"] == 2
