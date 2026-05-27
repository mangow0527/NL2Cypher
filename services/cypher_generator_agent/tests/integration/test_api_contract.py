from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.cypher_generator_agent.app.api.main import parse_semantics
from services.cypher_generator_agent.app.api.models import (
    CgaGenerationNonSuccessReport,
    GeneratedCypherSubmissionRequest,
    SemanticParseRequest,
)
from services.cypher_generator_agent.app.api.service import (
    CypherGeneratorAgentService,
    build_testing_agent_payload,
)
from services.cypher_generator_agent.app.core.result import GenerationOutput


def test_generated_output_requires_non_empty_cypher_dsl_and_trace() -> None:
    output = GenerationOutput(
        status="generated",
        cypher="MATCH (ne:NetworkElement) RETURN ne.id AS id",
        dsl={"schema_version": "restricted_query_dsl_v1", "query": {}},
        trace={"schema_version": "cga_graph_trace_v1", "stages": []},
    )

    assert output.status == "generated"

    with pytest.raises(ValidationError, match="generated requires non-empty cypher"):
        GenerationOutput(
            status="generated",
            cypher="",
            dsl={"schema_version": "restricted_query_dsl_v1", "query": {}},
            trace={"schema_version": "cga_graph_trace_v1", "stages": []},
        )


def test_generation_failed_output_requires_failure_reason() -> None:
    output = GenerationOutput(
        status="generation_failed",
        failure={"reason": "cypher_syntax_invalid", "message": "parser rejected generated query"},
        trace={"schema_version": "cga_graph_trace_v1", "stages": []},
    )

    assert output.failure is not None
    assert output.failure.reason == "cypher_syntax_invalid"

    with pytest.raises(ValidationError, match="generation_failed requires failure"):
        GenerationOutput(status="generation_failed", trace={"schema_version": "cga_graph_trace_v1", "stages": []})


def test_clarification_required_output_requires_clarification() -> None:
    output = GenerationOutput(
        status="clarification_required",
        clarification={"question": "Which service tier should be queried?"},
        trace={"schema_version": "cga_graph_trace_v1", "stages": []},
    )

    assert output.clarification is not None
    assert output.clarification.question == "Which service tier should be queried?"

    with pytest.raises(ValidationError, match="clarification_required requires clarification"):
        GenerationOutput(status="clarification_required", trace={"schema_version": "cga_graph_trace_v1", "stages": []})


def test_unsupported_query_shape_requires_unsupported_reason() -> None:
    output = GenerationOutput(
        status="unsupported_query_shape",
        failure={"reason": "unsupported_query_shape", "suggested_rewrites": ["Ask for a single service path."]},
        trace={"schema_version": "cga_graph_trace_v1", "stages": []},
    )

    assert output.failure is not None
    assert output.failure.reason == "unsupported_query_shape"

    with pytest.raises(ValidationError, match="unsupported_query_shape requires failure"):
        GenerationOutput(status="unsupported_query_shape", trace={"schema_version": "cga_graph_trace_v1", "stages": []})

    with pytest.raises(ValidationError, match="unsupported_query_shape requires unsupported_query_shape reason"):
        GenerationOutput(
            status="unsupported_query_shape",
            failure={"reason": "literal_unresolved", "suggested_rewrites": ["Use a known service ID."]},
            trace={"trace_schema_version": "cga_graph_trace_v1", "stages": []},
        )


def test_non_success_output_rejects_empty_cypher_placeholder() -> None:
    with pytest.raises(ValidationError, match="non-generated outputs must not include cypher"):
        GenerationOutput(
            status="unsupported_query_shape",
            cypher="",
            failure={"reason": "unsupported_query_shape"},
            trace={"schema_version": "cga_graph_trace_v1", "stages": []},
        )


