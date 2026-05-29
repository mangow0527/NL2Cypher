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


def test_runtime_results_detail_script_puts_cypher_comparison_in_overview():
    script = (Path(__file__).resolve().parents[1] / "console" / "runtime_console" / "ui" / "detail.js").read_text(encoding="utf-8")

    assert "cypherOverviewCard" in script
    assert "cypher-overview-card" in script
    assert "自然语言问题" in script
    assert "标准 Cypher" in script
    assert "生成 Cypher" in script
    assert "生成对照" not in script
    assert "CGA 全流程" in script
    assert "GraphTrace v1 阶段明细" in script
    assert "LLM 调用明细" in script
    assert "发给 LLM 的提示词" in script
    assert "LLM 原始返回" in script
    assert "DSL / Cypher / 自校验" in script
    assert "renderCgaFlowStages" in script
    assert "renderCgaLlmCalls" in script
    assert "renderCgaArtifacts" in script
    assert "renderTraceTable" in script
    assert "trace-table" in script
    assert "阶段指标" in script
    assert "formatStageMetrics" in script
    assert "无阶段指标" in script
    assert "字段说明" in script
    assert "renderStageSectionHelp" in script
    assert "stageFieldHints" in script
    assert "model_path" in script
    assert "语义模型 YAML 文件路径" in script
    assert "model_checksum" in script
    assert "模型内容校验值" in script
    assert "vertices" in script
    assert "点类型数量" in script
    assert "schema_version" in script
    assert "问题拆解结果的结构版本" in script
    assert "original_question" in script
    assert "进入问题拆解阶段的原始用户问题" in script
    assert "output_shape" in script
    assert "回答结果的形态" in script
    assert "llm_calls" in script
    assert "问题拆解阶段的 LLM 调用明细" not in script
    assert "stripLlmCallsFromPayload" in script
    assert "renderStageLlmCalls" in script
    assert "本阶段 LLM 调用" in script
    assert "阶段输入" in script
    assert "const stageOutput = stripLlmCallsFromPayload(stage.output)" in script
    assert "const stageInput = stripLlmCallsFromPayload(stage.input)" in script
    assert "codeBlock(stageInput)" in script
    assert "codeBlock(stageOutput)" in script
    assert "codeBlock(stage.output)" not in script
    assert "filter_phrases" not in script
    assert "从问题中抽取出的过滤条件短语" not in script
    assert "result_type" in script
    assert "拆解结果类型" in script
    assert "literal_candidate_objects" in script
    assert "保留 literal_candidates 的结构化对象列表" in script
    assert "literal_requests" in script
    assert "由工程代码生成的字面值解析请求" in script
    assert "skipped_literal_candidates" in script
    assert "按 slot 判定后未送入 literal resolver 的候选词" in script
    assert "skipped_literal_candidate_count" in script
    assert "因结构槽位被跳过的 literal candidate 数量" in script
    assert "coverage" in script
    assert "覆盖率报告，记录 substantive_terms 中哪些词已覆盖、哪些仍缺失" in script
    assert "projection_terms" in script
    assert "slot_terms" not in script
    assert "projection_coverage_missing" in script
    assert "返回字段覆盖缺失" in script
    assert "relation_phrases" in script
    assert "表示两个业务对象如何连接的关系短语" in script
    assert "例如“服务使用隧道”中的“使用”" in script
    assert "substantive_terms" in script
    assert "实义词对象数组，每项包含 text、slot 和可选 attached_to" in script
    assert "stopword_terms" in script
    assert "覆盖分类轴字段：礼貌语、连接词、助词或查询引导词" in script
    assert "modality_terms" in script
    assert "表达近似、不确定或软约束的词" in script
    assert "time_terms" in script
    assert "时间或时间范围表达" in script
    assert "unparsed_terms" in script
    assert "无法可靠分类但可能影响语义的残留词" in script
    assert "其他字段" not in script
    assert "保留原始 trace 字段名" not in script
    assert "关键指标" not in script
    assert "metrics_summary: inlineValue(stage.metrics)" not in script
    assert "renderOntologyLayerPrompts" not in script
    assert "renderLegacyCgaChainSummary" not in script
    assert "isOntologyCgaSection" not in script
    assert "ontology_path_selection', '3.3 本体路径选择 LLM 输入提示词" not in script
    assert "一层意图 LLM 原始输出" not in script
    assert "二层意图 LLM 原始输出" not in script
    assert "意图识别与答案形态：二层意图 LLM 原始输出" not in script
    assert "white-space: pre-line" in script or "white-space: pre-line" in (
        Path(__file__).resolve().parents[1] / "console" / "runtime_console" / "ui" / "styles.css"
    ).read_text(encoding="utf-8")
    assert "生成链路摘要" not in script
    assert "澄清反问" in script
    assert "澄清选项" in script
    assert "未解析项" in script
    assert "校验错误" in script
    assert "metricCard('当前阶段'" in script
    assert "metricCard('阶段数'" not in script
    assert "系统决策" in script
    assert "触发原因" in script
    assert "触发阶段" in script
    assert "回答方式" in script
    assert "metricCard('原因代码'" not in script
    assert "metricCard('来源层级'" not in script
    assert "metricCard('回答类型'" not in script
    assert "no_option_reason" in script
    assert "发给大模型的完整提示词" not in script
    assert "大模型原始输出" not in script
    assert "parser 后 Cypher" not in script
    assert "cypher_template" in script
    assert "编译器内部生成的参数化 Cypher 模板" in script
    assert "cypher_executable" in script
    assert "参数内联后的可执行 Cypher" in script
    assert "parameter_sources" in script
    assert "每个模板参数的来源元信息" in script
    assert "不是 v1 的执行契约" in script


def test_runtime_results_generated_cypher_overview_card_has_no_status_pill():
    script = (Path(__file__).resolve().parents[1] / "console" / "runtime_console" / "ui" / "detail.js").read_text(encoding="utf-8")

    assert "cypherOverviewCard('生成 Cypher', generationCypherText({ ...generator, generated_cypher: generatedCypher }))" in script
    assert "cypherOverviewCard('生成 Cypher', generationCypherText({ ...generator, generated_cypher: generatedCypher }), summary.generation_status)" not in script


def test_runtime_results_task_table_uses_chinese_clarification_status():
    script = (Path(__file__).resolve().parents[1] / "console" / "runtime_console" / "ui" / "app.js").read_text(encoding="utf-8")

    assert "clarification_required: '需要澄清'" in script


def test_runtime_results_tables_have_stable_column_widths():
    root = Path(__file__).resolve().parents[1]
    index_html = (root / "console" / "runtime_console" / "ui" / "index.html").read_text(encoding="utf-8")
    detail_js = (root / "console" / "runtime_console" / "ui" / "detail.js").read_text(encoding="utf-8")
    styles = (root / "console" / "runtime_console" / "ui" / "styles.css").read_text(encoding="utf-8")

    assert '<table class="task-table">' in index_html
    assert '<col style="width: 220px" />' in index_html
    assert '<col style="width: 180px" />' in index_html
    assert '<col style="width: 430px" />' in index_html
    assert '<col style="width: 474px" />' in index_html
    assert "const colgroup = columns" in detail_js
    assert '<col style="width: ${width}px" />' in detail_js
    assert ".task-table" in styles
    assert "min-width: 2060px" in styles
    assert ".status-pill" in styles
    assert "white-space: nowrap" in styles
    assert "min-width: 112px" in styles
    assert "min-width: max(100%, 960px)" in styles


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


