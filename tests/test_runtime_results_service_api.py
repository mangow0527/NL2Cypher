from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_runtime_results_center_html_exposes_task_list_and_cypher_quality(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(tmp_path / "testing"))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(tmp_path / "repair"))

    from console.runtime_console.app.main import create_app

    client = TestClient(create_app())

    response = client.get("/console")

    assert response.status_code == 200
    assert "运行结果中心" in response.text
    assert "Runtime Results Center" in response.text
    assert "Cypher 结果与质量" in response.text
    assert "repair-agent 诊断摘要" in response.text
    assert "Testing Service 持久化的 IssueTicket 与 RepairAnalysisRecord" in response.text
    assert "任务列表" in response.text
    assert "服务运行状态" in response.text
    assert "开始联调" not in response.text


def test_runtime_results_service_status_endpoint_returns_five_service_cards(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(tmp_path / "testing"))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(tmp_path / "repair"))

    from console.runtime_console.app.main import create_app
    from console.runtime_console.app.service import RuntimeResultsService

    mock_cards = [
        {"service_key": "cypher-generator-agent", "label_zh": "Cypher 生成服务", "status": "online"},
        {"service_key": "testing-agent", "label_zh": "测试服务", "status": "online"},
        {"service_key": "repair-agent", "label_zh": "知识修复建议服务", "status": "offline"},
        {"service_key": "knowledge-agent", "label_zh": "知识运营服务", "status": "online"},
        {"service_key": "qa-agent", "label_zh": "问答生成服务", "status": "online"},
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
        "cypher-generator-agent",
        "testing-agent",
        "repair-agent",
        "knowledge-agent",
        "qa-agent",
    ]


def test_runtime_results_tasks_only_include_qa_generator_items(monkeypatch, tmp_path: Path):
    testing_dir = tmp_path / "testing"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(tmp_path / "repair"))

    _write_json(
        testing_dir / "submissions" / "qa_old.json",
        {
            "id": "qa_old",
            "attempt_no": 1,
            "question": "旧问题",
            "generation_run_id": "run-old",
            "generated_cypher": "MATCH (n) RETURN n LIMIT 5",
            "input_prompt_snapshot": "old prompt",
            "state": "passed",
            "received_at": "2026-04-26T10:00:00+00:00",
            "updated_at": "2026-04-26T10:01:00+00:00",
        },
    )
    _write_json(
        testing_dir / "submissions" / "qa_new.json",
        {
            "id": "qa_new",
            "attempt_no": 1,
            "question": "新问题",
            "generation_run_id": "run-new",
            "generated_cypher": "MATCH (f:Fiber) RETURN f LIMIT 5",
            "input_prompt_snapshot": "new prompt",
            "state": "passed",
            "received_at": "2026-04-26T11:00:00+00:00",
            "updated_at": "2026-04-26T11:01:00+00:00",
        },
    )
    _write_json(
        testing_dir / "submissions" / "qa-console-manual.json",
        {
            "id": "qa-console-manual",
            "attempt_no": 1,
            "question": "手动调试",
            "generation_run_id": "run-console",
            "generated_cypher": "MATCH (n) RETURN n",
            "input_prompt_snapshot": "console prompt",
            "state": "passed",
            "received_at": "2026-04-26T12:00:00+00:00",
            "updated_at": "2026-04-26T12:01:00+00:00",
        },
    )

    from console.runtime_console.app.main import create_app

    client = TestClient(create_app())

    response = client.get("/api/v1/tasks")

    assert response.status_code == 200
    payload = response.json()
    assert payload["title_zh"] == "运行结果中心"
    assert [task["id"] for task in payload["tasks"]] == ["qa_new", "qa_old"]
    assert all(task["source"] == "qa_generator" for task in payload["tasks"])
    assert all("qa-console" not in task["id"] for task in payload["tasks"])