def test_testing_agent_submission_contract_separates_generated_and_non_success_payloads() -> None:
    generated = GeneratedCypherSubmissionRequest(
        id="qa-1",
        question="query devices",
        generation_run_id="run-1",
        generated_cypher="MATCH (ne:NetworkElement) RETURN ne.id AS id",
        input_prompt_snapshot="{}",
    )
    non_success = CgaGenerationNonSuccessReport(
        id="qa-2",
        question="query every impossible thing",
        generation_run_id="run-2",
        generation_status="unsupported_query_shape",
        failure_reason="unsupported_query_shape",
        input_prompt_snapshot="{}",
        gate_passed=False,
    )

    assert generated.generation_status == "generated"
    assert non_success.generation_status == "unsupported_query_shape"
    assert not hasattr(generated, "gate_passed")


def test_testing_agent_payload_adapter_maps_generation_output_statuses() -> None:
    generated = GenerationOutput(
        status="generated",
        cypher="MATCH (ne:NetworkElement) RETURN ne.id AS id",
        dsl={"schema_version": "restricted_query_dsl_v1", "query": {}},
        trace={"trace_schema_version": "cga_graph_trace_v1", "stages": []},
    )
    non_success = GenerationOutput(
        status="unsupported_query_shape",
        failure={"reason": "unsupported_query_shape", "message": "Graph algorithm is outside DSL v1."},
        trace={"trace_schema_version": "cga_graph_trace_v1", "stages": []},
    )

    generated_payload = build_testing_agent_payload(
        qa_id="qa-generated",
        question="query devices",
        generation_run_id="run-generated",
        output=generated,
    )
    non_success_payload = build_testing_agent_payload(
        qa_id="qa-unsupported",
        question="query shortest path",
        generation_run_id="run-unsupported",
        output=non_success,
    )

    assert isinstance(generated_payload, GeneratedCypherSubmissionRequest)
    assert generated_payload.generated_cypher == "MATCH (ne:NetworkElement) RETURN ne.id AS id"
    assert isinstance(non_success_payload, CgaGenerationNonSuccessReport)
    assert non_success_payload.generation_status == "unsupported_query_shape"
    assert non_success_payload.failure_reason == "unsupported_query_shape"
    assert non_success_payload.parsed_cypher is None


@pytest.mark.asyncio
async def test_service_can_submit_non_success_generation_output_to_testing_agent() -> None:
    class CaptureTestingClient:
        def __init__(self) -> None:
            self.generated = None
            self.non_success = None

        async def submit(self, payload):
            self.generated = payload
            return {"accepted": True}

        async def submit_generation_failure(self, payload):
            self.non_success = payload
            return {"accepted": True}

    client = CaptureTestingClient()
    service = CypherGeneratorAgentService(testing_client=client)
    output = GenerationOutput(
        status="unsupported_query_shape",
        failure={"reason": "unsupported_query_shape", "message": "Graph algorithm is outside DSL v1."},
        trace={"trace_schema_version": "cga_graph_trace_v1", "stages": []},
    )

    await service.submit_generation_output(
        qa_id="qa-unsupported",
        question="query shortest path",
        generation_run_id="run-unsupported",
        output=output,
    )

    assert client.generated is None
    assert client.non_success is not None
    assert client.non_success.generation_status == "unsupported_query_shape"


@pytest.mark.asyncio
async def test_semantic_parse_returns_graph_trace_skeleton_without_empty_success_cypher() -> None:
    result = await parse_semantics(
        SemanticParseRequest(id="qa-osi-2", question="查询端口信息", generation_run_id="run-osi-2")
    )

    assert result["status"] == "unsupported_query_shape"
    assert "cypher" not in result
    assert result["failure"]["reason"] == "unsupported_query_shape"
    assert result["trace"] == {
        "trace_schema_version": "cga_graph_trace_v1",
        "trace_id": "run-osi-2",
        "question_id": "qa-osi-2",
        "generation_run_id": "run-osi-2",
        "source_question": "查询端口信息",
        "final_status": "unsupported_query_shape",
        "semantic_model": {},
        "stages": [],
        "final_outputs": {
            "failure": {
                "reason": "unsupported_query_shape",
                "message": "Graph-native Cypher generation is not implemented in the IR-00 stub.",
                "suggested_rewrites": [],
            },
            "user_visible_notices": [],
        },
    }