def test_runtime_results_task_index_does_not_decode_full_prompt_snapshots(tmp_path: Path, monkeypatch):
    testing_dir = tmp_path / "testing"
    repair_dir = tmp_path / "repair"
    _write_json(testing_dir / "goldens" / "qa_big_trace.json", {"id": "qa_big_trace", "difficulty": "L2"})
    _write_json(
        testing_dir / "submissions" / "qa_big_trace.json",
        {
            "id": "qa_big_trace",
            "attempt_no": 1,
            "question": "查询大 trace 样本",
            "generation_run_id": "run-big-trace",
            "generated_cypher": "MATCH (s:Service) RETURN s",
            "input_prompt_snapshot": json.dumps(
                {"schema_version": "cga_trace_v2", "trace_profile": "ontology", "large": "x" * 200_000},
                ensure_ascii=False,
            ),
            "generation_status": "generated",
            "state": "passed",
            "received_at": "2026-05-25T12:00:00+00:00",
            "updated_at": "2026-05-25T12:01:00+00:00",
        },
    )

    from console.runtime_console.app.service import RuntimeResultsService

    service = RuntimeResultsService(
        testing_data_dir=str(testing_dir),
        repair_data_dir=str(repair_dir),
        cypher_generator_agent_base_url="http://127.0.0.1:8000",
        testing_service_base_url="http://127.0.0.1:8003",
        repair_service_base_url="http://127.0.0.1:8002",
        knowledge_agent_base_url="http://127.0.0.1:8010",
        qa_generator_base_url="http://127.0.0.1:8020",
    )

    def fail_full_json_read(path: Path):
        raise AssertionError(f"list/summary should use lightweight metadata, not full JSON reads: {path}")

    monkeypatch.setattr(service, "_read_json", fail_full_json_read)

    tasks_payload = service.list_tasks()
    summary_payload = service.get_task_summary()

    assert [task["id"] for task in tasks_payload["tasks"]] == ["qa_big_trace"]
    assert tasks_payload["tasks"][0]["final_verdict"] == "pass"
    l2_bucket = next(bucket for bucket in summary_payload["buckets"] if bucket["difficulty"] == "L2")
    assert l2_bucket["total"] == 1
    assert l2_bucket["pass"] == 1


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


def _inline_ref(value: object) -> dict:
    return {"type": "inline", "value": value, "reason": None, "artifact_uri": None}


def _graph_stage(
    stage: str,
    *,
    output: object | None = None,
    input_payload: object | None = None,
    status: str = "success",
    duration_ms: int = 3,
    metrics: dict | None = None,
    errors: list[dict] | None = None,
    warnings: list[dict] | None = None,
) -> dict:
    return {
        "stage": stage,
        "status": status,
        "started_at": "2026-05-28T00:00:00+00:00",
        "duration_ms": duration_ms,
        "input_ref": _inline_ref(input_payload) if input_payload is not None else None,
        "output_ref": _inline_ref(output) if output is not None else None,
        "metrics": metrics or {},
        "errors": errors or [],
        "warnings": warnings or [],
    }


def test_runtime_results_generator_section_parses_cga_graph_trace_v1(monkeypatch, tmp_path: Path):
    testing_dir = tmp_path / "testing"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(tmp_path / "repair"))
    llm_call = {
        "call_id": "question_decomposer-1",
        "stage": "question_decomposer",
        "schema_name": "question_decomposition_v1",
        "attempt": 1,
        "model": "qwen3-32b",
        "prompt": "请把问题拆成结构化槽位。\nJSON Schema: ...",
        "raw_output": "{\"schema_version\":\"question_decomposition_v1\",\"intent_type\":\"list\"}",
        "parsed_output": {
            "schema_version": "question_decomposition_v1",
            "result_type": "decomposition",
            "intent_type": "list",
            "target_concepts": ["服务", "隧道"],
        },
        "status": "success",
    }
    dsl = {
        "schema_version": "restricted_query_dsl_v1",
        "query_shape": "single_hop_traversal",
        "operations": [{"op": "match", "from": "Service", "edge": "SERVICE_USES_TUNNEL", "to": "Tunnel"}],
    }
    trace_snapshot = {
        "trace_schema_version": "cga_graph_trace_v1",
        "trace_id": "run-graph-trace",
        "question_id": "qa_graph_trace",
        "generation_run_id": "run-graph-trace",
        "source_question": "Gold 服务使用了哪些隧道？",
        "started_at": "2026-05-28T00:00:00+00:00",
        "finished_at": "2026-05-28T00:00:01+00:00",
        "final_status": "generated",
        "semantic_model": {"name": "network_schema_v10", "checksum": "sha256:test"},
        "stages": [
            _graph_stage("graph_model_loader", output={"model_name": "network_schema_v10", "vertices": 5, "edges": 4}),
            _graph_stage("input_clarification_gate", input_payload={"question": "Gold 服务使用了哪些隧道？"}, output={"status": "pass"}),
            _graph_stage(
                "question_decomposer",
                input_payload={"question": "Gold 服务使用了哪些隧道？"},
                output={
                    "schema_version": "question_decomposition_v1",
                    "result_type": "decomposition",
                    "intent_type": "list",
                    "target_concepts": ["服务", "隧道"],
                    "literal_candidates": ["Gold"],
                    "llm_calls": [llm_call],
                },
                metrics={"llm_call_count": 1},
            ),
            _graph_stage("candidate_retrieval", output={"candidates": [{"semantic_id": "Service"}, {"semantic_id": "Tunnel"}]}, metrics={"candidate_count": 2}),
            _graph_stage("literal_resolver", output=[{"raw_literal": "Gold", "resolved": True, "resolved_value": "Gold"}]),
            _graph_stage("grounded_understanding", output={"query_shape": "single_hop", "selected_vertices": ["Service", "Tunnel"]}),
            _graph_stage("semantic_binder", output={"query_shape": "single_hop_traversal"}),
            _graph_stage("semantic_validator", output={"is_valid": True, "assumptions": []}),
            _graph_stage("dsl_builder", output=dsl),
            _graph_stage("dsl_parser", output={"query_shape": "single_hop_traversal", "operation_count": 1}),
            _graph_stage(
                "cypher_compiler",
                output={
                    "schema_version": "cypher_compile_result_v1",
                    "cypher": "MATCH (svc:Service)-[:SERVICE_USES_TUNNEL]->(tun:Tunnel) RETURN tun.id AS tunnel_id",
                    "parameters": {"quality_of_service": "Gold"},
                    "expected_return_aliases": ["tunnel_id"],
                },
            ),
            _graph_stage(
                "cypher_self_validation",
                output={"valid": True, "errors": [], "warnings": [], "checked_rules": ["syntax", "readonly", "schema"]},
            ),
            _graph_stage("output", output={"status": "generated", "has_dsl": True, "has_cypher": True}),
        ],
        "final_outputs": {
            "dsl": dsl,
            "cypher": "MATCH (svc:Service)-[:SERVICE_USES_TUNNEL]->(tun:Tunnel) RETURN tun.id AS tunnel_id",
            "clarification": None,
            "user_visible_notices": ["我把 Gold 理解为 Service.quality_of_service=Gold。"],
            "failure": None,
        },
    }
    _write_json(
        testing_dir / "goldens" / "qa_graph_trace.json",
        {
            "id": "qa_graph_trace",
            "difficulty": "L3",
            "cypher": "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel) RETURN t.id",
        },
    )
    _write_json(
        testing_dir / "submissions" / "qa_graph_trace.json",
        {
            "id": "qa_graph_trace",
            "attempt_no": 1,
            "question": "Gold 服务使用了哪些隧道？",
            "generation_run_id": "run-graph-trace",
            "generated_cypher": trace_snapshot["final_outputs"]["cypher"],
            "input_prompt_snapshot": json.dumps(trace_snapshot, ensure_ascii=False),
            "generation_status": "generated",
            "state": "received_submission_only",
            "received_at": "2026-05-28T00:00:01+00:00",
            "updated_at": "2026-05-28T00:00:01+00:00",
        },
    )

    from console.runtime_console.app.main import create_app

    client = TestClient(create_app())
    response = client.get("/api/v1/tasks/qa_graph_trace")

    assert response.status_code == 200
    generator = response.json()["pipeline"]["cypher_generator_agent"]
    assert generator["trace_schema_version"] == "cga_graph_trace_v1"
    assert generator["trace_profile"] == "graph"
    assert generator["trace_layers"] == []
    flow = generator["cga_flow"]
    assert flow["trace_id"] == "run-graph-trace"
    assert flow["summary"]["semantic_model"] == "network_schema_v10"
    assert flow["summary"]["current_stage"] == "cypher_self_validation"
    assert flow["summary"]["current_stage_title_zh"] == "Cypher 自校验"
    assert flow["summary"]["stage_count"] == 13
    assert [stage["key"] for stage in flow["stages"]][:4] == [
        "graph_model_loader",
        "input_clarification_gate",
        "question_decomposer",
        "candidate_retrieval",
    ]
    stage_titles = {stage["key"]: stage["title_zh"] for stage in flow["stages"]}
    assert stage_titles["question_decomposer"] == "问题结构化拆解"
    assert stage_titles["cypher_self_validation"] == "Cypher 自校验"
    assert flow["stages"][2]["output"]["llm_calls"][0]["call_id"] == "question_decomposer-1"
    assert flow["llm_calls"] == [
        {
            "call_id": "question_decomposer-1",
            "stage": "question_decomposer",
            "stage_title_zh": "问题结构化拆解",
            "schema_name": "question_decomposition_v1",
            "attempt": 1,
            "model": "qwen3-32b",
            "prompt": "请把问题拆成结构化槽位。\nJSON Schema: ...",
            "raw_output": "{\"schema_version\":\"question_decomposition_v1\",\"intent_type\":\"list\"}",
            "parsed_output": {
                "schema_version": "question_decomposition_v1",
                "result_type": "decomposition",
                "intent_type": "list",
                "target_concepts": ["服务", "隧道"],
            },
            "status": "success",
            "error": None,
        }
    ]
    assert flow["artifacts"]["dsl"]["query_shape"] == "single_hop_traversal"
    assert flow["artifacts"]["cypher"].startswith("MATCH (svc:Service)")
    assert flow["artifacts"]["compiler"]["parameters"] == {"quality_of_service": "Gold"}
    assert flow["artifacts"]["self_validation"]["valid"] is True
    assert flow["artifacts"]["user_visible_notices"] == ["我把 Gold 理解为 Service.quality_of_service=Gold。"]
    assert "chain_summary" not in flow


