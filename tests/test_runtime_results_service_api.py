from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_runtime_results_center_html_exposes_pipeline_sections(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(tmp_path / "testing"))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(tmp_path / "repair"))

    from console.runtime_console.app.main import create_app

    client = TestClient(create_app())

    response = client.get("/console")

    assert response.status_code == 200
    assert "运行结果中心" in response.text
    assert "Runtime Results Center" in response.text
    assert "cypher-generator-agent" in response.text
    assert "testing-agent" in response.text
    assert "repair-agent" in response.text
    assert "Cypher 结果与质量" not in response.text
    assert "改进评估" not in response.text
    assert "repair-agent 诊断摘要" not in response.text
    assert "服务运行状态" in response.text
    assert "难度结论概览" in response.text
    assert "任务明细表" in response.text
    assert "按难度过滤" in response.text
    assert "按 ID 搜索" in response.text
    assert "service-grid" in response.text
    assert "difficulty-grid" in response.text
    assert "task-table-body" in response.text
    assert "pipeline-view" not in response.text
    assert "Agent 落盘信息" not in response.text
    assert "开始联调" not in response.text


def test_runtime_results_task_detail_page_is_separate_from_main_table(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(tmp_path / "testing"))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(tmp_path / "repair"))

    from console.runtime_console.app.main import create_app

    client = TestClient(create_app())

    response = client.get("/console/tasks/qa_contract_001")

    assert response.status_code == 200
    assert "任务详情" in response.text
    assert "Agent 落盘信息" in response.text
    assert "pipeline-view" in response.text
    assert "task-table-body" not in response.text


def test_runtime_results_detail_script_uses_chinese_cypher_generator_comparison_labels():
    script = (Path(__file__).resolve().parents[1] / "console" / "runtime_console" / "ui" / "detail.js").read_text(encoding="utf-8")

    assert "生成对照" in script
    assert "自然语言问题" in script
    assert "标准 Cypher" in script
    assert "生成 Cypher" in script
    assert "意图识别 LLM 原始返回" in script
    assert "Cypher 生成 LLM 原始返回" in script
    assert "生成链路摘要" in script
    assert "发给大模型的完整提示词" not in script
    assert "大模型原始输出" not in script
    assert "parser 后 Cypher" not in script


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


def test_runtime_results_tasks_include_every_persisted_submission(monkeypatch, tmp_path: Path):
    testing_dir = tmp_path / "testing"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(tmp_path / "repair"))
    _write_json(testing_dir / "goldens" / "qa_old.json", {"id": "qa_old", "difficulty": "L1"})
    _write_json(testing_dir / "goldens" / "qa_new.json", {"id": "qa_new", "difficulty": "L2"})
    _write_json(testing_dir / "goldens" / "qa-console-manual.json", {"id": "qa-console-manual", "difficulty": "L3"})

    _write_json(
        testing_dir / "submissions" / "qa_old.json",
        {
            "id": "qa_old",
            "attempt_no": 1,
            "question": "旧问题",
            "generation_run_id": "run-old",
            "generated_cypher": "MATCH (n) RETURN n LIMIT 5",
            "input_prompt_snapshot": "old prompt",
            "generation_status": "generated",
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
            "generation_status": "generated",
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
            "generation_status": "generated",
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
    assert [task["id"] for task in payload["tasks"]] == ["qa-console-manual", "qa_new", "qa_old"]
    assert payload["pagination"] == {
        "page": 1,
        "page_size": 20,
        "total": 3,
        "total_pages": 1,
        "has_previous": False,
        "has_next": False,
    }
    assert all(task["source"] == "testing_agent" for task in payload["tasks"])


def test_runtime_results_tasks_support_server_side_pagination_and_filters(monkeypatch, tmp_path: Path):
    testing_dir = tmp_path / "testing"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(tmp_path / "repair"))

    for index, difficulty in enumerate(["L1", "L2", "L2", "L3", "L2"], start=1):
        qa_id = f"qa_page_{index}"
        _write_json(testing_dir / "goldens" / f"{qa_id}.json", {"id": qa_id, "difficulty": difficulty})
        _write_json(
            testing_dir / "submissions" / f"{qa_id}.json",
            {
                "id": qa_id,
                "question": f"问题 {index}",
                "generated_cypher": "MATCH (n) RETURN n",
                "generation_status": "generated",
                "state": "passed",
                "updated_at": f"2026-04-26T12:0{index}:00+00:00",
            },
        )

    from console.runtime_console.app.main import create_app

    client = TestClient(create_app())

    page_response = client.get("/api/v1/tasks?page=2&page_size=2")
    filtered_response = client.get("/api/v1/tasks?difficulty=L2&q=page_5&page_size=10")

    assert page_response.status_code == 200
    page_payload = page_response.json()
    assert [task["id"] for task in page_payload["tasks"]] == ["qa_page_3", "qa_page_2"]
    assert page_payload["pagination"]["total"] == 5
    assert page_payload["pagination"]["total_pages"] == 3
    assert page_payload["pagination"]["has_previous"] is True
    assert page_payload["pagination"]["has_next"] is True

    assert filtered_response.status_code == 200
    filtered_payload = filtered_response.json()
    assert [task["id"] for task in filtered_payload["tasks"]] == ["qa_page_5"]
    assert filtered_payload["pagination"]["total"] == 1


def test_runtime_results_tasks_exclude_legacy_or_non_contract_records(monkeypatch, tmp_path: Path):
    testing_dir = tmp_path / "testing"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(tmp_path / "repair"))

    _write_json(testing_dir / "goldens" / "qa_valid.json", {"id": "qa_valid", "difficulty": "L1"})
    _write_json(testing_dir / "goldens" / "qa_legacy.json", {"id": "qa_legacy", "difficulty": "L1"})
    _write_json(testing_dir / "goldens" / "qa_submitted.json", {"id": "qa_submitted", "difficulty": "L1"})
    _write_json(
        testing_dir / "submissions" / "qa_valid.json",
        {
            "id": "qa_valid",
            "question": "有效新契约记录",
            "generated_cypher": "MATCH (n) RETURN n",
            "generation_status": "generated",
            "state": "passed",
            "updated_at": "2026-04-26T12:00:00+00:00",
        },
    )
    _write_json(
        testing_dir / "submissions" / "qa_legacy.json",
        {
            "id": "qa_legacy",
            "question": "旧记录缺少 generation_status",
            "generated_cypher": "MATCH (n) RETURN n",
            "state": "passed",
            "updated_at": "2026-04-26T12:01:00+00:00",
        },
    )
    _write_json(
        testing_dir / "submissions" / "qa_submitted.json",
        {
            "id": "qa_submitted",
            "question": "cypher-generator 对 qa-agent 的同步状态",
            "generated_cypher": "MATCH (n) RETURN n",
            "generation_status": "submitted_to_testing",
            "state": "passed",
            "updated_at": "2026-04-26T12:02:00+00:00",
        },
    )

    from console.runtime_console.app.main import create_app

    client = TestClient(create_app())

    tasks_response = client.get("/api/v1/tasks")
    legacy_detail_response = client.get("/api/v1/tasks/qa_legacy")
    submitted_detail_response = client.get("/api/v1/tasks/qa_submitted")

    assert tasks_response.status_code == 200
    assert [task["id"] for task in tasks_response.json()["tasks"]] == ["qa_valid"]
    assert legacy_detail_response.status_code == 404
    assert submitted_detail_response.status_code == 404


