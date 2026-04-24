from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from services.query_generator_agent.app.clients import (
    CypherLLMClient,
    OpenAICompatibleCypherGenerator,
)
from services.query_generator_agent.app.config import Settings as QueryGeneratorSettings
from services.repair_agent.app.config import Settings as RepairServiceSettings
from services.testing_agent.app.clients import LLMEvaluationClient
from services.testing_agent.app.config import Settings as TestingServiceSettings


def test_query_generator_requires_complete_llm_configuration(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CYPHER_GENERATOR_AGENT_LLM_ENABLED", raising=False)
    monkeypatch.delenv("CYPHER_GENERATOR_AGENT_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("CYPHER_GENERATOR_AGENT_LLM_API_KEY", raising=False)
    monkeypatch.delenv("CYPHER_GENERATOR_AGENT_LLM_MODEL", raising=False)

    with pytest.raises(ValidationError):
        QueryGeneratorSettings(_env_file=None)


def test_testing_service_requires_complete_llm_configuration(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("TESTING_SERVICE_LLM_ENABLED", raising=False)
    monkeypatch.delenv("TESTING_SERVICE_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("TESTING_SERVICE_LLM_API_KEY", raising=False)
    monkeypatch.delenv("TESTING_SERVICE_LLM_MODEL", raising=False)

    with pytest.raises(ValidationError):
        TestingServiceSettings(_env_file=None)


def test_repair_service_accepts_legacy_model_env_name(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REPAIR_SERVICE_LLM_ENABLED", "true")
    monkeypatch.setenv("REPAIR_SERVICE_LLM_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("REPAIR_SERVICE_LLM_API_KEY", "secret")
    monkeypatch.setenv("REPAIR_SERVICE_LLM_MODEL", "glm-5")
    monkeypatch.delenv("REPAIR_SERVICE_LLM_MODEL_NAME", raising=False)

    settings = RepairServiceSettings(_env_file=None)

    assert settings.llm_enabled is True
    assert settings.llm_model_name == "glm-5"


@pytest.mark.asyncio
async def test_query_generator_raises_when_llm_call_fails():
    llm_generator = AsyncMock(spec=OpenAICompatibleCypherGenerator)
    llm_generator.generate_from_prompt.side_effect = RuntimeError("llm offline")
    client = CypherLLMClient(llm_generator=llm_generator)

    with pytest.raises(RuntimeError, match="llm offline"):
        await client.generate_from_prompt(
            task_id="qa-001",
            question_text="统计网元数量",
            llm_prompt="Generate Cypher",
        )


@pytest.mark.asyncio
async def test_query_generator_logs_exact_llm_call_evidence(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    client = OpenAICompatibleCypherGenerator(
        base_url="https://example.com/v1",
        api_key="secret",
        model="qwen-test",
        timeout_seconds=5,
        temperature=0.1,
    )

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": '{"cypher":"MATCH (n) RETURN n"}'}}]
    }
    mock_response.headers = {"x-request-id": "req-qg-123"}

    mock_ctx = AsyncMock()
    mock_ctx.post.return_value = mock_response
    mock_ctx.__aenter__.return_value = mock_ctx
    mock_ctx.__aexit__.return_value = False
    monkeypatch.setattr("httpx.AsyncClient", lambda *args, **kwargs: mock_ctx)

    caplog.set_level(logging.INFO, logger="cypher_generator_agent")

    await client.generate_from_prompt(
        task_id="qa-001",
        question_text="统计网元数量",
        llm_prompt="Generate Cypher",
    )

    start = next(record for record in caplog.records if record.message.startswith("llm_call_started"))
    success = next(record for record in caplog.records if record.message.startswith("llm_call_succeeded"))

    assert start.qa_id == "qa-001"
    assert start.model == "qwen-test"
    assert start.target == "cypher_generator_agent.llm"
    assert "qa_id=qa-001" in start.message
    assert "model=qwen-test" in start.message
    assert success.qa_id == "qa-001"
    assert success.model == "qwen-test"
    assert success.target == "cypher_generator_agent.llm"
    assert success.request_id == "req-qg-123"
    assert success.elapsed_ms >= 0
    assert "request_id=req-qg-123" in success.message


@pytest.mark.asyncio
async def test_testing_service_raises_when_llm_evaluation_fails(monkeypatch: pytest.MonkeyPatch):
    client = LLMEvaluationClient(
        base_url="https://example.com/v1",
        api_key="secret",
        model="glm-4.5",
        timeout_seconds=5,
        temperature=0.1,
    )

    mock_ctx = AsyncMock()
    mock_ctx.post.side_effect = RuntimeError("evaluation endpoint unavailable")
    mock_ctx.__aenter__.return_value = mock_ctx
    mock_ctx.__aexit__.return_value = False
    monkeypatch.setattr("httpx.AsyncClient", lambda *args, **kwargs: mock_ctx)

    with pytest.raises(RuntimeError, match="evaluation endpoint unavailable"):
        await client.evaluate(
            question="test",
            expected_cypher="MATCH (n) RETURN n",
            expected_answer=[],
            actual_cypher="MATCH (n) RETURN n",
            actual_result=[],
            rule_based_verdict="fail",
            rule_based_dimensions={"result_correctness": "fail", "question_alignment": "fail"},
        )


@pytest.mark.asyncio
async def test_testing_service_logs_exact_llm_evaluation_evidence(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    client = LLMEvaluationClient(
        base_url="https://example.com/v1",
        api_key="secret",
        model="glm-5",
        timeout_seconds=5,
        temperature=0.1,
    )

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"result_correctness":"pass","question_alignment":"pass","reasoning":"ok","confidence":0.9}'
                    )
                }
            }
        ]
    }
    mock_response.headers = {"request-id": "req-test-456"}

    mock_ctx = AsyncMock()
    mock_ctx.post.return_value = mock_response
    mock_ctx.__aenter__.return_value = mock_ctx
    mock_ctx.__aexit__.return_value = False
    monkeypatch.setattr("httpx.AsyncClient", lambda *args, **kwargs: mock_ctx)

    caplog.set_level(logging.INFO, logger="testing_service")

    await client.evaluate(
        qa_id="qa-002",
        question="test",
        expected_cypher="MATCH (n) RETURN n",
        expected_answer=[],
        actual_cypher="MATCH (n) RETURN n",
        actual_result=[],
        rule_based_verdict="fail",
        rule_based_dimensions={"result_correctness": "fail", "question_alignment": "fail"},
    )

    start = next(record for record in caplog.records if record.message.startswith("llm_call_started"))
    success = next(record for record in caplog.records if record.message.startswith("llm_call_succeeded"))

    assert start.qa_id == "qa-002"
    assert start.model == "glm-5"
    assert start.target == "testing.llm_evaluation"
    assert "qa_id=qa-002" in start.message
    assert "model=glm-5" in start.message
    assert success.qa_id == "qa-002"
    assert success.request_id == "req-test-456"
    assert success.elapsed_ms >= 0
    assert "request_id=req-test-456" in success.message