def test_runtime_results_graph_clarification_uses_repair_and_literal_trace(monkeypatch, tmp_path: Path):
    testing_dir = tmp_path / "testing"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(tmp_path / "repair"))
    trace_snapshot = {
        "trace_schema_version": "cga_graph_trace_v1",
        "trace_id": "run-graph-clarify",
        "question_id": "qa_graph_clarify",
        "generation_run_id": "run-graph-clarify",
        "source_question": "查询所有服务使用的隧道的名称、ID及详细信息。",
        "started_at": "2026-05-28T00:00:00+00:00",
        "finished_at": "2026-05-28T00:00:01+00:00",
        "final_status": "clarification_required",
        "semantic_model": {"name": "network_schema_v10", "checksum": "sha256:test"},
        "stages": [
            _graph_stage("graph_model_loader", output={"model_name": "network_schema_v10"}),
            _graph_stage("question_decomposer", output={"literal_candidates": ["名称", "ID", "详细信息"]}),
            _graph_stage(
                "literal_resolver",
                output=[
                    {
                        "raw_literal": "名称",
                        "expected": "Tunnel.elem_type",
                        "resolved": False,
                        "error_code": "literal_value_index_miss",
                        "value_index_miss": True,
                        "alternatives": [],
                    },
                    {
                        "raw_literal": "ID",
                        "expected": "Tunnel.elem_type",
                        "resolved": False,
                        "error_code": "literal_value_index_miss",
                        "value_index_miss": True,
                    },
                ],
            ),
            _graph_stage("semantic_validator", output={"is_valid": False}),
            _graph_stage(
                "repair_controller",
                input_payload={
                    "validator_errors": [
                        {
                            "code": "literal_unresolved",
                            "message": "literal '名称' could not be resolved for Tunnel.elem_type",
                            "action": "ask_user",
                            "details": {
                                "literal": "名称",
                                "property": "Tunnel.elem_type",
                                "alternatives": [],
                            },
                        },
                        {
                            "code": "literal_unresolved",
                            "message": "literal 'ID' could not be resolved for Tunnel.elem_type",
                            "action": "ask_user",
                            "details": {
                                "literal": "ID",
                                "property": "Tunnel.elem_type",
                                "alternatives": [],
                            },
                        },
                    ]
                },
                output={
                    "decision": "ask_user",
                    "reason_code": "literal_unresolved",
                    "clarification": {
                        "source_stage": "semantic_validator",
                        "reason_code": "literal_unresolved",
                        "question": "我没有确定“名称”对应的值，请选择或补充。",
                        "expected_answer_type": "free_text",
                        "options": [],
                    },
                },
            ),
            _graph_stage("output", output={"status": "clarification_required"}),
        ],
        "final_outputs": {
            "dsl": None,
            "cypher": None,
            "clarification": {"question": "我没有确定“名称”对应的值，请选择或补充。"},
            "failure": None,
            "user_visible_notices": [],
        },
    }
    _write_json(testing_dir / "goldens" / "qa_graph_clarify.json", {"id": "qa_graph_clarify", "difficulty": "L3"})
    _write_json(
        testing_dir / "generation_failures" / "qa_graph_clarify__run-graph-clarify.json",
        {
            "id": "qa_graph_clarify",
            "question": "查询所有服务使用的隧道的名称、ID及详细信息。",
            "generation_run_id": "run-graph-clarify",
            "generation_status": "clarification_required",
            "input_prompt_snapshot": json.dumps(trace_snapshot, ensure_ascii=False),
            "clarification": {"question": "我没有确定“名称”对应的值，请选择或补充。"},
            "gate_passed": False,
            "received_at": "2026-05-28T00:00:01+00:00",
        },
    )

    from console.runtime_console.app.main import create_app

    client = TestClient(create_app())
    response = client.get("/api/v1/tasks/qa_graph_clarify")

    assert response.status_code == 200
    generator = response.json()["pipeline"]["cypher_generator_agent"]
    clarification = generator["clarification"]
    assert clarification["question_zh"] == "我没有确定“名称”对应的值，请选择或补充。"
    assert clarification["decision"] == "ask_user"
    assert clarification["reason_code"] == "literal_unresolved"
    assert clarification["source_stage"] == "semantic_validator"
    assert clarification["source_stage_label_zh"] == "语义正确性校验"
    assert generator["cga_flow"]["summary"]["current_stage"] == "repair_controller"
    assert generator["cga_flow"]["summary"]["current_stage_title_zh"] == "修复与澄清决策"
    assert clarification["expected_answer_type"] == "free_text"
    assert clarification["no_option_reason"] == "当前澄清需要用户补充文本，不是固定选项选择。"
    assert clarification["unresolved_items"] == [
        {
            "term": "名称",
            "expected": "Tunnel.elem_type",
            "code": "literal_value_index_miss",
            "alternatives": [],
            "value_index_miss": True,
        },
        {
            "term": "ID",
            "expected": "Tunnel.elem_type",
            "code": "literal_value_index_miss",
            "alternatives": [],
            "value_index_miss": True,
        },
    ]
    assert clarification["validation_errors"] == [
        {
            "code": "literal_unresolved",
            "message": "literal '名称' could not be resolved for Tunnel.elem_type",
            "action": "ask_user",
            "literal": "名称",
            "property": "Tunnel.elem_type",
            "alternatives": [],
        },
        {
            "code": "literal_unresolved",
            "message": "literal 'ID' could not be resolved for Tunnel.elem_type",
            "action": "ask_user",
            "literal": "ID",
            "property": "Tunnel.elem_type",
            "alternatives": [],
        },
    ]
    assert generator["cga_flow"]["artifacts"]["clarification"] == clarification
    assert response.json()["summary"]["clarification"]["unresolved_items"][0]["term"] == "名称"


def _llm_trace_call(
    call_id: str,
    stage: str,
    prompt_markdown: str,
    raw_output: str,
    *,
    parsed_output: dict | None = None,
    accepted: bool = True,
) -> dict:
    return {
        "call_id": call_id,
        "stage": stage,
        "model": "qwen3-vl-32b-thinking",
        "prompt_markdown": prompt_markdown,
        "raw_output": raw_output,
        "parsed_output": parsed_output or {},
        "accepted": accepted,
        "rejected_reason": None if accepted else "low_confidence",
    }