def test_runtime_results_task_summary_groups_final_verdict_by_difficulty(monkeypatch, tmp_path: Path):
    testing_dir = tmp_path / "testing"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(tmp_path / "repair"))

    _write_json(testing_dir / "goldens" / "qa_l1_ok.json", {"id": "qa_l1_ok", "difficulty": "L1"})
    _write_json(testing_dir / "goldens" / "qa_l1_fail.json", {"id": "qa_l1_fail", "difficulty": "L1"})
    _write_json(testing_dir / "goldens" / "qa_l2_pending.json", {"id": "qa_l2_pending", "difficulty": "L2"})
    _write_json(testing_dir / "goldens" / "qa_l8_ok.json", {"id": "qa_l8_ok", "difficulty": "L8"})
    _write_json(
        testing_dir / "submissions" / "qa_l1_ok.json",
        {
            "id": "qa_l1_ok",
            "question": "L1 成功问题",
            "generated_cypher": "MATCH (n) RETURN n LIMIT 1",
            "generation_status": "generated",
            "state": "passed",
            "updated_at": "2026-04-26T12:00:00+00:00",
        },
    )
    _write_json(
        testing_dir / "submissions" / "qa_l1_fail.json",
        {
            "id": "qa_l1_fail",
            "question": "L1 失败问题",
            "generation_run_id": "run-1",
            "generated_cypher": "MATCH (n) RETURN n",
            "generation_status": "generated",
            "state": "issue_ticket_created",
            "updated_at": "2026-04-26T12:01:00+00:00",
        },
    )
    _write_json(
        testing_dir / "generation_failures" / "qa_l2_pending__run-2.json",
        {
            "id": "qa_l2_pending",
            "question": "L2 待定问题",
            "generation_run_id": "run-2",
            "generation_status": "service_failed",
            "received_at": "2026-04-26T12:02:00+00:00",
            "updated_at": "2026-04-26T12:02:00+00:00",
        },
    )
    _write_json(
        testing_dir / "submissions" / "qa_l8_ok.json",
        {
            "id": "qa_l8_ok",
            "question": "L8 成功问题",
            "generated_cypher": "MATCH (n) RETURN n LIMIT 1",
            "generation_status": "generated",
            "state": "passed",
            "updated_at": "2026-04-26T12:03:00+00:00",
        },
    )

    from console.runtime_console.app.main import create_app

    client = TestClient(create_app())

    response = client.get("/api/v1/tasks/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["title_zh"] == "难度结论概览"
    assert payload["difficulty_order"] == ["L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8"]
    assert [status["key"] for status in payload["statuses"]] == ["pass", "fail", "pending"]
    buckets = {bucket["difficulty"]: bucket for bucket in payload["buckets"]}
    assert buckets["L1"] == {
        "difficulty": "L1",
        "total": 2,
        "pass": 1,
        "fail": 1,
        "pending": 0,
    }
    assert buckets["L2"]["total"] == 1
    assert buckets["L2"]["pending"] == 1
    assert buckets["L8"]["total"] == 1
    assert buckets["L8"]["pass"] == 1
    assert buckets["L3"]["total"] == 0


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
            "generation_status": "generated",
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
                "knowledge_agent_response": {"status": "ok"},
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
            "generation_status": "generated",
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
                "knowledge_agent_response": {"status": "ok"},
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
            "system_prompt_snapshot": "repair system prompt",
            "user_prompt_snapshot": "repair user prompt with DiagnosisContext",
            "raw_output": "{\"repairable\": true, \"primary_knowledge_type\": \"few_shot\"}",
            "knowledge_repair_request": {
                "id": "qa_fiber_001",
                "suggestion": "Add a few-shot example for top-N fiber ranking questions.",
                "knowledge_types": ["few_shot"],
            },
            "knowledge_agent_response": {"status": "ok"},
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
    assert payload["summary"]["difficulty"] == "L4"
    assert "cypher_quality" not in payload
    assert "artifacts" not in payload
    assert "improvement_assessment" not in payload
    assert payload["attempt_no"] == 2
    assert payload["stages"]["evaluation"]["status"] == "failed"
    assert payload["stages"]["knowledge_repair"]["status"] == "passed"
    generator = payload["pipeline"]["cypher_generator_agent"]
    assert generator["question"] == "查询长度最长的5条光纤"
    assert generator["difficulty"] == "L4"
    assert generator["prompt_markdown"] == "Fiber prompt snapshot"
    assert generator["generated_cypher"].startswith("MATCH (f:Fiber)")
    assert generator["gate_passed"] is True
    testing = payload["pipeline"]["testing_agent"]
    assert testing["golden_cypher"].startswith("MATCH (n:Fiber)")
    assert testing["golden_answer"] == []
    assert testing["actual_cypher"].startswith("MATCH (f:Fiber)")
    assert testing["grammar"]["score"] == 1
    assert testing["execution_accuracy"]["reason"] == "not_equivalent"
    assert testing["strict_check"]["status"] == "fail"
    assert testing["semantic_review"]["status"] == "not_recorded"
    assert testing["secondary_metrics"]["gleu"] == 0.22
    assert testing["secondary_metrics"]["similarity"] == 0.41
    assert testing["improvement"]["previous_attempt_no"] == 1
    repair = payload["pipeline"]["repair_agent"]
    assert repair["issue_ticket_id"] == "ticket-qa_fiber_001-attempt-2"
    assert repair["analysis_id"] == "analysis-ticket-qa_fiber_001"
    assert repair["llm_prompt_markdown"] == "repair system prompt\n\nrepair user prompt with DiagnosisContext"
    assert repair["raw_output"] == "{\"repairable\": true, \"primary_knowledge_type\": \"few_shot\"}"
    assert "generation_prompt_evidence" not in repair
    assert repair["suggestion"] == "Add a few-shot example for top-N fiber ranking questions."
    assert repair["knowledge_types"] == ["few_shot"]
    assert repair["knowledge_agent_request"] == {
        "id": "qa_fiber_001",
        "suggestion": "Add a few-shot example for top-N fiber ranking questions.",
        "knowledge_types": ["few_shot"],
    }
    assert repair["knowledge_agent_response"] == {"status": "ok"}
    assert "knowledge_ops_response" not in repair
    assert "repair_response" not in repair


def test_runtime_results_ignores_malformed_repair_response_artifacts(monkeypatch, tmp_path: Path):
    testing_dir = tmp_path / "testing"
    repair_dir = tmp_path / "repair"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(repair_dir))
    _write_json(testing_dir / "goldens" / "qa_bad_repair.json", {"id": "qa_bad_repair", "difficulty": "L3"})
    _write_json(
        testing_dir / "submission_attempts" / "qa_bad_repair__attempt_1.json",
        {
            "id": "qa_bad_repair",
            "attempt_no": 1,
            "question": "查询异常修复记录",
            "generation_run_id": "run-bad-repair",
            "generated_cypher": "MATCH (n) RETURN n",
            "input_prompt_snapshot": "prompt snapshot",
            "generation_status": "generated",
            "state": "issue_ticket_created",
            "issue_ticket_id": "ticket-qa_bad_repair-attempt-1",
            "repair_response": {
                "status": "applied",
                "analysis_id": 123,
                "knowledge_agent_response": {"status": "ok"},
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
            "generation_status": "generated",
            "state": "issue_ticket_created",
            "issue_ticket_id": "ticket-qa_bad_repair-attempt-1",
            "repair_response": {
                "status": "applied",
                "analysis_id": 123,
                "knowledge_agent_response": {"status": "ok"},
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
    assert payload["pipeline"]["repair_agent"]["analysis_id"] is None


def test_runtime_results_marks_knowledge_agent_fields_as_not_repairable(monkeypatch, tmp_path: Path):
    testing_dir = tmp_path / "testing"
    repair_dir = tmp_path / "repair"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(repair_dir))
    _write_json(testing_dir / "goldens" / "qa_not_repairable.json", {"id": "qa_not_repairable", "difficulty": "L1"})
    _write_json(
        testing_dir / "submissions" / "qa_not_repairable.json",
        {
            "id": "qa_not_repairable",
            "attempt_no": 1,
            "question": "查询所有设备",
            "generation_run_id": "run-not-repairable",
            "generated_cypher": "MATCH (n:Device) RETURN n",
            "input_prompt_snapshot": "generator prompt",
            "generation_status": "generated",
            "state": "issue_ticket_created",
            "issue_ticket_id": "ticket-qa_not_repairable-attempt-1",
            "repair_response": {
                "status": "not_repairable",
                "analysis_id": "analysis-ticket-qa_not_repairable-attempt-1",
                "knowledge_repair_request": None,
                "knowledge_agent_response": None,
                "applied": False,
            },
            "received_at": "2026-04-26T09:00:30+00:00",
            "updated_at": "2026-04-26T09:03:00+00:00",
        },
    )
    _write_json(
        testing_dir / "issue_tickets" / "ticket-qa_not_repairable-attempt-1.json",
        {
            "ticket_id": "ticket-qa_not_repairable-attempt-1",
            "id": "qa_not_repairable",
            "difficulty": "L1",
            "question": "查询所有设备",
            "expected": {"cypher": "MATCH (n:Device) RETURN n", "answer": []},
            "actual": {"generated_cypher": "MATCH (n:Device) RETURN n", "execution": None},
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
                            "actual_row_count": 10,
                            "evidence": None,
                        },
                        "semantic_check": {"status": "fail", "message": "语义不等价。", "raw_output": None},
                    },
                },
                "secondary_signals": {},
            },
            "generation_evidence": {
                "generation_run_id": "run-not-repairable",
                "attempt_no": 1,
                "input_prompt_snapshot": "generator prompt",
            },
        },
    )
    _write_json(
        repair_dir / "analyses" / "analysis-ticket-qa_not_repairable-attempt-1.json",
        {
            "analysis_id": "analysis-ticket-qa_not_repairable-attempt-1",
            "ticket_id": "ticket-qa_not_repairable-attempt-1",
            "id": "qa_not_repairable",
            "status": "not_repairable",
            "prompt_snapshot": "repair prompt",
            "system_prompt_snapshot": "repair system",
            "user_prompt_snapshot": "repair user",
            "raw_output": "{\"repairable\": false}",
            "knowledge_repair_request": None,
            "knowledge_agent_response": None,
            "confidence": 0.85,
            "rationale": "当前失败来自 golden answer 与数据库数据不一致。",
            "primary_knowledge_type": None,
            "secondary_knowledge_types": [],
            "diagnosis_context_summary": {},
            "non_repairable_reason": "当前失败来自 golden answer 与数据库数据不一致。",
            "applied": False,
            "created_at": "2026-04-26T09:04:00+00:00",
            "applied_at": "2026-04-26T09:04:00+00:00",
        },
    )

    from console.runtime_console.app.main import create_app

    client = TestClient(create_app())

    response = client.get("/api/v1/tasks/qa_not_repairable")

    assert response.status_code == 200
    repair = response.json()["pipeline"]["repair_agent"]
    assert repair["status"] == "not_repairable"
    assert repair["non_repairable_reason"] == "当前失败来自 golden answer 与数据库数据不一致。"
    assert repair["knowledge_agent_request"] == {
        "status": "not_sent",
        "reason": "not_repairable",
        "message": "不修复：当前失败来自 golden answer 与数据库数据不一致。",
    }
    assert repair["knowledge_agent_response"] == {
        "status": "not_sent",
        "reason": "not_repairable",
        "message": "不修复：repair-agent 判定该问题不是 knowledge-agent 知识缺口，因此没有发送请求。",
    }


