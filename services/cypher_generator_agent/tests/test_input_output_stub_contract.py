from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.cypher_generator_agent.app.api.main import parse_semantics, recognize_intent
from services.cypher_generator_agent.app.api.models import (
    IntentRecognitionRequest,
    QAQuestionRequest,
    SemanticParseRequest,
)
from services.cypher_generator_agent.app.api.service import CypherGeneratorAgentService


SERVICE_ROOT = Path(__file__).resolve().parents[1]
GENERATED_NAMES = {"__pycache__", ".DS_Store"}


class _CaptureTestingClient:
    def __init__(self) -> None:
        self.submission = None
        self.failure = None

    async def submit(self, payload):
        self.submission = payload
        return {"ok": True}

    async def submit_generation_failure(self, payload):
        self.failure = payload
        return {"ok": True}


@pytest.mark.asyncio
async def test_ingest_question_preserves_io_contract_with_empty_generation_body() -> None:
    testing_client = _CaptureTestingClient()
    service = CypherGeneratorAgentService(testing_client=testing_client)

    result = await service.ingest_question(QAQuestionRequest(id="qa-osi-1", question="查询服务名称"))

    assert result.generation_status == "submitted_to_testing"
    assert result.generation_run_id
    assert testing_client.failure is None
    assert testing_client.submission is not None
    assert testing_client.submission.id == "qa-osi-1"
    assert testing_client.submission.question == "查询服务名称"
    assert testing_client.submission.generation_run_id == result.generation_run_id
    assert testing_client.submission.generated_cypher == ""

    snapshot = json.loads(testing_client.submission.input_prompt_snapshot)
    assert snapshot == {
        "schema_version": "cga_io_stub_v1",
        "trace_id": result.generation_run_id,
        "input": {"id": "qa-osi-1", "question": "查询服务名称"},
        "output": {"generated_cypher": ""},
        "internal_flow": {},
    }


@pytest.mark.asyncio
async def test_semantic_parse_returns_empty_io_skeleton() -> None:
    result = await parse_semantics(
        SemanticParseRequest(id="qa-osi-2", question="查询端口信息", generation_run_id="run-osi-2")
    )

    assert result == {
        "status": "generated",
        "cypher": "",
        "logical_plan": {},
        "trace": {
            "schema_version": "cga_io_stub_v1",
            "trace_id": "run-osi-2",
            "input": {"id": "qa-osi-2", "question": "查询端口信息"},
            "output": {"generated_cypher": ""},
            "internal_flow": {},
        },
    }


@pytest.mark.asyncio
async def test_intent_recognition_returns_empty_io_skeleton() -> None:
    result = await recognize_intent(IntentRecognitionRequest(question="查询业务状态"))

    assert result == {
        "status": "stubbed",
        "input": {"question": "查询业务状态"},
        "output": {"intent": {}},
        "internal_flow": {},
    }


def test_cypher_generator_agent_contains_only_io_stub_files() -> None:
    allowed_top_level = {"__init__.py", "app", "tests"}
    assert _source_names(SERVICE_ROOT) <= allowed_top_level

    allowed_app_children = {"__init__.py", "api", "infrastructure"}
    assert _source_names(SERVICE_ROOT / "app") <= allowed_app_children

    allowed_infrastructure_files = {"__init__.py", "clients.py", "config.py"}
    assert _source_names(SERVICE_ROOT / "app" / "infrastructure") <= allowed_infrastructure_files

    allowed_tests = {"test_input_output_stub_contract.py"}
    assert _source_names(SERVICE_ROOT / "tests") <= allowed_tests


def _source_names(path: Path) -> set[str]:
    return {child.name for child in path.iterdir() if child.name not in GENERATED_NAMES}