def test_runtime_results_task_detail_reads_current_testing_and_repair_artifacts(monkeypatch, tmp_path: Path):
    testing_dir = tmp_path / "testing"
    repair_dir = tmp_path / "repair"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(repair_dir))
    _write_json(
        testing_dir / "goldens" / "qa_fiber_001.json",
        {
            "id": "qa_fiber_001",
            "cypher": "MATCH (n:Fiber) RETURN n ORDER BY n.length DESC LIMIT 5",
            "answer": [],
            "difficulty": "L4",
            "updated_at": "2026-04-26T09:01:00+00:00",
        },
    )
    _write_json(
        testing_dir / "submission_attempts" / "qa_fiber_001__attempt_2.json",
        {
            "id": "qa_fiber_001",
            "attempt_no": 2,
            "question": "查询长度最长的5条光纤",
            "generation_run_id": "run-fiber-001",
            "generated_cypher": "MATCH (f:Fiber) RETURN f.id AS id, f.name AS name, f.length AS length LIMIT 20",
            "input_prompt_snapshot": "Fiber prompt snapshot",
            "state": "issue_ticket_created",
            "execution": {
                "success": False,
                "rows": [],
                "row_count": 0,
                "error_message": "Cypher execution failed",
                "elapsed_ms": 12,
            },
            "issue_ticket_id": "ticket-qa_fiber_001-attempt-2",
            "repair_response": {
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
            "improvement_assessment": {
                "qa_id": "qa_fiber_001",
                "current_attempt_no": 2,
                "previous_attempt_no": 1,
                "summary_zh": "第 2 轮相较第 1 轮已改善。",
                "metrics": {
                    "grammar_score": {"previous": 0, "current": 1, "status": "improved"},
                    "execution_accuracy_score": {"previous": 0, "current": 0, "status": "unchanged"},
                    "gleu_score": {"previous": 0.1, "current": 0.4, "status": "improved"},
                    "jaro_winkler_similarity_score": {"previous": 0.2, "current": 0.5, "status": "improved"},
                },
                "highlights": ["上一轮问题已不再出现: missing ORDER BY"],
                "evidence": ["limit mismatch"],
            },
            "received_at": "2026-04-26T09:00:30+00:00",
            "updated_at": "2026-04-26T09:03:00+00:00",
        },
    )
    _write_json(
        testing_dir / "submissions" / "qa_fiber_001.json",
        {
            "id": "qa_fiber_001",
            "attempt_no": 2,
            "question": "查询长度最长的5条光纤",
            "generation_run_id": "run-fiber-001",
            "generated_cypher": "MATCH (f:Fiber) RETURN f.id AS id, f.name AS name, f.length AS length LIMIT 20",
            "input_prompt_snapshot": "Fiber prompt snapshot",
            "state": "issue_ticket_created",
            "execution": {
                "success": False,
                "rows": [],
                "row_count": 0,
                "error_message": "Cypher execution failed",
                "elapsed_ms": 12,
            },
            "issue_ticket_id": "ticket-qa_fiber_001-attempt-2",
            "repair_response": {
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
            "improvement_assessment": {
                "qa_id": "qa_fiber_001",
                "current_attempt_no": 2,
                "previous_attempt_no": 1,
                "summary_zh": "第 2 轮相较第 1 轮已改善。",
                "metrics": {
                    "grammar_score": {"previous": 0, "current": 1, "status": "improved"},
                    "execution_accuracy_score": {"previous": 0, "current": 0, "status": "unchanged"},
                    "gleu_score": {"previous": 0.1, "current": 0.4, "status": "improved"},
                    "jaro_winkler_similarity_score": {"previous": 0.2, "current": 0.5, "status": "improved"},
                },
                "highlights": ["上一轮问题已不再出现: missing ORDER BY"],
                "evidence": ["limit mismatch"],
            },
            "received_at": "2026-04-26T09:00:30+00:00",
            "updated_at": "2026-04-26T09:03:00+00:00",
        },
    )
    _write_json(
        testing_dir / "issue_tickets" / "ticket-qa_fiber_001-attempt-2.json",
        {
            "ticket_id": "ticket-qa_fiber_001-attempt-2",
            "id": "qa_fiber_001",
            "difficulty": "L4",
            "question": "查询长度最长的5条光纤",
            "expected": {
                "cypher": "MATCH (n:Fiber) RETURN n ORDER BY n.length DESC LIMIT 5",
                "answer": [],
            },
            "actual": {
                "generated_cypher": "MATCH (f:Fiber) RETURN f.id AS id, f.name AS name, f.length AS length LIMIT 20",
                "execution": {
                    "success": False,
                    "rows": [],
                    "row_count": 0,
                    "error_message": "Cypher execution failed",
                    "elapsed_ms": 12,
                },
            },
            "evaluation": {
                "verdict": "fail",
                "primary_metrics": {
                    "grammar": {"score": 1, "parser_error": None, "message": None},
                    "execution_accuracy": {
                        "score": 0,
                        "reason": "not_equivalent",
                        "strict_check": {
                            "status": "fail",
                            "message": "结果未严格一致。",
                            "order_sensitive": True,
                            "expected_row_count": 5,
                            "actual_row_count": 20,
                            "evidence": {
                                "golden_answer": [],
                                "actual_answer": [],
                                "diff": {
                                    "missing_rows": [],
                                    "unexpected_rows": [],
                                    "order_mismatch": True,
                                },
                            },
                        },
                        "semantic_check": {
                            "status": "fail",
                            "message": "语义不等价。",
                            "raw_output": {"accepted": False},
                        },
                    },
                },
                "secondary_signals": {
                    "gleu": {"score": 0.22, "tokenizer": "zh", "min_n": 1, "max_n": 4},
                    "jaro_winkler_similarity": {"score": 0.41, "normalization": "cypher_basic", "library": "rapidfuzz"},
                },
            },
            "generation_evidence": {
                "generation_run_id": "run-fiber-001",
                "attempt_no": 2,
                "input_prompt_snapshot": "Fiber prompt snapshot",
            },
        },
    )
    _write_json(
        repair_dir / "analyses" / "analysis-ticket-qa_fiber_001.json",
        {
            "analysis_id": "analysis-ticket-qa_fiber_001",
            "ticket_id": "ticket-qa_fiber_001-attempt-2",
            "id": "qa_fiber_001",
            "status": "applied",
            "prompt_snapshot": "Fiber prompt snapshot",
            "knowledge_repair_request": {
                "id": "qa_fiber_001",
                "suggestion": "Add a few-shot example for top-N fiber ranking questions.",
                "knowledge_types": ["few_shot"],
            },
            "knowledge_ops_response": {"status": "ok"},
            "confidence": 0.91,
            "rationale": "The query missed the ranking few-shot pattern.",
            "used_experiments": True,
            "primary_knowledge_type": "few_shot",
            "secondary_knowledge_types": ["system_prompt"],
            "candidate_patch_types": ["few_shot"],
            "validation_mode": "lightweight",
            "validation_result": {
                "validated_patch_types": ["few_shot"],
            },
            "diagnosis_context_summary": {"failure_diff": {"limit_problem": True}},
            "applied": True,
            "created_at": "2026-04-26T09:03:01+00:00",
            "applied_at": "2026-04-26T09:03:02+00:00",
        },
    )

    from console.runtime_console.app.main import create_app

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
    assert payload["artifacts"]["repair"]["analysis"]["analysis_id"] == "analysis-ticket-qa_fiber_001"
    assert payload["artifacts"]["repair"]["issue_ticket"]["generation_evidence"]["input_prompt_snapshot"] == "Fiber prompt snapshot"
    assert payload["artifacts"]["repair"]["analysis"]["prompt_snapshot"] == "Fiber prompt snapshot"
    assert payload["artifacts"]["repair"]["analysis"]["primary_knowledge_type"] == "few_shot"
    assert payload["artifacts"]["repair"]["analysis"]["validation_mode"] == "lightweight"
    assert payload["artifacts"]["repair"]["analysis"]["validation_result"]["validated_patch_types"] == ["few_shot"]


def test_runtime_results_ignores_malformed_repair_response_artifacts(monkeypatch, tmp_path: Path):
    testing_dir = tmp_path / "testing"
    repair_dir = tmp_path / "repair"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(repair_dir))
    _write_json(
        testing_dir / "submission_attempts" / "qa_bad_repair__attempt_1.json",
        {
            "id": "qa_bad_repair",
            "attempt_no": 1,
            "question": "查询异常修复记录",
            "generation_run_id": "run-bad-repair",
            "generated_cypher": "MATCH (n) RETURN n",
            "input_prompt_snapshot": "prompt snapshot",
            "state": "issue_ticket_created",
            "issue_ticket_id": "ticket-qa_bad_repair-attempt-1",
            "repair_response": {
                "status": "applied",
                "analysis_id": 123,
                "knowledge_ops_response": {"status": "ok"},
            },
            "received_at": "2026-04-26T09:00:30+00:00",
            "updated_at": "2026-04-26T09:03:00+00:00",
        },
    )
    _write_json(
        testing_dir / "submissions" / "qa_bad_repair.json",
        {
            "id": "qa_bad_repair",
            "attempt_no": 1,
            "question": "查询异常修复记录",
            "generation_run_id": "run-bad-repair",
            "generated_cypher": "MATCH (n) RETURN n",
            "input_prompt_snapshot": "prompt snapshot",
            "state": "issue_ticket_created",
            "issue_ticket_id": "ticket-qa_bad_repair-attempt-1",
            "repair_response": {
                "status": "applied",
                "analysis_id": 123,
                "knowledge_ops_response": {"status": "ok"},
            },
            "received_at": "2026-04-26T09:00:30+00:00",
            "updated_at": "2026-04-26T09:03:00+00:00",
        },
    )
    _write_json(
        testing_dir / "issue_tickets" / "ticket-qa_bad_repair-attempt-1.json",
        {
            "ticket_id": "ticket-qa_bad_repair-attempt-1",
            "id": "qa_bad_repair",
            "difficulty": "L3",
            "question": "查询异常修复记录",
            "expected": {"cypher": "MATCH (n) RETURN n", "answer": []},
            "actual": {"generated_cypher": "MATCH (n) RETURN n", "execution": None},
            "evaluation": {
                "verdict": "fail",
                "primary_metrics": {
                    "grammar": {"score": 1, "parser_error": None, "message": None},
                    "execution_accuracy": {
                        "score": 0,
                        "reason": "not_equivalent",
                        "strict_check": {
                            "status": "fail",
                            "message": "结果未严格一致。",
                            "order_sensitive": False,
                            "expected_row_count": 0,
                            "actual_row_count": 0,
                            "evidence": None,
                        },
                        "semantic_check": {"status": "fail", "message": "语义不等价。", "raw_output": None},
                    },
                },
                "secondary_signals": {
                    "gleu": {"score": 0.2, "tokenizer": "zh", "min_n": 1, "max_n": 4},
                    "jaro_winkler_similarity": {"score": 0.4, "normalization": "cypher_basic", "library": "rapidfuzz"},
                },
            },
            "generation_evidence": {
                "generation_run_id": "run-bad-repair",
                "attempt_no": 1,
                "input_prompt_snapshot": "prompt snapshot",
            },
        },
    )

    from console.runtime_console.app.main import create_app

    client = TestClient(create_app())

    response = client.get("/api/v1/tasks/qa_bad_repair")

    assert response.status_code == 200
    payload = response.json()
    assert payload["stages"]["evaluation"]["status"] == "failed"
    assert payload["stages"]["knowledge_repair"]["status"] == "failed"
    assert payload["stages"]["knowledge_apply"]["status"] == "failed"
    assert payload["artifacts"]["repair"]["repair_response"] is None
    assert payload["artifacts"]["repair"]["analysis"] is None


def test_runtime_results_do_not_require_cypher_generator_agent_local_storage(monkeypatch, tmp_path: Path):
    testing_dir = tmp_path / "testing"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(tmp_path / "repair"))

    _write_json(
        testing_dir / "submissions" / "qa_storage_free.json",
        {
            "id": "qa_storage_free",
            "attempt_no": 1,
            "question": "查询设备",
            "generation_run_id": "run-storage-free",
            "generated_cypher": "MATCH (n) RETURN n LIMIT 5",
            "input_prompt_snapshot": "prompt",
            "state": "received_submission_only",
            "received_at": "2026-04-26T08:00:00+00:00",
            "updated_at": "2026-04-26T08:01:00+00:00",
        },
    )

    from console.runtime_console.app.main import create_app

    client = TestClient(create_app())

    tasks_response = client.get("/api/v1/tasks")
    detail_response = client.get("/api/v1/tasks/qa_storage_free")

    assert tasks_response.status_code == 200
    assert [task["id"] for task in tasks_response.json()["tasks"]] == ["qa_storage_free"]
    assert detail_response.status_code == 200
    assert detail_response.json()["question"] == "查询设备"