def test_runtime_results_separates_repair_review_and_cancelled_redispatch(monkeypatch, tmp_path: Path):
    testing_dir = tmp_path / "testing"
    repair_dir = tmp_path / "repair"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(repair_dir))
    _write_json(testing_dir / "goldens" / "qa_review_waiting.json", {"id": "qa_review_waiting", "difficulty": "L5"})
    _write_json(
        testing_dir / "submissions" / "qa_review_waiting.json",
        {
            "id": "qa_review_waiting",
            "attempt_no": 3,
            "question": "查询所有服务使用的隧道及其目的网元",
            "generation_run_id": "run-review-waiting",
            "generated_cypher": "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel) RETURN t",
            "input_prompt_snapshot": "generator prompt",
            "generation_status": "generated",
            "state": "issue_ticket_created",
            "issue_ticket_id": "ticket-qa_review_waiting-attempt-3",
            "repair_response": {
                "status": "applied",
                "analysis_id": "analysis-ticket-qa_review_waiting-attempt-3",
                "knowledge_repair_request": {
                    "id": "qa_review_waiting",
                    "suggestion": "补充 TUNNEL_DST 业务知识。",
                    "knowledge_types": ["business_knowledge"],
                },
                "knowledge_agent_response": {
                    "status": "ok",
                    "redispatch": {
                        "trace_id": "qa_review_waiting",
                        "qa_id": "qa_review_waiting",
                        "status": "skipped",
                        "dispatch": {
                            "status": "skipped",
                            "reason": "knowledge_agent_no_longer_redispatches_qa",
                        },
                    },
                },
                "applied": True,
            },
            "received_at": "2026-04-26T09:00:30+00:00",
            "updated_at": "2026-04-26T09:03:00+00:00",
        },
    )
    _write_json(
        testing_dir / "issue_tickets" / "ticket-qa_review_waiting-attempt-3.json",
        {
            "ticket_id": "ticket-qa_review_waiting-attempt-3",
            "id": "qa_review_waiting",
            "difficulty": "L5",
            "question": "查询所有服务使用的隧道及其目的网元",
            "expected": {"cypher": "MATCH (s:Service) RETURN s", "answer": []},
            "actual": {"generated_cypher": "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel) RETURN t", "execution": None},
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
                            "actual_row_count": 20,
                            "evidence": None,
                        },
                        "semantic_check": {"status": "fail", "message": "语义不等价。", "raw_output": None},
                    },
                },
                "secondary_signals": {},
            },
            "generation_evidence": {
                "generation_run_id": "run-review-waiting",
                "attempt_no": 3,
                "input_prompt_snapshot": "generator prompt",
            },
        },
    )
    _write_json(
        repair_dir / "analyses" / "analysis-ticket-qa_review_waiting-attempt-3.json",
        {
            "analysis_id": "analysis-ticket-qa_review_waiting-attempt-3",
            "ticket_id": "ticket-qa_review_waiting-attempt-3",
            "id": "qa_review_waiting",
            "status": "applied",
            "prompt_snapshot": "repair prompt",
            "system_prompt_snapshot": "repair system",
            "user_prompt_snapshot": "repair user",
            "raw_output": "{\"repairable\": true}",
            "knowledge_repair_request": {
                "id": "qa_review_waiting",
                "suggestion": "补充 TUNNEL_DST 业务知识。",
                "knowledge_types": ["business_knowledge"],
            },
            "knowledge_agent_response": {
                "status": "ok",
                "redispatch": {
                    "trace_id": "qa_review_waiting",
                    "qa_id": "qa_review_waiting",
                    "status": "skipped",
                    "attempt": 0,
                    "max_attempts": 0,
                    "dispatch": {
                        "status": "skipped",
                        "reason": "knowledge_agent_no_longer_redispatches_qa",
                    },
                },
                "agent_run": {
                    "run_id": "run-knowledge-agent",
                    "qa_id": "qa_review_waiting",
                    "status": "completed",
                    "validation": {
                        "prompt_package_built": True,
                        "before_after_improved": True,
                        "remaining_risks": ["Legacy apply path is gated by human approval before knowledge persistence."],
                    },
                    "decision": {
                        "action": "human_review",
                        "reason": "Converted legacy repair apply request into an agent review run.",
                    },
                },
            },
            "confidence": 0.9,
            "rationale": "缺少 TUNNEL_DST 知识。",
            "primary_knowledge_type": "business_knowledge",
            "secondary_knowledge_types": [],
            "diagnosis_context_summary": {},
            "applied": True,
            "created_at": "2026-04-26T09:04:00+00:00",
            "applied_at": "2026-04-26T09:04:01+00:00",
        },
    )

    from console.runtime_console.app.main import create_app

    client = TestClient(create_app())

    response = client.get("/api/v1/tasks/qa_review_waiting")

    assert response.status_code == 200
    payload = response.json()
    repair = payload["pipeline"]["repair_agent"]
    assert repair["status"] == "applied"
    assert repair["repair_state"]["value"] == "waiting_human_review"
    assert repair["repair_state"]["label_zh"] == "等待人工审核"
    assert repair["knowledge_apply_state"]["value"] == "waiting_human_review"
    assert repair["knowledge_apply_state"]["label_zh"] == "等待人工审核后落库"
    assert repair["redispatch_state"]["value"] == "cancelled"
    assert repair["redispatch_state"]["label_zh"] == "QA 自动重派发已取消"
    assert repair["redispatch_state"]["reason"] == "knowledge_agent_no_longer_redispatches_qa"
    assert payload["stages"]["knowledge_repair"]["status"] == "passed"
    assert payload["stages"]["knowledge_apply"]["status"] == "running"