def test_runtime_results_generator_section_parses_cga_trace_v2_generated(monkeypatch, tmp_path: Path):
    testing_dir = tmp_path / "testing"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(tmp_path / "repair"))
    trace_snapshot = {
        "schema_version": "cga_trace_v2",
        "question": "查询 Gold 服务使用的隧道名称。",
        "generation_run_id": "run-trace-v2-generated",
        "generation_status": "generated",
        "service_context": {
            "active_mode": "semantic_view_pipeline",
            "model": "qwen3-vl-32b-thinking",
            "semantic_view_version": "network_graph_semantic_view@2026-05-11",
            "rag_source": "http://127.0.0.1:8004/api/v1/retrieve",
        },
        "intent_recognition": {
            "result": {
                "primary_intent": "record_retrieval_query",
                "secondary_intent": "related_record_query",
                "source": "llm",
                "decision": "accept",
                "confidence": 0.86,
            },
            "diagnostics": {
                "rule_hit": None,
                "embedding_candidates": [{"id": "intent-candidate-1", "score": 0.71}],
                "llm_primary_attempts": [
                    _llm_trace_call(
                        "llm-intent-primary-001",
                        "intent_recognition.primary",
                        "一级意图 prompt",
                        "{\"primary_intent\":\"record_retrieval_query\"}",
                        parsed_output={"primary_intent": "record_retrieval_query"},
                    )
                ],
                "llm_secondary_attempts": [
                    _llm_trace_call(
                        "llm-intent-secondary-001",
                        "intent_recognition.secondary",
                        "二级意图 prompt",
                        "{\"secondary_intent\":\"related_record_query\"}",
                        parsed_output={"secondary_intent": "related_record_query"},
                    ),
                ],
            },
        },
        "semantic_view_matching": {
            "stages": {"candidate_generation": {"decision": "accept", "candidate_count": 1}},
            "llm_disambiguation_attempts": [
                _llm_trace_call(
                    "llm-semantic-disambiguation-001",
                    "semantic_view_matching.disambiguation",
                    "语义视图消歧 prompt",
                    "{\"selected\":\"view-a\"}",
                    parsed_output={"selected": "view-a"},
                )
            ],
            "result": {
                "matched_entities": [{"type": "Service", "name": "Gold"}],
                "filters": [{"field": "service.name", "operator": "=", "value": "Gold"}],
                "path_semantics": [{"name": "service_uses_tunnel"}],
                "return_objects": ["tunnel.name"],
                "confidence": 0.9,
                "ambiguity": None,
                "trace": {
                    "semantic_completion": [{"entity": "service", "status": "filled"}],
                    "candidate_scores": [{"candidate_id": "view-a", "score": 0.93}],
                },
                "candidate_trace": [{"candidate_id": "view-a"}],
            }
        },
        "logical_query_plan": {
            "answer_shape": "table",
            "operations": [{"op": "expand", "path_ref": "path-service-tunnel"}],
            "path_refs": ["path-service-tunnel"],
            "render_hints": {"return": ["tunnel.name"]},
        },
        "schema_path_planning": {
            "selected_path": {"id": "path-service-tunnel"},
            "candidate_paths": [{"id": "path-service-tunnel", "score": 0.92}],
            "rejected_paths": [],
        },
        "knowledge_selection": {
            "source": "rag",
            "retrieve_query": {"text": "Gold 服务 隧道"},
            "selected_items": [{"id": "knowledge-card-1", "title": "服务到隧道关系"}],
            "rejected_items": [],
        },
        "generation": {
            "renderer": {"family": "deterministic", "accepted": False, "cypher": "", "failure_reason": "unsupported_shape"},
            "cypher_fallback_llm": _llm_trace_call(
                "llm-cypher-fallback-001",
                "generation.cypher_fallback",
                "Cypher 兜底 prompt",
                "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel) RETURN t.name",
            ),
            "parser": {
                "parsed_cypher": "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel) RETURN t.name",
                "parse_summary": "cypher_only",
            },
        },
        "preflight": {"accepted": True, "checks": [{"name": "schema", "accepted": True}], "reason": None},
        "clarification": None,
        "delivery": {"target": "testing-agent", "status": "delivered", "reason": None},
    }
    _write_json(
        testing_dir / "goldens" / "qa_trace_v2_generated.json",
        {
            "id": "qa_trace_v2_generated",
            "difficulty": "L4",
            "cypher": "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel) RETURN t.name",
        },
    )
    _write_json(
        testing_dir / "submissions" / "qa_trace_v2_generated.json",
        {
            "id": "qa_trace_v2_generated",
            "attempt_no": 1,
            "question": "查询 Gold 服务使用的隧道名称。",
            "generation_run_id": "run-trace-v2-generated",
            "generated_cypher": "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel) RETURN t.name",
            "input_prompt_snapshot": json.dumps(trace_snapshot, ensure_ascii=False),
            "generation_status": "generated",
            "state": "evaluated",
        },
    )

    from console.runtime_console.app.main import create_app

    client = TestClient(create_app())
    response = client.get("/api/v1/tasks/qa_trace_v2_generated")

    assert response.status_code == 200
    generator = response.json()["pipeline"]["cypher_generator_agent"]
    assert generator["trace_schema_version"] == "cga_trace_v2"
    trace_layers = generator["trace_layers"]
    assert [layer["key"] for layer in trace_layers] == [
        "orchestration",
        "intent_recognition",
        "semantic_view_matching",
        "planning",
        "generation",
    ]
    assert [layer["title_zh"] for layer in trace_layers] == [
        "服务编排层",
        "意图识别层",
        "语义视图匹配层",
        "规划层",
        "生成与提交层",
    ]
    orchestration_fields = {field["label_zh"]: field["value"] for field in trace_layers[0]["fields"]}
    assert orchestration_fields["运行模式"] == "semantic_view_pipeline"
    assert orchestration_fields["模型"] == "qwen3-vl-32b-thinking"
    assert trace_layers[1]["raw"]["result"]["primary_intent"] == "record_retrieval_query"
    intent_fields = {field["label_zh"]: field["value"] for field in trace_layers[1]["fields"]}
    assert intent_fields["二级 LLM 调用"] == "1 条"
    assert "兜底 LLM 调用" not in intent_fields
    semantic_fields = {field["label_zh"]: field["value"] for field in trace_layers[2]["fields"]}
    assert semantic_fields["候选生成"] == "1 条"
    assert trace_layers[2]["raw"]["llm_disambiguation_attempts"][0]["call_id"] == "llm-semantic-disambiguation-001"
    assert trace_layers[3]["raw"]["logical_query_plan"]["answer_shape"] == "table"
    assert trace_layers[4]["raw"]["generation"]["parser"]["parse_summary"] == "cypher_only"

    prompts = generator["llm_prompts"]
    assert prompts["intent_primary_classification"]["title_zh"] == "意图识别：一级分类 LLM 判定"
    assert prompts["intent_primary_classification"]["triggered"] is True
    assert prompts["intent_primary_classification"]["prompt"] == "一级意图 prompt"
    assert prompts["intent_primary_classification"]["raw_output"] == "{\"primary_intent\":\"record_retrieval_query\"}"
    assert prompts["intent_secondary_classification"]["prompt"] == "二级意图 prompt"
    assert "intent_recognition_fallback" not in prompts
    assert prompts["semantic_view_disambiguation"]["raw_output"] == "{\"selected\":\"view-a\"}"
    assert prompts["cypher_generation_fallback"]["title_zh"] == "Renderer 失败后的 Cypher 兜底生成"
    assert prompts["cypher_generation_fallback"]["raw_output"].startswith("MATCH (s:Service)")


