from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from contracts.models import (
    ActualAnswer,
    EvaluationDimensions,
    EvaluationSubmissionRequest,
    EvaluationSummary,
    ExpectedAnswer,
    ImprovementAssessment,
    ImprovementDimensions,
    IssueTicket,
    KRSSAnalysisRecord,
    KnowledgeRepairSuggestionRequest,
    QAGoldenRequest,
)


def test_runtime_results_center_html_exposes_task_list_and_cypher_quality(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_QUERY_GENERATOR_DATA_DIR", str(tmp_path / "query"))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(tmp_path / "testing"))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(tmp_path / "repair"))

    from console.runtime_console.app.main import create_app

    client = TestClient(create_app())

    response = client.get("/console")

    assert response.status_code == 200
    assert "运行结果中心" in response.text
    assert "Runtime Results Center" in response.text
    assert "Cypher 结果与质量" in response.text
    assert "KRSS 诊断摘要" in response.text
    assert "Testing Service 持久化的 IssueTicket 与 KRSSAnalysisRecord" in response.text
    assert "任务列表" in response.text
    assert "服务运行状态" in response.text
    assert "开始联调" not in response.text


def test_runtime_results_service_status_endpoint_returns_five_service_cards(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_QUERY_GENERATOR_DATA_DIR", str(tmp_path / "query"))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(tmp_path / "testing"))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(tmp_path / "repair"))

    from console.runtime_console.app.main import create_app
    from console.runtime_console.app.service import RuntimeResultsService

    mock_cards = [
        {"service_key": "cgs", "label_zh": "查询生成服务", "status": "online"},
        {"service_key": "testing_service", "label_zh": "测试服务", "status": "online"},
        {"service_key": "krss", "label_zh": "知识修复建议服务", "status": "offline"},
        {"service_key": "knowledge_ops", "label_zh": "知识运营服务", "status": "online"},
        {"service_key": "qa_generator", "label_zh": "问答生成服务", "status": "online"},
    ]
    monkeypatch.setattr(
        RuntimeResultsService,
        "get_runtime_services",
        AsyncMock(return_value={"title_zh": "服务运行状态", "title_en": "Runtime Service Status", "services": mock_cards}),
    )

    client = TestClient(create_app())

    response = client.get("/api/v1/runtime/services")

    assert response.status_code == 200
    payload = response.json()
    assert payload["title_zh"] == "服务运行状态"
    assert [service["service_key"] for service in payload["services"]] == [
        "cgs",
        "testing_service",
        "krss",
        "knowledge_ops",
        "qa_generator",
    ]


def test_runtime_results_service_uses_local_health_client_boundary():
    import console.runtime_console.app.service as runtime_service_module

    assert runtime_service_module.ServiceHealthClient.__module__ == "console.runtime_console.app.service"


def test_runtime_results_tasks_only_include_qa_generator_items(monkeypatch, tmp_path: Path):
    query_dir = tmp_path / "query"
    testing_dir = tmp_path / "testing"
    repair_dir = tmp_path / "repair"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_QUERY_GENERATOR_DATA_DIR", str(query_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(repair_dir))

    from services.cypher_generator_agent.app.repository import QueryGeneratorRepository
    from console.runtime_console.app.main import create_app

    query_repository = QueryGeneratorRepository(str(query_dir))
    query_repository.upsert_question(id="qa_old", question="旧问题", status="generated")
    query_repository.save_generation_run(
        id="qa_old",
        generation_run_id="run-old",
        attempt_no=1,
        generation_status="generated",
        generated_cypher="MATCH (n) RETURN n LIMIT 5",
        parse_summary="ok",
        guardrail_summary="passed",
        raw_output_snapshot="{}",
        failure_stage=None,
        failure_reason_summary=None,
        input_prompt_snapshot="old prompt",
    )
    query_repository.upsert_question(id="qa_new", question="新问题", status="generated")
    query_repository.save_generation_run(
        id="qa_new",
        generation_run_id="run-new",
        attempt_no=1,
        generation_status="generated",
        generated_cypher="MATCH (f:Fiber) RETURN f LIMIT 5",
        parse_summary="ok",
        guardrail_summary="passed",
        raw_output_snapshot="{}",
        failure_stage=None,
        failure_reason_summary=None,
        input_prompt_snapshot="new prompt",
    )
    query_repository.upsert_question(id="qa-console-manual", question="手动调试", status="generated")

    client = TestClient(create_app())

    response = client.get("/api/v1/tasks")

    assert response.status_code == 200
    payload = response.json()
    assert payload["title_zh"] == "运行结果中心"
    assert [task["id"] for task in payload["tasks"]] == ["qa_new", "qa_old"]
    assert all(task["source"] == "qa_generator" for task in payload["tasks"])
    assert all("qa-console" not in task["id"] for task in payload["tasks"])


def test_runtime_results_task_detail_aggregates_cypher_quality_and_repair_trace(monkeypatch, tmp_path: Path):
    query_dir = tmp_path / "query"
    testing_dir = tmp_path / "testing"
    repair_dir = tmp_path / "repair"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_QUERY_GENERATOR_DATA_DIR", str(query_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(repair_dir))

    from services.cypher_generator_agent.app.repository import QueryGeneratorRepository
    from services.repair_agent.app.repository import RepairRepository
    from console.runtime_console.app.main import create_app
    from services.testing_agent.app.repository import TestingRepository

    query_repository = QueryGeneratorRepository(str(query_dir))
    testing_repository = TestingRepository(str(testing_dir))
    repair_repository = RepairRepository(str(repair_dir))

    query_repository.upsert_question(id="qa_fiber_001", question="查询长度最长的5条光纤", status="generated")
    query_repository.save_generation_run(
        id="qa_fiber_001",
        generation_run_id="run-fiber-001",
        attempt_no=2,
        generation_status="generated",
        generated_cypher="MATCH (f:Fiber) RETURN f.id AS id, f.name AS name, f.length AS length LIMIT 20",
        parse_summary="parsed",
        guardrail_summary="passed",
        raw_output_snapshot='{"cypher":"MATCH (f:Fiber) RETURN f.id AS id, f.name AS name, f.length AS length LIMIT 20"}',
        failure_stage=None,
        failure_reason_summary=None,
        input_prompt_snapshot="Fiber prompt snapshot",
    )
    testing_repository.save_golden(
        QAGoldenRequest(
            id="qa_fiber_001",
            cypher="MATCH (n:Fiber) RETURN n ORDER BY n.length DESC LIMIT 5",
            answer=[],
            difficulty="L4",
        )
    )
    testing_repository.save_submission(
        EvaluationSubmissionRequest(
            id="qa_fiber_001",
            question="查询长度最长的5条光纤",
            generation_run_id="run-fiber-001",
            attempt_no=2,
            generated_cypher="MATCH (f:Fiber) RETURN f.id AS id, f.name AS name, f.length AS length LIMIT 20",
            parse_summary="parsed",
            guardrail_summary="passed",
            raw_output_snapshot='{"cypher":"MATCH (f:Fiber) RETURN f.id AS id, f.name AS name, f.length AS length LIMIT 20"}',
            input_prompt_snapshot="Fiber prompt snapshot",
        ),
        status="issue_ticket_created",
    )
    testing_repository.save_submission(
        EvaluationSubmissionRequest(
            id="qa_fiber_001",
            question="查询长度最长的5条光纤",
            generation_run_id="run-fiber-000",
            attempt_no=1,
            generated_cypher="MATCH (f:Fiber) RETURN f.id AS id LIMIT 20",
            parse_summary="parsed",
            guardrail_summary="passed",
            raw_output_snapshot='{"cypher":"MATCH (f:Fiber) RETURN f.id AS id LIMIT 20"}',
            input_prompt_snapshot="Older prompt snapshot",
        ),
        status="issue_ticket_created",
    )
    testing_repository.save_submission_execution(
        "qa_fiber_001",
        '{"success": false, "rows": [], "row_count": 0, "error_message": "Cypher execution failed", "elapsed_ms": 12}',
        attempt_no=1,
    )
    testing_repository.save_submission_execution(
        "qa_fiber_001",
        '{"success": false, "rows": [], "row_count": 0, "error_message": "Cypher execution failed", "elapsed_ms": 12}',
        attempt_no=2,
    )
    testing_repository.save_issue_ticket(
        IssueTicket(
            ticket_id="ticket-qa_fiber_001",
            id="qa_fiber_001",
            difficulty="L4",
            question="查询长度最长的5条光纤",
            expected=ExpectedAnswer(
                cypher="MATCH (n:Fiber) RETURN n ORDER BY n.length DESC LIMIT 5",
                answer=[],
            ),
            actual=ActualAnswer(
                generated_cypher="MATCH (f:Fiber) RETURN f.id AS id, f.name AS name, f.length AS length LIMIT 20",
                execution={
                    "success": False,
                    "rows": [],
                    "row_count": 0,
                    "error_message": "Cypher execution failed",
                    "elapsed_ms": 12,
                },
            ),
            evaluation=EvaluationSummary(
                verdict="fail",
                dimensions=EvaluationDimensions(
                    syntax_validity="fail",
                    schema_alignment="pass",
                    result_correctness="fail",
                    question_alignment="fail",
                ),
                symptom="The query missed the expected ordering and limit semantics.",
                evidence=["missing ORDER BY", "limit mismatch", "return shape mismatch"],
            ),
            input_prompt_snapshot="Fiber prompt snapshot",
        )
    )
    testing_repository.save_issue_ticket(
        IssueTicket(
            ticket_id="ticket-qa_fiber_001-attempt-1",
            id="qa_fiber_001",
            difficulty="L4",
            question="查询长度最长的5条光纤",
            expected=ExpectedAnswer(
                cypher="MATCH (n:Fiber) RETURN n ORDER BY n.length DESC LIMIT 5",
                answer=[],
            ),
            actual=ActualAnswer(
                generated_cypher="MATCH (f:Fiber) RETURN f.id AS id LIMIT 20",
                execution={
                    "success": False,
                    "rows": [],
                    "row_count": 0,
                    "error_message": "Cypher execution failed",
                    "elapsed_ms": 12,
                },
            ),
            evaluation=EvaluationSummary(
                verdict="fail",
                dimensions=EvaluationDimensions(
                    syntax_validity="fail",
                    schema_alignment="pass",
                    result_correctness="fail",
                    question_alignment="fail",
                ),
                symptom="The query missed the expected ordering and limit semantics.",
                evidence=["missing ORDER BY", "limit mismatch", "return shape mismatch"],
            ),
            input_prompt_snapshot="Older prompt snapshot",
        )
    )
    testing_repository.save_submission_krss_response(
        "qa_fiber_001",
        {
            "status": "applied",
            "analysis_id": "analysis-ticket-qa_fiber_001",
            "id": "qa_fiber_001",
            "knowledge_repair_request": {
                "id": "qa_fiber_001",
                "suggestion": "Add a few-shot example for top-N fiber ranking questions.",
                "knowledge_types": ["few_shot"],
            },
            "knowledge_ops_response": {"status": "ok"},
            "applied": True,
        },
        attempt_no=2,
    )
    testing_repository.save_improvement_assessment(
        "qa_fiber_001",
        ImprovementAssessment(
            qa_id="qa_fiber_001",
            current_attempt_no=2,
            previous_attempt_no=1,
            summary_zh="第 2 轮相较第 1 轮已改善。",
            dimensions=ImprovementDimensions(
                syntax_validity_change="unchanged",
                schema_alignment_change="unchanged",
                result_correctness_change="unchanged",
                question_alignment_change="improved",
            ),
            highlights=["上一轮问题已不再出现: missing ORDER BY"],
            evidence=["limit mismatch"],
        ),
        attempt_no=2,
    )
    repair_repository.save_analysis(
        KRSSAnalysisRecord(
            analysis_id="analysis-ticket-qa_fiber_001",
            ticket_id="ticket-qa_fiber_001",
            id="qa_fiber_001",
            prompt_snapshot="Fiber prompt snapshot",
            knowledge_repair_request=KnowledgeRepairSuggestionRequest(
                id="qa_fiber_001",
                suggestion="Add a few-shot example for top-N fiber ranking questions.",
                knowledge_types=["few_shot"],
            ),
            knowledge_ops_response={"status": "ok"},
            confidence=0.92,
            rationale="The failure points to missing ranking-specific examples.",
            used_experiments=True,
            primary_knowledge_type="few_shot",
            secondary_knowledge_types=["business_knowledge"],
            candidate_patch_types=["few_shot", "business_knowledge"],
            validation_mode="lightweight",
            validation_result={
                "validated_patch_types": ["few_shot"],
                "rejected_patch_types": ["business_knowledge"],
                "validation_reasoning": ["few_shot best explains the top-N ranking mismatch"],
            },
            diagnosis_context_summary={"failure_diff": {"return_shape_problem": True, "limit_problem": True}},
            applied=True,
            created_at="2026-04-14T10:18:10.108360+00:00",
            applied_at="2026-04-14T10:18:10.108387+00:00",
        )
    )

    client = TestClient(create_app())

    response = client.get("/api/v1/tasks/qa_fiber_001")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "qa_fiber_001"
    assert payload["question"] == "查询长度最长的5条光纤"
    assert payload["cypher_quality"]["label"] == "bad"
    assert "ORDER BY" in payload["cypher_quality"]["summary_zh"]
    assert any("LIMIT 5" in finding for finding in payload["cypher_quality"]["findings"])
    assert payload["generated_cypher"].startswith("MATCH (f:Fiber)")
    assert payload["attempt_no"] == 2
    assert payload["stages"]["evaluation"]["status"] == "failed"
    assert payload["stages"]["knowledge_repair"]["status"] == "passed"
    assert payload["improvement_assessment"]["previous_attempt_no"] == 1
    assert payload["improvement_assessment"]["dimensions"]["question_alignment_change"] == "improved"
    assert payload["artifacts"]["repair"]["analysis"]["analysis_id"] == "analysis-ticket-qa_fiber_001"
    assert payload["artifacts"]["repair"]["issue_ticket"]["input_prompt_snapshot"] == "Fiber prompt snapshot"
    assert payload["artifacts"]["repair"]["analysis"]["prompt_snapshot"] == "Fiber prompt snapshot"
    assert payload["artifacts"]["repair"]["analysis"]["prompt_snapshot"] == payload["artifacts"]["repair"]["issue_ticket"]["input_prompt_snapshot"]
    assert payload["artifacts"]["repair"]["analysis"]["primary_knowledge_type"] == "few_shot"
    assert payload["artifacts"]["repair"]["analysis"]["validation_mode"] == "lightweight"
    assert payload["artifacts"]["repair"]["analysis"]["validation_result"]["validated_patch_types"] == ["few_shot"]


def test_runtime_results_prefers_latest_attempt_artifacts_when_question_points_to_newer_attempt(monkeypatch, tmp_path: Path):
    query_dir = tmp_path / "query"
    testing_dir = tmp_path / "testing"
    repair_dir = tmp_path / "repair"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_QUERY_GENERATOR_DATA_DIR", str(query_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(repair_dir))

    from services.cypher_generator_agent.app.repository import QueryGeneratorRepository
    from console.runtime_console.app.main import create_app
    from services.testing_agent.app.repository import TestingRepository

    query_repository = QueryGeneratorRepository(str(query_dir))
    testing_repository = TestingRepository(str(testing_dir))

    query_repository.upsert_question(id="qa_attempt_latest", question="查询光纤", status="generated")
    query_repository.save_generation_run(
        id="qa_attempt_latest",
        generation_run_id="run-001",
        attempt_no=1,
        generation_status="generated",
        generated_cypher="MATCH (f:Fiber) RETURN f LIMIT 20",
        parse_summary="parsed",
        guardrail_summary="accepted",
        raw_output_snapshot="MATCH (f:Fiber) RETURN f LIMIT 20",
        failure_stage=None,
        failure_reason_summary=None,
        input_prompt_snapshot="attempt1",
    )
    query_repository.save_generation_run(
        id="qa_attempt_latest",
        generation_run_id="run-002",
        attempt_no=2,
        generation_status="submitted_to_testing",
        generated_cypher="MATCH (f:Fiber) RETURN f ORDER BY f.length DESC LIMIT 5",
        parse_summary="parsed",
        guardrail_summary="accepted",
        raw_output_snapshot="MATCH (f:Fiber) RETURN f ORDER BY f.length DESC LIMIT 5",
        failure_stage=None,
        failure_reason_summary=None,
        input_prompt_snapshot="attempt2",
    )

    latest_question_path = query_dir / "questions" / "qa_attempt_latest.json"
    latest_question = latest_question_path.read_text(encoding="utf-8")
    latest_question_path.write_text(latest_question.replace('"latest_attempt_no": 2', '"latest_attempt_no": 2'), encoding="utf-8")

    testing_repository.save_submission(
        EvaluationSubmissionRequest(
            id="qa_attempt_latest",
            question="查询光纤",
            generation_run_id="run-001",
            attempt_no=1,
            generated_cypher="MATCH (f:Fiber) RETURN f LIMIT 20",
            parse_summary="parsed",
            guardrail_summary="accepted",
            raw_output_snapshot="MATCH (f:Fiber) RETURN f LIMIT 20",
            input_prompt_snapshot="attempt1",
        ),
        status="issue_ticket_created",
    )
    testing_repository.save_submission(
        EvaluationSubmissionRequest(
            id="qa_attempt_latest",
            question="查询光纤",
            generation_run_id="run-002",
            attempt_no=2,
            generated_cypher="MATCH (f:Fiber) RETURN f ORDER BY f.length DESC LIMIT 5",
            parse_summary="parsed",
            guardrail_summary="accepted",
            raw_output_snapshot="MATCH (f:Fiber) RETURN f ORDER BY f.length DESC LIMIT 5",
            input_prompt_snapshot="attempt2",
        ),
        status="waiting_for_golden",
    )

    client = TestClient(create_app())

    response = client.get("/api/v1/tasks/qa_attempt_latest")

    assert response.status_code == 200
    payload = response.json()
    assert payload["attempt_no"] == 2
    assert payload["generated_cypher"] == "MATCH (f:Fiber) RETURN f ORDER BY f.length DESC LIMIT 5"
    assert payload["artifacts"]["submission"]["attempt_no"] == 2