def test_runtime_results_do_not_require_cypher_generator_agent_local_storage(monkeypatch, tmp_path: Path):
    testing_dir = tmp_path / "testing"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(tmp_path / "repair"))
    _write_json(testing_dir / "goldens" / "qa_storage_free.json", {"id": "qa_storage_free", "difficulty": "L1"})

    _write_json(
        testing_dir / "submissions" / "qa_storage_free.json",
        {
            "id": "qa_storage_free",
            "attempt_no": 1,
            "question": "查询设备",
            "generation_run_id": "run-storage-free",
            "generated_cypher": "MATCH (n) RETURN n LIMIT 5",
            "input_prompt_snapshot": "prompt",
            "generation_status": "generated",
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


def test_runtime_results_task_detail_reads_generation_failure_reports(monkeypatch, tmp_path: Path):
    testing_dir = tmp_path / "testing"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(tmp_path / "repair"))
    _write_json(
        testing_dir / "goldens" / "qa_generation_failed.json",
        {
            "id": "qa_generation_failed",
            "cypher": "MATCH (p:Protocol) RETURN p.version",
            "answer": [{"p.version": "SRv6"}],
            "difficulty": "L2",
            "updated_at": "2026-04-26T09:01:00+00:00",
        },
    )
    _write_json(
        testing_dir / "submissions" / "qa_generation_failed.json",
        {
            "id": "qa_generation_failed",
            "attempt_no": 1,
            "question": "查询协议版本",
            "generation_run_id": "run-generation-failed",
            "generated_cypher": "MATCH (p:Protocol RETURN p.version",
            "input_prompt_snapshot": "prompt before failure",
            "generation_status": "generation_failed",
            "failure_reason": "unbalanced_brackets",
            "state": "issue_ticket_created",
            "evaluation": {
                "verdict": "fail",
                "primary_metrics": {
                    "grammar": {"score": 0, "parser_error": "unbalanced brackets", "message": "语法未通过"},
                    "execution_accuracy": {
                        "score": 0,
                        "reason": "grammar_failed",
                        "strict_check": {
                            "status": "not_run",
                            "message": "Grammar failed.",
                            "order_sensitive": False,
                            "expected_row_count": 0,
                            "actual_row_count": 0,
                            "evidence": None,
                        },
                        "semantic_check": {"status": "not_run", "message": None, "raw_output": None},
                    },
                },
                "secondary_signals": {
                    "gleu": {"score": 0.31, "tokenizer": "zh", "min_n": 1, "max_n": 4},
                    "jaro_winkler_similarity": {"score": 0.72, "normalization": "cypher_basic", "library": "rapidfuzz"},
                },
            },
            "received_at": "2026-04-26T09:00:30+00:00",
            "updated_at": "2026-04-26T09:03:00+00:00",
        },
    )
    _write_json(
        testing_dir / "generation_failures" / "qa_generation_failed__run-generation-failed.json",
        {
            "id": "qa_generation_failed",
            "question": "查询协议版本",
            "generation_run_id": "run-generation-failed",
            "input_prompt_snapshot": "prompt before failure",
            "generation_status": "generation_failed",
            "failure_reason": "unbalanced_brackets",
            "parsed_cypher": "MATCH (p:Protocol RETURN p.version",
            "gate_passed": False,
            "received_at": "2026-04-26T09:00:31+00:00",
        },
    )

    from console.runtime_console.app.main import create_app

    client = TestClient(create_app())

    response = client.get("/api/v1/tasks/qa_generation_failed")

    assert response.status_code == 200
    payload = response.json()
    generator = payload["pipeline"]["cypher_generator_agent"]
    assert generator["generation_status"] == "generation_failed"
    assert generator["gate_passed"] is False
    assert generator["failure_reason"] == "unbalanced_brackets"
    assert payload["stages"]["query_generation"]["status"] == "failed"
    assert payload["pipeline"]["testing_agent"]["grammar"]["score"] == 0


def test_runtime_results_generator_section_prioritizes_cypher_comparison_and_chinese_chain_summary(monkeypatch, tmp_path: Path):
    testing_dir = tmp_path / "testing"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(tmp_path / "repair"))
    semantic_snapshot = {
        "generation_mode": "deterministic_renderer",
        "intent": {
            "primary_intent": "record_retrieval_query",
            "secondary_intent": "attribute_query",
            "source": "rule",
            "decision": "accept",
            "confidence": 0.91,
        },
        "validation": {"accepted": True, "diagnostics": []},
        "selected_knowledge": {
            "source": "rag",
            "selection_trace": ["selected schema fragment", "selected few-shot fragment"],
        },
        "preflight": {"accepted": False, "reason": "logical_plan_mismatch"},
    }
    _write_json(
        testing_dir / "goldens" / "qa_semantic_detail.json",
        {
            "id": "qa_semantic_detail",
            "difficulty": "L5",
            "cypher": "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel) RETURN t.name",
            "answer": [],
        },
    )
    _write_json(
        testing_dir / "submissions" / "qa_semantic_detail.json",
        {
            "id": "qa_semantic_detail",
            "attempt_no": 1,
            "question": "查询所有服务使用的隧道名称。",
            "generation_run_id": "run-semantic-detail",
            "generated_cypher": "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel) RETURN t.id",
            "input_prompt_snapshot": json.dumps(semantic_snapshot, ensure_ascii=False),
            "generation_status": "generated",
            "state": "issue_ticket_created",
            "evaluation": {"verdict": "fail"},
            "updated_at": "2026-05-08T02:52:00+00:00",
        },
    )

    from console.runtime_console.app.main import create_app

    client = TestClient(create_app())

    response = client.get("/api/v1/tasks/qa_semantic_detail")

    assert response.status_code == 200
    generator = response.json()["pipeline"]["cypher_generator_agent"]
    assert generator["question"] == "查询所有服务使用的隧道名称。"
    assert generator["golden_cypher"].startswith("MATCH (s:Service)")
    assert generator["generated_cypher"].endswith("RETURN t.id")
    assert generator["chain_summary"]["generation_mode"]["label_zh"] == "确定性渲染器"
    assert generator["chain_summary"]["generation_status"]["label_zh"] == "生成成功"
    assert generator["chain_summary"]["intent"]["decision_label_zh"] == "已接受"
    assert generator["chain_summary"]["preflight"]["label_zh"] == "预检未通过"
    assert generator["chain_summary"]["preflight"]["reason_label_zh"] == "生成结果与逻辑查询计划不一致"
    assert generator["chain_summary"]["knowledge"]["source_label_zh"] == "RAG 知识选择"