def test_runtime_results_generator_section_parses_cga_trace_v2_clarification_required(monkeypatch, tmp_path: Path):
    testing_dir = tmp_path / "testing"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(tmp_path / "repair"))
    clarification = {
        "source_stage": "semantic_view_matching",
        "reason_code": "ambiguous_path_semantic",
        "question_zh": "你说的对应网元是指源网元还是目的网元？",
        "expected_answer_type": "single_choice",
        "options": [{"id": "source", "label": "源网元"}, {"id": "target", "label": "目的网元"}],
    }
    trace_snapshot = {
        "schema_version": "cga_trace_v2",
        "question": "查询服务 A 对应的网元。",
        "generation_run_id": "run-trace-v2-clarify",
        "generation_status": "clarification_required",
        "service_context": {"active_mode": "semantic_view_pipeline", "model": "qwen3-vl-32b-thinking"},
        "intent_recognition": {
            "result": {
                "primary_intent": "record_retrieval_query",
                "secondary_intent": "related_record_query",
                "source": "llm",
                "decision": "accept",
                "confidence": 0.82,
            },
            "diagnostics": {
                "llm_primary_attempts": [
                    _llm_trace_call(
                        "llm-intent-primary-clarify-001",
                        "intent_recognition.primary",
                        "澄清场景一级意图 prompt",
                        "{\"primary_intent\":\"record_retrieval_query\"}",
                    )
                ],
                "llm_secondary_attempts": [],
            },
        },
        "semantic_view_matching": {
            "result": {
                "matched_entities": [{"type": "Service", "name": "A"}],
                "ambiguity": {"reason": "source_or_target_ne"},
                "trace": {
                    "candidate_scores": [
                        {"candidate_id": "source-ne", "score": 0.88},
                        {"candidate_id": "target-ne", "score": 0.87},
                    ],
                    "llm_disambiguation_attempts": [
                        _llm_trace_call(
                            "llm-semantic-disambiguation-clarify-001",
                            "semantic_view_matching.disambiguation",
                            "澄清场景语义视图消歧 prompt",
                            "{\"decision\":\"clarify\"}",
                            parsed_output={"decision": "clarify"},
                            accepted=False,
                        )
                    ],
                },
            }
        },
        "logical_query_plan": {},
        "schema_path_planning": {"selected_path": None, "candidate_paths": [], "rejected_paths": []},
        "knowledge_selection": {"source": "rag", "selected_items": [], "rejected_items": []},
        "generation": {"renderer": {"family": "deterministic", "accepted": False}, "cypher_fallback_llm": None, "parser": {}},
        "preflight": {"accepted": False, "checks": [], "reason": "ambiguous_path_semantic"},
        "clarification": clarification,
        "delivery": {"target": "testing-agent", "status": "delivered", "reason": None},
    }
    _write_json(testing_dir / "goldens" / "qa_trace_v2_clarify.json", {"id": "qa_trace_v2_clarify", "difficulty": "L5"})
    _write_json(
        testing_dir / "generation_failures" / "qa_trace_v2_clarify__run-trace-v2-clarify.json",
        {
            "id": "qa_trace_v2_clarify",
            "question": "查询服务 A 对应的网元。",
            "generation_run_id": "run-trace-v2-clarify",
            "generation_status": "clarification_required",
            "input_prompt_snapshot": json.dumps(trace_snapshot, ensure_ascii=False),
            "clarification": clarification,
            "parsed_cypher": None,
            "gate_passed": False,
            "received_at": "2026-05-11T00:00:00+00:00",
        },
    )

    from console.runtime_console.app.main import create_app

    client = TestClient(create_app())
    response = client.get("/api/v1/tasks/qa_trace_v2_clarify")

    assert response.status_code == 200
    generator = response.json()["pipeline"]["cypher_generator_agent"]
    assert generator["generation_status"] == "clarification_required"
    assert generator["trace_schema_version"] == "cga_trace_v2"
    assert generator["clarification"]["question_zh"] == "你说的对应网元是指源网元还是目的网元？"
    assert response.json()["summary"]["clarification"]["question_zh"] == "你说的对应网元是指源网元还是目的网元？"
    assert [layer["key"] for layer in generator["trace_layers"]] == [
        "orchestration",
        "intent_recognition",
        "semantic_view_matching",
        "planning",
        "generation",
    ]
    semantic_view_layer = generator["trace_layers"][2]
    assert semantic_view_layer["raw"]["result"]["ambiguity"]["reason"] == "source_or_target_ne"
    generation_fields = {field["label_zh"]: field["value"] for field in generator["trace_layers"][4]["fields"]}
    assert generation_fields["澄清问题"] == "你说的对应网元是指源网元还是目的网元？"
    prompts = generator["llm_prompts"]
    assert prompts["intent_primary_classification"]["prompt"] == "澄清场景一级意图 prompt"
    assert prompts["semantic_view_disambiguation"]["triggered"] is True
    assert prompts["semantic_view_disambiguation"]["raw_output"] == "{\"decision\":\"clarify\"}"
    assert prompts["cypher_generation_fallback"]["triggered"] is False

    list_response = client.get("/api/v1/tasks")
    assert list_response.status_code == 200
    task = list_response.json()["tasks"][0]
    assert task["clarification"]["question_zh"] == "你说的对应网元是指源网元还是目的网元？"
    assert task["clarification_summary"] == "你说的对应网元是指源网元还是目的网元？"


def test_runtime_results_normalizes_unified_clarification_payload_for_display(monkeypatch, tmp_path: Path):
    testing_dir = tmp_path / "testing"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(tmp_path / "repair"))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_CGA_TRACE_PROFILE", "ontology")
    clarification = {
        "core_question": "查询服务相关网元",
        "source_step": "step_3_3_ontology_path_selection",
        "reason_code": "ambiguous_path",
        "reason": "存在多条路径。",
        "missing_information": "用户需要确认对象之间按哪条业务关系连接。",
        "user_message": "你想按服务到源网元，还是服务到目的网元来查询？",
        "options": ["服务到源网元", "服务到目的网元"],
    }
    _write_json(testing_dir / "goldens" / "qa_unified_clarify.json", {"id": "qa_unified_clarify", "difficulty": "L5"})
    _write_json(
        testing_dir / "generation_failures" / "qa_unified_clarify__run-unified-clarify.json",
        {
            "id": "qa_unified_clarify",
            "question": "查询服务相关网元",
            "generation_run_id": "run-unified-clarify",
            "generation_status": "clarification_required",
            "input_prompt_snapshot": json.dumps(clarification, ensure_ascii=False),
            "clarification": clarification,
            "parsed_cypher": None,
            "gate_passed": False,
            "received_at": "2026-05-11T00:00:00+00:00",
        },
    )

    from console.runtime_console.app.main import create_app

    client = TestClient(create_app())
    response = client.get("/api/v1/tasks/qa_unified_clarify")

    assert response.status_code == 200
    display = response.json()["summary"]["clarification"]
    assert display["question_zh"] == "你想按服务到源网元，还是服务到目的网元来查询？"
    assert display["source_step"] == "step_3_3_ontology_path_selection"
    assert display["source_stage"] == "step_3_3_ontology_path_selection"
    assert display["reason"] == "存在多条路径。"
    assert display["missing_information"] == "用户需要确认对象之间按哪条业务关系连接。"
    assert display["expected_answer_type"] == "single_choice"
    assert display["options"] == [
        {"id": "option_1", "label": "服务到源网元"},
        {"id": "option_2", "label": "服务到目的网元"},
    ]
    assert response.json()["summary"]["clarification_summary"] == display["question_zh"]

    list_response = client.get("/api/v1/tasks")
    assert list_response.status_code == 200
    task = list_response.json()["tasks"][0]
    assert task["id"] == "qa_unified_clarify"
    assert task["cga_trace_profile"] == "ontology"
    assert task["clarification_summary"] == display["question_zh"]


