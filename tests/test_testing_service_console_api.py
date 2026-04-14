from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from shared.models import QAGoldenRequest, QueryQuestionResponse


def test_console_html_exposes_dual_tab_workspace(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("TESTING_SERVICE_DATA_DIR", str(tmp_path / "testing-data"))

    from services.testing_service.app.main import app

    client = TestClient(app)

    response = client.get("/console")

    assert response.status_code == 200
    assert "架构总览" in response.text
    assert "系统联调" in response.text
    assert "Architecture Overview" in response.text
    assert "System Integration Console" in response.text


def test_runtime_architecture_endpoint_returns_service_cards(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("TESTING_SERVICE_DATA_DIR", str(tmp_path / "testing-data"))

    from services.testing_service.app.main import app, validation_service

    validation_service.health_client.read_health = AsyncMock(return_value={"status": "ok"})

    client = TestClient(app)

    response = client.get("/api/v1/runtime/architecture")

    assert response.status_code == 200
    payload = response.json()
    assert payload["title_zh"] == "系统运行架构"
    assert payload["title_en"] == "System Runtime Architecture"
    assert [service["service_key"] for service in payload["services"]] == [
        "cgs",
        "testing_service",
        "krss",
        "knowledge_ops",
        "qa_generator",
    ]
    assert any(service["label_zh"] == "测试服务" for service in payload["services"])
    assert any(link["source"] == "cgs" and link["target"] == "knowledge_ops" for link in payload["links"])
    assert any(link["source"] == "testing_service" and link["target"] == "krss" for link in payload["links"])
    assert any(link["source"] == "krss" and link["target"] == "cgs" for link in payload["links"])
    assert any(link["source"] == "krss" and link["target"] == "knowledge_ops" for link in payload["links"])
    assert any(obj["object_key"] == "prompt_snapshot" for obj in payload["data_objects"])
    assert any(obj["object_key"] == "issue_ticket" for obj in payload["data_objects"])


def test_console_run_failure_path_returns_aggregated_trace(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("TESTING_SERVICE_DATA_DIR", str(tmp_path / "testing-data"))

    from services.testing_service.app.main import app, validation_service

    validation_service.health_client.read_health = AsyncMock(return_value={"status": "ok"})
    validation_service._is_service_online = AsyncMock(return_value=False)
    validation_service.repository.save_golden(
        QAGoldenRequest(
            id="qa-console-fail",
            cypher="MATCH (n:NetworkElement) RETURN n.id AS id, n.name AS name LIMIT 20",
            answer=[{"id": "non-matching-id", "name": "golden-only-device"}],
            difficulty="L3",
        )
    )
    validation_service._get_console_generation = AsyncMock(
        return_value=QueryQuestionResponse(
            id="qa-console-fail",
            generation_run_id="console-qa-console-fail",
            generation_status="generated",
            generated_cypher="MATCH (n:Device) RETURN n.id AS id, n.name AS name LIMIT 20",
            parse_summary="console_fallback_generation",
            guardrail_summary="passed",
            raw_output_snapshot='{"cypher":"MATCH (n:Device) RETURN n.id AS id, n.name AS name LIMIT 20"}',
            input_prompt_snapshot="Console runtime fallback prompt snapshot.",
        )
    )

    client = TestClient(app)

    response = client.post(
        "/api/v1/runtime/console-runs",
        json={"id": "qa-console-fail", "question": "查询失败样例"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "qa-console-fail"
    assert payload["question"] == "查询失败样例"
    assert payload["title_zh"] == "系统联调运行"
    assert payload["title_en"] == "System Integration Run"
    assert any(card["service_key"] == "testing_service" for card in payload["service_cards"])
    assert any(link["target"] == "krss" for link in payload["links"])
    assert payload["stages"]["query_generation"]["status"] in {"success", "failed"}
    assert payload["stages"]["evaluation"]["status"] in {"success", "failed"}
    assert payload["stages"]["knowledge_repair"]["status"] in {"success", "failed", "skipped"}
    assert payload["timeline"]
    assert "knowledge_repair" in payload["artifacts"]
    assert "submission" in payload["artifacts"]
    assert payload["artifacts"]["knowledge_repair"]["issue_ticket"] is not None
    assert payload["artifacts"]["knowledge_repair"]["krss_response"] is None