def test_runtime_results_generator_section_exposes_cga_llm_prompts(monkeypatch, tmp_path: Path):
    testing_dir = tmp_path / "testing"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(tmp_path / "repair"))
    semantic_snapshot = {
        "generation_mode": "controlled_llm_fallback",
        "llm_prompts": {
            "intent_recognition_fallback": "【任务说明】\n第三阶段 LLM 意图识别 prompt",
            "cypher_generation_fallback": "【任务说明】\nRenderer 失败后的 Cypher 兜底 prompt",
        },
        "llm_responses": {
            "intent_recognition_fallback": "{\"decision\":\"accept\"}",
            "cypher_generation_fallback": "MATCH (s:Service) RETURN s.name",
        },
    }
    _write_json(
        testing_dir / "goldens" / "qa_llm_prompts.json",
        {"id": "qa_llm_prompts", "difficulty": "L3", "cypher": "MATCH (s:Service) RETURN s.name"},
    )
    _write_json(
        testing_dir / "submissions" / "qa_llm_prompts.json",
        {
            "id": "qa_llm_prompts",
            "attempt_no": 1,
            "question": "查询所有服务",
            "generation_run_id": "run-llm-prompts",
            "generated_cypher": "MATCH (s:Service) RETURN s.name",
            "input_prompt_snapshot": json.dumps(semantic_snapshot, ensure_ascii=False),
            "generation_status": "generated",
            "state": "evaluated",
        },
    )

    from console.runtime_console.app.main import create_app

    client = TestClient(create_app())
    response = client.get("/api/v1/tasks/qa_llm_prompts")

    assert response.status_code == 200
    prompts = response.json()["pipeline"]["cypher_generator_agent"]["llm_prompts"]
    assert prompts["intent_recognition_fallback"]["title_zh"] == "意图识别 LLM 兜底提示词"
    assert prompts["intent_recognition_fallback"]["triggered"] is True
    assert prompts["intent_recognition_fallback"]["prompt"].endswith("第三阶段 LLM 意图识别 prompt")
    assert prompts["intent_recognition_fallback"]["raw_output"] == "{\"decision\":\"accept\"}"
    assert prompts["intent_recognition_fallback"]["raw_output_title_zh"] == "意图识别 LLM 原始返回"
    assert "intent_fallback_cypher_generation" not in prompts
    assert prompts["cypher_generation_fallback"]["triggered"] is True
    assert prompts["cypher_generation_fallback"]["prompt"].endswith("Renderer 失败后的 Cypher 兜底 prompt")
    assert prompts["cypher_generation_fallback"]["raw_output"] == "MATCH (s:Service) RETURN s.name"
    assert prompts["cypher_generation_fallback"]["raw_output_title_zh"] == "Cypher 生成 LLM 原始返回"