def test_runtime_results_generator_section_parses_ontology_cga_trace(monkeypatch, tmp_path: Path):
    testing_dir = tmp_path / "testing"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(tmp_path / "repair"))
    trace_snapshot = {
        "schema_version": "cga_trace_v2",
        "trace_id": "run-ontology-trace",
        "preprocessing": {
            "accepted": True,
            "original_question": "帮我查一下金牌服务使用的隧道名称",
            "core_question": "查询金牌服务使用的隧道名称",
        },
        "lexer": {
            "question": "查询金牌服务使用的隧道名称",
            "question_framing": {
                "enabled": True,
                "question": "查询金牌服务使用的隧道名称",
                "prompt": "Step 0 完整提示词",
                "raw_response": "原子问题：\n1. 金牌服务 ｜ 找什么对象 + 用什么条件筛选\n2. 使用的隧道 ｜ 通过什么关系继续找\n3. 隧道名称 ｜ 最后返回什么",
                "atoms": [
                    {
                        "atom_id": "QA1",
                        "text": "金牌服务",
                        "roles": ["FIND_OBJECT", "FILTER_CONDITION"],
                        "span": [2, 6],
                        "confidence": 0.9,
                        "raw_role_text": "找什么对象 + 用什么条件筛选",
                    },
                    {
                        "atom_id": "QA2",
                        "text": "使用的隧道",
                        "roles": ["RELATION_PATH"],
                        "span": [6, 11],
                        "confidence": 0.9,
                        "raw_role_text": "通过什么关系继续找",
                    },
                    {
                        "atom_id": "QA3",
                        "text": "隧道名称",
                        "roles": ["RETURN_CONTENT"],
                        "span": [9, 13],
                        "confidence": 0.9,
                        "raw_role_text": "最后返回什么",
                    },
                ],
                "retrieval_plan": {
                    "version": "question_framing_retrieval_plan_v1",
                    "question": "查询金牌服务使用的隧道名称",
                    "path_queries": [
                        {
                            "query_id": "PQ1",
                            "atom_ids": ["QA1", "QA2"],
                            "source_text": "金牌服务",
                            "path_text": "使用的隧道",
                            "retrieval_text": "金牌服务 使用的隧道",
                            "roles": ["FIND_OBJECT", "FILTER_CONDITION", "RELATION_PATH"],
                            "grounding_spans": [[2, 6], [6, 11]],
                            "generic_connectors": [],
                        }
                    ],
                    "return_targets": [{"atom_id": "QA3", "text": "隧道名称"}],
                    "attribute_queries": [{"atom_id": "QA3", "text": "隧道名称"}],
                    "metric_queries": [],
                    "diagnostics": [],
                },
                "diagnostics": [],
            },
            "vector_recalls": [
                {
                    "fragment": "金牌服务 使用的隧道",
                    "span": [2, 11],
                    "provider": "fixture",
                    "source": "question_framing_retrieval_plan",
                    "query_id": "PQ1",
                    "candidates": [
                        {
                            "candidate_id": "VC1",
                            "canonical_id": "REL_SERVICE_USES_TUNNEL",
                            "mention_type": "RELATION",
                            "score": 0.92,
                            "matched_surface": "服务使用隧道",
                        }
                    ],
                }
            ],
            "ac_matches": [
                {
                    "canonical_id": "ServiceQuality.Gold",
                    "mention_type": "VALUE",
                    "surface": "金牌",
                    "span": [2, 4],
                    "hit_id": "ac-1",
                    "match_source": "ac_exact",
                    "score": 1.0,
                }
            ],
            "structured_matches": [
                {
                    "canonical_id": "OP_QUERY",
                    "mention_type": "OPERATION",
                    "surface": "查询",
                    "span": [0, 2],
                    "hit_id": "struct-1",
                    "match_source": "operation_cue",
                    "score": 1.0,
                }
            ],
            "unmatched_fragments": [{"surface": "使用的", "span": [6, 9], "expected_mention_type": "RELATION"}],
            "mentions": [
                {
                    "canonical_id": "ServiceQuality.Gold",
                    "mention_type": "VALUE",
                    "surface": "金牌",
                    "span": [2, 4],
                    "metadata": {"enum_class": "ServiceQuality"},
                },
                {"canonical_id": "Service", "mention_type": "OBJECT", "surface": "服务", "span": [4, 6]},
                {"canonical_id": "Tunnel.name", "mention_type": "ATTRIBUTE", "surface": "隧道名称", "span": [9, 13]},
            ],
            "context_signals": [
                {
                    "signal_id": "S2",
                    "type": "PROXIMAL_MODIFIER",
                    "text": "金牌服务",
                    "span": [2, 6],
                    "supports": ["ServiceQuality.Gold", "Service"],
                    "strength": 0.95,
                }
            ],
            "shape_signals": [
                {
                    "signal_id": "S1",
                    "type": "SHAPE_SIGNAL",
                    "text": "隧道名称",
                    "span": [9, 13],
                    "supports": ["answer_projection_region"],
                    "strength": 0.85,
                }
            ],
        },
        "intent": {
            "intent": {
                "primary": "record_retrieval_query",
                "secondary": "related_record_query",
                "source": "llm",
                "decision": "accept",
                "confidence": 0.8,
            },
            "initial_shape": {"answer_type": {"value": "attribute_table", "source": "taxonomy", "decision": "accept", "confidence": 1.0}},
            "diagnostics": {
                "llm_stages": [
                    {"rendered_prompt": "一层意图完整 prompt", "raw_response": "选择 C1。理由：明细查询", "decision": "accept", "candidate_id": "C1"},
                    {"rendered_prompt": "二层意图完整 prompt", "raw_response": "选择 C4。理由：关联明细", "decision": "accept", "candidate_id": "C4"},
                ]
            },
        },
        "object_role_selection": {
            "object_candidates": [{"candidate_id": "SM1", "surface": "服务"}],
            "object_role_selection": {"selected_objects": [{"candidate_id": "SM1", "roles": ["filter_subject", "path_subject"]}]},
            "llm_prompt": "3.1 对象角色 prompt",
            "llm_raw_output": "选择 SM1：filter_subject、path_subject。理由：金牌服务参与路径。",
        },
        "ontology_mapping": {
            "ontology_objects": [{"mapping_id": "OM1", "ontology_kind": "class", "class_id": "Service"}],
            "ontology_relation_hints": [{"mapping_id": "OM2", "ontology_kind": "relation", "relation_id": "SERVICE_USES_TUNNEL"}],
            "ontology_attributes": [{"mapping_id": "OM3", "ontology_kind": "attribute", "attribute_id": "Tunnel.name"}],
            "ontology_values": [{"mapping_id": "OM4", "ontology_kind": "enum_value", "value_id": "ServiceQuality.Gold"}],
            "evidence": [{"source": "mention_to_ontology"}],
        },
        "ontology_path_selection": {
            "path_requests": [{"request_id": "PR1"}],
            "candidate_paths": [{"path_id": "P1"}],
            "selected_paths": [{"request_id": "PR1", "path_id": "P1"}],
            "shape_updates": {},
            "llm_prompt": "3.3 路径选择 prompt",
            "llm_raw_output": "选择 PR1：P1。理由：服务使用隧道。",
        },
        "coreference": {
            "resolved_pairs": [{"candidate_pair_id": "CP1", "decision": "same_instance"}],
            "merged_nodes": [{"node_id": "N1"}],
            "llm_decision_traces": [
                {"candidate_pair_id": "CP1", "llm_prompt": "3.4 指代消解 prompt", "llm_raw_output": "选择 C1。理由：同一服务。"}
            ],
        },
        "binding": {"projections": [{"result": {"attribute": "Tunnel.name", "alias": "tunnel_name"}}]},
        "shape_finalization": {"logical_plan": {"root_operation": "match_project", "projection": [{"attribute": "name"}]}},
        "validator": {"accepted": True, "checks": [{"name": "required_nodes", "accepted": True}]},
        "compiler": {"cypher": "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel) RETURN t.name"},
    }
    _write_json(testing_dir / "goldens" / "qa_ontology_trace.json", {"id": "qa_ontology_trace", "difficulty": "L4"})
    _write_json(
        testing_dir / "submissions" / "qa_ontology_trace.json",
        {
            "id": "qa_ontology_trace",
            "attempt_no": 1,
            "question": "帮我查一下金牌服务使用的隧道名称",
            "generation_run_id": "run-ontology-trace",
            "generated_cypher": "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel) RETURN t.name",
            "input_prompt_snapshot": json.dumps(trace_snapshot, ensure_ascii=False),
            "generation_status": "generated",
            "state": "evaluated",
        },
    )

    from console.runtime_console.app.main import create_app

    client = TestClient(create_app())
    response = client.get("/api/v1/tasks/qa_ontology_trace")

    assert response.status_code == 200
    generator = response.json()["pipeline"]["cypher_generator_agent"]
    assert generator["trace_schema_version"] == "cga_trace_v2"
    assert [layer["key"] for layer in generator["trace_layers"]] == [
        "preprocessing",
        "question_framing",
        "lexical",
        "intent_shape",
        "ontology",
        "validation",
        "compilation",
    ]
    assert [layer["title_zh"] for layer in generator["trace_layers"]] == [
        "自然语言问题预处理",
        "Step 0 问题框定 / 检索计划",
        "词法层",
        "意图识别与答案形态",
        "本体层",
        "校验层",
        "编译层",
    ]
    assert all("raw" not in layer for layer in generator["trace_layers"])
    preprocessing_fields = {field["label_zh"]: field["value"] for field in generator["trace_layers"][0]["fields"]}
    assert preprocessing_fields["原始问题"] == "帮我查一下金牌服务使用的隧道名称"
    assert preprocessing_fields["输出给下一阶段的 core_question"] == "查询金牌服务使用的隧道名称"
    assert "未通过原因" not in preprocessing_fields
    assert generator["trace_layers"][0]["sections"] == []
    question_framing_fields = {field["label_zh"]: field["value"] for field in generator["trace_layers"][1]["fields"]}
    assert question_framing_fields["输入问题"] == "查询金牌服务使用的隧道名称"
    question_framing_sections = {section["title_zh"]: section["value"] for section in generator["trace_layers"][1]["sections"]}
    assert question_framing_sections["发给 LLM 的完整提示词"] == "Step 0 完整提示词"
    assert question_framing_sections["LLM 原始返回"].startswith("原子问题：")
    assert question_framing_sections["原子问题拆分结果"][1]["roles"] == ["RELATION_PATH"]
    assert question_framing_sections["结构化检索计划"]["path_queries"][0]["retrieval_text"] == "金牌服务 使用的隧道"
    assert question_framing_sections["Step 1 消费情况摘要"] == {
        "retrieval_plan_vector_recall_count": 1,
        "retrieval_plan_vector_recalls": [
            {
                "query_id": "PQ1",
                "retrieval_text": "金牌服务 使用的隧道",
                "span": [2, 11],
                "provider": "fixture",
                "candidate_count": 1,
                "top_candidates": [
                    {
                        "canonical_id": "REL_SERVICE_USES_TUNNEL",
                        "mention_type": "RELATION",
                        "score": 0.92,
                        "matched_surface": "服务使用隧道",
                    }
                ],
            }
        ],
    }
    lexical_fields = {field["label_zh"]: field["value"] for field in generator["trace_layers"][2]["fields"]}
    assert lexical_fields["mentions 数量"] == "3 条"
    assert lexical_fields["AC 命中数量"] == "1 条"
    assert lexical_fields["结构化命中数量"] == "1 条"
    assert lexical_fields["向量召回数量"] == "1 条"
    assert lexical_fields["未匹配残片数量"] == "1 条"
    assert lexical_fields["上下文信号数量"] == "1 条"
    assert lexical_fields["答案形态信号数量"] == "1 条"
    lexical_sections = [section["title_zh"] for section in generator["trace_layers"][2]["sections"]]
    assert lexical_sections == ["词法层明细"]
    lexical_detail = generator["trace_layers"][2]["sections"][0]
    lexical_tables = {table["title_zh"]: table for table in lexical_detail["tables"]}
    assert list(lexical_tables) == [
        "mentions 明细",
        "AC / 结构化命中明细",
        "向量召回明细",
        "未匹配残片",
        "context signals",
        "shape signals",
    ]
    assert lexical_tables["mentions 明细"]["rows"][0] == {
        "surface": "金牌",
        "mention_type": "VALUE",
        "canonical_id": "ServiceQuality.Gold",
        "span": "[2, 4]",
        "metadata": '{"enum_class": "ServiceQuality"}',
    }
    assert lexical_tables["mentions 明细"]["columns"][2]["width"] == 280
    assert lexical_tables["向量召回明细"]["columns"][-1]["width"] == 560
    assert lexical_tables["AC / 结构化命中明细"]["rows"][1]["match_source"] == "operation_cue"
    assert lexical_tables["向量召回明细"]["rows"][0]["top_candidates"] == "REL_SERVICE_USES_TUNNEL(RELATION, 0.92)"
    assert lexical_tables["未匹配残片"]["rows"][0]["expected_mention_type"] == "RELATION"
    assert lexical_tables["context signals"]["rows"][0]["supports"] == "ServiceQuality.Gold / Service"
    assert lexical_tables["shape signals"]["rows"][0]["supports"] == "answer_projection_region"
    lexical_blocks = {block["title_zh"]: block["value"] for block in lexical_detail["blocks"]}
    lexical_output = lexical_blocks["词法层完整输出"]
    assert lexical_output["mentions"][0]["surface"] == "金牌"
    assert lexical_output["context_signals"][0]["text"] == "金牌服务"
    assert lexical_output["shape_signals"][0]["text"] == "隧道名称"
    intent_fields = {field["label_zh"]: field["value"] for field in generator["trace_layers"][3]["fields"]}
    assert intent_fields["一层意图字段名称"] == "record_retrieval_query"
    assert intent_fields["一层意图中文解释"] == "明细/清单查询\n说明：返回实体、资源、记录或属性明细，不以统计值、路径结构或布尔判断为最终答案。"
    assert intent_fields["二层意图字段名称"] == "related_record_query"
    assert intent_fields["二层意图中文解释"] == "关联明细查询\n说明：沿关系或固定路径返回相关实体或属性明细，但不把图结构本身作为答案。"
    assert intent_fields["答案形态摘要"] == "answer_type=attribute_table"
    intent_sections = [section["title_zh"] for section in generator["trace_layers"][3]["sections"]]
    assert intent_sections == []
    ontology_layer = generator["trace_layers"][4]
    assert ontology_layer.get("fields", []) == []
    ontology_steps = {section["title_zh"]: section for section in ontology_layer["sections"]}
    assert list(ontology_steps) == [
        "3.1 对象提取与角色标注",
        "3.2 Mention 映射到本体",
        "3.3 本体路径选择",
        "3.4 指代消解选择",
        "3.5 字段绑定",
        "3.6 最终回填结构",
    ]
    object_role_fields = {field["label_zh"]: field["value"] for field in ontology_steps["3.1 对象提取与角色标注"]["fields"]}
    assert object_role_fields["对象候选"] == "服务"
    assert object_role_fields["角色标注"] == "SM1: filter_subject, path_subject"
    object_role_blocks = {block["title_zh"]: block["value"] for block in ontology_steps["3.1 对象提取与角色标注"]["blocks"]}
    assert object_role_blocks["LLM 原始输入提示词"] == "3.1 对象角色 prompt"
    mapping_fields = {field["label_zh"]: field["value"] for field in ontology_steps["3.2 Mention 映射到本体"]["fields"]}
    assert mapping_fields["对象映射"] == "Service"
    assert mapping_fields["关系线索"] == "SERVICE_USES_TUNNEL"
    assert mapping_fields["属性映射"] == "Tunnel.name"
    assert mapping_fields["取值映射"] == "ServiceQuality.Gold"
    mapping_blocks = {block["title_zh"]: block["value"] for block in ontology_steps["3.2 Mention 映射到本体"]["blocks"]}
    assert mapping_blocks["分类说明"][0]["description_zh"].startswith("对象类")
    path_fields = {field["label_zh"]: field["value"] for field in ontology_steps["3.3 本体路径选择"]["fields"]}
    assert path_fields["路径请求"] == "PR1"
    assert path_fields["选中路径"] == "PR1 -> P1"
    path_blocks = {block["title_zh"]: block["value"] for block in ontology_steps["3.3 本体路径选择"]["blocks"]}
    assert path_blocks["LLM 原始输出"] == "选择 PR1：P1。理由：服务使用隧道。"
    coreference_fields = {field["label_zh"]: field["value"] for field in ontology_steps["3.4 指代消解选择"]["fields"]}
    assert coreference_fields["指代消解决策"] == "CP1: same_instance"
    assert coreference_fields["合并节点"] == "N1"
    coreference_blocks = {block["title_zh"]: block["value"] for block in ontology_steps["3.4 指代消解选择"]["blocks"]}
    assert coreference_blocks["LLM 调用明细"][0]["prompt"] == "3.4 指代消解 prompt"
    binding_fields = {field["label_zh"]: field["value"] for field in ontology_steps["3.5 字段绑定"]["fields"]}
    assert binding_fields["投影绑定"] == "Tunnel.name AS tunnel_name"
    final_fields = {field["label_zh"]: field["value"] for field in ontology_steps["3.6 最终回填结构"]["fields"]}
    assert final_fields["根操作"] == "match_project"
    assert final_fields["投影字段"] == "name"
    final_blocks = {block["title_zh"]: block["value"] for block in ontology_steps["3.6 最终回填结构"]["blocks"]}
    assert final_blocks["Step 3 输出结构"]["logical_plan"]["root_operation"] == "match_project"
    validation_fields = {field["label_zh"]: field["value"] for field in generator["trace_layers"][5]["fields"]}
    assert validation_fields["校验结果"] == "校验通过"
    assert validation_fields["校验项摘要"] == "required_nodes: 通过"
    compilation_fields = {field["label_zh"]: field["value"] for field in generator["trace_layers"][6]["fields"]}
    assert compilation_fields["编译结果"] == "已输出 Cypher"
    assert compilation_fields["Cypher 摘要"] == "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel) RETURN t.name"
    prompts = generator["llm_prompts"]
    assert prompts["intent_primary_classification"]["title_zh"] == "一层意图 LLM 判定"
    assert prompts["intent_primary_classification"]["raw_output_title_zh"] == "一层意图 LLM 原始输出"
    assert prompts["intent_primary_classification"]["prompt"] == "一层意图完整 prompt"
    assert prompts["intent_secondary_classification"]["title_zh"] == "二层意图 LLM 判定"
    assert prompts["intent_secondary_classification"]["raw_output_title_zh"] == "二层意图 LLM 原始输出"
    assert prompts["intent_secondary_classification"]["raw_output"] == "选择 C4。理由：关联明细"
    assert prompts["object_role_selection"]["prompt"] == "3.1 对象角色 prompt"
    assert prompts["ontology_path_selection"]["raw_output"] == "选择 PR1：P1。理由：服务使用隧道。"
    assert prompts["coreference_selection"]["prompt"] == "3.4 指代消解 prompt"


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


