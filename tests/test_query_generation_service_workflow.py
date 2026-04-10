from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.models import QAQuestionRequest
from services.query_generator_service.app import service as workflow_module
from services.query_generator_service.app.service import QueryWorkflowService


class TestCypherGenerationWorkflow:
    @pytest.mark.asyncio
    async def test_ingest_question_fetches_prompt_generates_and_submits(self):
        prompt_client = AsyncMock()
        prompt_client.fetch_prompt.return_value = "请生成一个 Cypher JSON"

        generator_client = AsyncMock()
        generator_client.generate_from_prompt.return_value = {
            "raw_output": '{"cypher":"MATCH (n:NetworkElement) RETURN n.name AS name LIMIT 5"}',
            "model_name": "test-model",
        }

        testing_client = AsyncMock()
        testing_client.submit.return_value = {"status": "waiting_for_golden"}

        repository = MagicMock()
        repository.next_generation_run_id.return_value = "run-001"
        repository.get_generation_run.return_value = None

        svc = QueryWorkflowService(
            prompt_client=prompt_client,
            generator_client=generator_client,
            testing_client=testing_client,
            repository=repository,
        )

        result = await svc.ingest_question(QAQuestionRequest(id="qa-001", question="查询设备名称"))

        prompt_client.fetch_prompt.assert_awaited_once_with(task_id="qa-001", question_text="查询设备名称")
        generator_client.generate_from_prompt.assert_awaited_once_with(
            task_id="qa-001",
            question_text="查询设备名称",
            generation_prompt="请生成一个 Cypher JSON",
        )
        testing_client.submit.assert_awaited_once()
        submission_payload = testing_client.submit.await_args.kwargs["payload"]
        assert submission_payload.id == "qa-001"
        assert submission_payload.question == "查询设备名称"
        assert submission_payload.generated_cypher.startswith("MATCH")
        assert submission_payload.input_prompt_snapshot == "请生成一个 Cypher JSON"
        assert result.generation_run_id == "run-001"
        assert result.generation_status == "submitted_to_testing"
        assert result.input_prompt_snapshot == "请生成一个 Cypher JSON"
        assert result.parse_summary == "parsed_json"
        assert "MATCH (n:NetworkElement)" in result.raw_output_snapshot

    @pytest.mark.asyncio
    async def test_prompt_fetch_failure_returns_processing_failure(self):
        prompt_client = AsyncMock()
        prompt_client.fetch_prompt.side_effect = RuntimeError("knowledge ops offline")

        generator_client = AsyncMock()
        testing_client = AsyncMock()

        repository = MagicMock()
        repository.next_generation_run_id.return_value = "run-002"

        svc = QueryWorkflowService(
            prompt_client=prompt_client,
            generator_client=generator_client,
            testing_client=testing_client,
            repository=repository,
        )

        result = await svc.ingest_question(QAQuestionRequest(id="qa-002", question="查询隧道"))

        generator_client.generate_from_prompt.assert_not_called()
        testing_client.submit.assert_not_called()
        assert result.generation_status == "prompt_fetch_failed"
        assert result.failure_stage == "prompt_fetch"
        assert "knowledge ops offline" in (result.failure_reason_summary or "")

    def test_get_prompt_snapshot_returns_id_and_prompt(self):
        prompt_client = AsyncMock()
        generator_client = AsyncMock()
        testing_client = AsyncMock()
        repository = MagicMock()
        repository.get_generation_prompt_snapshot.return_value = {
            "id": "qa-003",
            "input_prompt_snapshot": "请仅返回 JSON，其中包含 cypher 字段",
        }

        svc = QueryWorkflowService(
            prompt_client=prompt_client,
            generator_client=generator_client,
            testing_client=testing_client,
            repository=repository,
        )

        result = svc.get_prompt_snapshot("qa-003")

        repository.get_generation_prompt_snapshot.assert_called_once_with("qa-003")
        assert result is not None
        assert result.id == "qa-003"
        assert result.input_prompt_snapshot == "请仅返回 JSON，其中包含 cypher 字段"

    @pytest.mark.asyncio
    async def test_tugraph_connection_is_reported_as_unsupported(self):
        result = await workflow_module.test_tugraph_connection()

        assert result == {
            "supported": False,
            "detail": "Cypher Generation Service no longer executes TuGraph queries directly.",
        }