def test_runtime_results_prefers_latest_generated_submission_over_stale_generation_failure(monkeypatch, tmp_path: Path):
    testing_dir = tmp_path / "testing"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(tmp_path / "repair"))
    _write_json(testing_dir / "goldens" / "qa_retry.json", {"id": "qa_retry", "difficulty": "L3"})
    _write_json(
        testing_dir / "generation_failures" / "qa_retry__old-run.json",
        {
            "id": "qa_retry",
            "question": "旧失败",
            "generation_run_id": "old-run",
            "generation_status": "service_failed",
            "failure_reason": "knowledge_context_unavailable",
            "input_prompt_snapshot": "",
            "parsed_cypher": "MATCH (old) RETURN old",
            "received_at": "2026-04-26T09:00:00+00:00",
        },
    )
    _write_json(
        testing_dir / "submission_attempts" / "qa_retry__attempt_1.json",
        {
            "id": "qa_retry",
            "attempt_no": 1,
            "question": "旧失败",
            "generation_run_id": "old-run",
            "generated_cypher": "MATCH (old) RETURN old",
            "generation_status": "generated",
            "state": "issue_ticket_created",
            "evaluation": {"verdict": "fail"},
            "updated_at": "2026-04-26T09:01:00+00:00",
        },
    )
    _write_json(
        testing_dir / "submissions" / "qa_retry.json",
        {
            "id": "qa_retry",
            "attempt_no": 2,
            "question": "最新生成",
            "generation_run_id": "new-run",
            "generated_cypher": "MATCH (fresh) RETURN fresh",
            "input_prompt_snapshot": "fresh prompt",
            "generation_status": "generated",
            "state": "issue_ticket_created",
            "evaluation": {"verdict": "fail"},
            "updated_at": "2026-04-26T09:02:00+00:00",
        },
    )
    _write_json(
        testing_dir / "submission_attempts" / "qa_retry__attempt_2.json",
        {
            "id": "qa_retry",
            "attempt_no": 2,
            "question": "最新生成",
            "generation_run_id": "new-run",
            "generated_cypher": "MATCH (fresh) RETURN fresh",
            "input_prompt_snapshot": "fresh prompt",
            "generation_status": "generated",
            "state": "issue_ticket_created",
            "evaluation": {"verdict": "fail"},
            "updated_at": "2026-04-26T09:02:00+00:00",
        },
    )

    from console.runtime_console.app.main import create_app

    client = TestClient(create_app())

    payload = client.get("/api/v1/tasks/qa_retry").json()

    generator = payload["pipeline"]["cypher_generator_agent"]
    assert generator["generation_status"] == "generated"
    assert generator["generation_run_id"] == "new-run"
    assert generator["prompt_markdown"] == "fresh prompt"
    assert generator["generated_cypher"] == "MATCH (fresh) RETURN fresh"
    assert generator["failure_reason"] is None
    assert payload["pipeline"]["testing_agent"]["improvement"] is None