def test_runtime_results_ontology_profile_prefers_newer_submission_over_stale_failure(monkeypatch, tmp_path: Path):
    testing_dir = tmp_path / "testing"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(tmp_path / "repair"))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_CGA_TRACE_PROFILE", "ontology")
    ontology_snapshot = json.dumps({"schema_version": "cga_trace_v2", "trace_profile": "ontology"}, ensure_ascii=False)
    _write_json(testing_dir / "goldens" / "qa_ontology_retry.json", {"id": "qa_ontology_retry", "difficulty": "L1"})
    _write_json(
        testing_dir / "generation_failures" / "qa_ontology_retry__old-run.json",
        {
            "id": "qa_ontology_retry",
            "question": "旧失败",
            "generation_run_id": "old-run",
            "generation_status": "service_failed",
            "failure_reason": "semantic_contract_unaligned",
            "input_prompt_snapshot": ontology_snapshot,
            "received_at": "2026-05-20T12:43:00+00:00",
        },
    )
    _write_json(
        testing_dir / "submissions" / "qa_ontology_retry.json",
        {
            "id": "qa_ontology_retry",
            "attempt_no": 3,
            "question": "最新生成",
            "generation_run_id": "new-run",
            "generated_cypher": "MATCH (s:Service) RETURN s.name",
            "input_prompt_snapshot": ontology_snapshot,
            "generation_status": "generated",
            "state": "passed",
            "received_at": "2026-05-20T12:47:00+00:00",
            "updated_at": "2026-05-20T12:47:01+00:00",
        },
    )

    from console.runtime_console.app.main import create_app

    client = TestClient(create_app())

    payload = client.get("/api/v1/tasks/qa_ontology_retry").json()

    generator = payload["pipeline"]["cypher_generator_agent"]
    assert generator["generation_status"] == "generated"
    assert generator["generation_run_id"] == "new-run"
    assert generator["generated_cypher"] == "MATCH (s:Service) RETURN s.name"
    assert generator["failure_reason"] is None


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