def test_runtime_results_does_not_bind_repair_analysis_without_submission_analysis_id(monkeypatch, tmp_path: Path):
    testing_dir = tmp_path / "testing"
    repair_dir = tmp_path / "repair"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(repair_dir))
    _write_json(testing_dir / "goldens" / "qa_repair_unlinked.json", {"id": "qa_repair_unlinked", "difficulty": "L4"})
    _write_json(
        testing_dir / "submissions" / "qa_repair_unlinked.json",
        {
            "id": "qa_repair_unlinked",
            "attempt_no": 2,
            "question": "查询未绑定修复分析",
            "generation_run_id": "run-unlinked",
            "generated_cypher": "MATCH (n) RETURN n",
            "input_prompt_snapshot": "generator prompt",
            "generation_status": "generated",
            "state": "issue_ticket_created",
            "issue_ticket_id": "ticket-qa_repair_unlinked-attempt-2",
            "updated_at": "2026-04-26T09:03:00+00:00",
        },
    )
    _write_json(
        repair_dir / "analyses" / "analysis-old-ticket.json",
        {
            "analysis_id": "analysis-old-ticket",
            "ticket_id": "ticket-old-attempt-1",
            "id": "qa_repair_unlinked",
            "status": "applied",
            "prompt_snapshot": "old generator prompt",
            "system_prompt_snapshot": "old repair system",
            "user_prompt_snapshot": "old repair user",
            "raw_output": "{\"repairable\": true}",
            "knowledge_repair_request": {
                "id": "qa_repair_unlinked",
                "suggestion": "old suggestion",
                "knowledge_types": ["few_shot"],
            },
            "knowledge_agent_response": {"status": "ok"},
            "confidence": 0.7,
            "rationale": "old rationale",
            "primary_knowledge_type": "few_shot",
            "secondary_knowledge_types": [],
            "diagnosis_context_summary": {},
            "applied": True,
            "created_at": "2026-04-26T09:00:00+00:00",
            "applied_at": "2026-04-26T09:00:01+00:00",
        },
    )

    from console.runtime_console.app.main import create_app

    client = TestClient(create_app())

    response = client.get("/api/v1/tasks/qa_repair_unlinked")

    assert response.status_code == 200
    repair = response.json()["pipeline"]["repair_agent"]
    assert repair["analysis_id"] is None
    assert repair["llm_prompt_markdown"] == ""
    assert repair["raw_output"] is None
    assert repair["knowledge_agent_request"] is None
    assert repair["knowledge_agent_response"] is None


def test_runtime_results_does_not_fallback_to_other_generation_failure_run(monkeypatch, tmp_path: Path):
    testing_dir = tmp_path / "testing"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(tmp_path / "repair"))
    _write_json(testing_dir / "goldens" / "qa_generation_exact.json", {"id": "qa_generation_exact", "difficulty": "L2"})
    _write_json(
        testing_dir / "submissions" / "qa_generation_exact.json",
        {
            "id": "qa_generation_exact",
            "attempt_no": 1,
            "question": "查询协议",
            "generation_run_id": "missing-run",
            "generated_cypher": "MATCH (p:Protocol RETURN p.version",
            "input_prompt_snapshot": "submission prompt",
            "generation_status": "generation_failed",
            "failure_reason": "unbalanced_brackets",
            "state": "issue_ticket_created",
            "updated_at": "2026-04-26T09:03:00+00:00",
        },
    )
    _write_json(
        testing_dir / "generation_failures" / "qa_generation_exact__other-run.json",
        {
            "id": "qa_generation_exact",
            "question": "另一个生成失败",
            "generation_run_id": "other-run",
            "generation_status": "generation_failed",
            "failure_reason": "empty_output",
            "input_prompt_snapshot": "other prompt",
            "parsed_cypher": "MATCH (other) RETURN other",
            "gate_passed": False,
            "received_at": "2026-04-26T09:00:00+00:00",
        },
    )

    from console.runtime_console.app.main import create_app

    client = TestClient(create_app())

    response = client.get("/api/v1/tasks/qa_generation_exact")

    assert response.status_code == 200
    generator = response.json()["pipeline"]["cypher_generator_agent"]
    assert generator["generation_run_id"] == "missing-run"
    assert generator["prompt_markdown"] == "submission prompt"
    assert generator["parsed_cypher"] == "MATCH (p:Protocol RETURN p.version"
    assert generator["failure_reason"] == "unbalanced_brackets"


def test_runtime_results_does_not_synthesize_improvement_when_not_persisted(monkeypatch, tmp_path: Path):
    testing_dir = tmp_path / "testing"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(tmp_path / "repair"))
    _write_json(testing_dir / "goldens" / "qa_no_improvement.json", {"id": "qa_no_improvement", "difficulty": "L3"})
    for attempt_no in (1, 2):
        _write_json(
            testing_dir / "submission_attempts" / f"qa_no_improvement__attempt_{attempt_no}.json",
            {
                "id": "qa_no_improvement",
                "attempt_no": attempt_no,
                "question": "查询无 improvement 的尝试",
                "generation_run_id": f"run-{attempt_no}",
                "generated_cypher": "MATCH (n) RETURN n",
                "generation_status": "generated",
                "state": "issue_ticket_created",
                "evaluation": {"verdict": "fail"},
                "updated_at": f"2026-04-26T09:0{attempt_no}:00+00:00",
            },
        )
    _write_json(
        testing_dir / "submissions" / "qa_no_improvement.json",
        {
            "id": "qa_no_improvement",
            "attempt_no": 2,
            "question": "查询无 improvement 的尝试",
            "generation_run_id": "run-2",
            "generated_cypher": "MATCH (n) RETURN n",
            "generation_status": "generated",
            "state": "issue_ticket_created",
            "evaluation": {"verdict": "fail"},
            "updated_at": "2026-04-26T09:02:00+00:00",
        },
    )

    from console.runtime_console.app.main import create_app

    client = TestClient(create_app())

    response = client.get("/api/v1/tasks/qa_no_improvement")

    assert response.status_code == 200
    assert response.json()["pipeline"]["testing_agent"]["improvement"] is None