def test_runtime_results_does_not_bind_repair_analysis_by_ticket_id_without_submission_analysis_id(monkeypatch, tmp_path: Path):
    testing_dir = tmp_path / "testing"
    repair_dir = tmp_path / "repair"
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_TESTING_DATA_DIR", str(testing_dir))
    monkeypatch.setenv("RUNTIME_RESULTS_SERVICE_REPAIR_DATA_DIR", str(repair_dir))
    _write_json(testing_dir / "goldens" / "qa_ticket_bound.json", {"id": "qa_ticket_bound", "difficulty": "L4"})
    _write_json(
        testing_dir / "submissions" / "qa_ticket_bound.json",
        {
            "id": "qa_ticket_bound",
            "attempt_no": 3,
            "question": "查询缺少 repair response analysis_id 的样本",
            "generation_run_id": "run-ticket-bound",
            "generated_cypher": "MATCH (n) RETURN n",
            "input_prompt_snapshot": "generator prompt",
            "generation_status": "generated",
            "state": "issue_ticket_created",
            "issue_ticket_id": "ticket-qa_ticket_bound-attempt-3",
            "repair_response": None,
            "updated_at": "2026-04-26T09:03:00+00:00",
        },
    )
    _write_json(
        repair_dir / "analyses" / "analysis-ticket-qa_ticket_bound-attempt-3.json",
        {
            "analysis_id": "analysis-ticket-qa_ticket_bound-attempt-3",
            "ticket_id": "ticket-qa_ticket_bound-attempt-3",
            "id": "qa_ticket_bound",
            "status": "applied",
            "prompt_snapshot": "repair prompt",
            "system_prompt_snapshot": "repair system",
            "user_prompt_snapshot": "repair user",
            "raw_output": "{\"repairable\": true}",
            "knowledge_repair_request": {
                "id": "qa_ticket_bound",
                "suggestion": "补充当前 ticket 的修复建议。",
                "knowledge_types": ["few_shot"],
            },
            "knowledge_agent_response": {
                "status": "ok",
                "redispatch": {
                    "status": "skipped",
                    "dispatch": {
                        "status": "skipped",
                        "reason": "knowledge_agent_no_longer_redispatches_qa",
                    },
                },
                "agent_run": {
                    "decision": {
                        "action": "human_review",
                        "reason": "Converted legacy repair apply request into an agent review run.",
                    },
                },
            },
            "confidence": 0.8,
            "rationale": "current ticket rationale",
            "primary_knowledge_type": "few_shot",
            "secondary_knowledge_types": [],
            "diagnosis_context_summary": {},
            "applied": True,
            "created_at": "2026-04-26T09:04:00+00:00",
            "applied_at": "2026-04-26T09:04:01+00:00",
        },
    )

    from console.runtime_console.app.main import create_app

    client = TestClient(create_app())

    response = client.get("/api/v1/tasks/qa_ticket_bound")

    assert response.status_code == 200
    repair = response.json()["pipeline"]["repair_agent"]
    assert repair["analysis_id"] is None
    assert repair["issue_ticket_id"] == "ticket-qa_ticket_bound-attempt-3"
    assert repair["llm_prompt_markdown"] == ""
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
