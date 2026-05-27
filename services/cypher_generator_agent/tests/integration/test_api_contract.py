from __future__ import annotations

import json

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
    generated = _generated_output()
    non_success = _unsupported_output()

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
    generated_snapshot = json.loads(generated_payload.input_prompt_snapshot)
    assert generated_snapshot["final_status"] == "generated"
    assert generated_snapshot["final_outputs"] == {
        "dsl": {"schema_version": "restricted_query_dsl_v1", "query": {}},
        "cypher": "MATCH (ne:NetworkElement) RETURN ne.id AS id",
        "clarification": None,
        "user_visible_notices": [],
        "failure": None,
    }
    assert isinstance(non_success_payload, CgaGenerationNonSuccessReport)
    assert non_success_payload.generation_status == "unsupported_query_shape"
    assert non_success_payload.failure_reason == "unsupported_query_shape"
    assert non_success_payload.parsed_cypher is None
    non_success_snapshot = json.loads(non_success_payload.input_prompt_snapshot)
    assert non_success_snapshot["final_status"] == "unsupported_query_shape"
    assert non_success_snapshot["final_outputs"]["dsl"] is None
    assert non_success_snapshot["final_outputs"]["cypher"] is None
    assert non_success_snapshot["final_outputs"]["failure"]["reason"] == "unsupported_query_shape"


def test_testing_agent_payload_adapter_rejects_trace_status_mismatch() -> None:
    generated = _generated_output()
    generated.trace["final_status"] = "generation_failed"
    generated.trace["final_outputs"] = {
        "failure": {"reason": "coverage_failure", "message": "uncovered term"},
        "user_visible_notices": [],
    }

    with pytest.raises(ValueError, match="does not match output.status"):
        build_testing_agent_payload(
            qa_id="qa-generated",
            question="query devices",
            generation_run_id="run-generated",
            output=generated,
        )


def test_testing_agent_payload_adapter_rejects_forbidden_trace_payload() -> None:
    generated = _generated_output()
    generated.trace["final_outputs"]["dsl"]["db_connection"] = {"url": "bolt://secret"}

    with pytest.raises(ValidationError):
        build_testing_agent_payload(
            qa_id="qa-generated",
            question="query devices",
            generation_run_id="run-generated",
            output=generated,
        )


def test_testing_agent_payload_adapter_rejects_user_visible_notice_drift() -> None:
    generated = _generated_output()
    generated.trace["final_outputs"]["user_visible_notices"] = ["trace-only notice"]

    with pytest.raises(ValueError, match="user_visible_notices"):
        build_testing_agent_payload(
            qa_id="qa-generated",
            question="query devices",
            generation_run_id="run-generated",
            output=generated,
        )


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
    output = _unsupported_output()

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
    trace = result["trace"]
    assert trace["started_at"]
    assert trace["finished_at"]
    trace_without_timestamps = {key: value for key, value in trace.items() if key not in {"started_at", "finished_at"}}
    assert trace_without_timestamps == {
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


def _generated_output() -> GenerationOutput:
    cypher = "MATCH (ne:NetworkElement) RETURN ne.id AS id"
    dsl = {"schema_version": "restricted_query_dsl_v1", "query": {}}
    return GenerationOutput(
        status="generated",
        cypher=cypher,
        dsl=dsl,
        trace={
            **_trace_base(
                trace_id="trace-generated",
                qa_id="qa-generated",
                run_id="run-generated",
                question="query devices",
                status="generated",
            ),
            "final_outputs": {
                "dsl": dsl,
                "cypher": cypher,
                "user_visible_notices": [],
            },
        },
    )


def _unsupported_output() -> GenerationOutput:
    failure = {"reason": "unsupported_query_shape", "message": "Graph algorithm is outside DSL v1."}
    return GenerationOutput(
        status="unsupported_query_shape",
        failure=failure,
        trace={
            **_trace_base(
                trace_id="trace-unsupported",
                qa_id="qa-unsupported",
                run_id="run-unsupported",
                question="query shortest path",
                status="unsupported_query_shape",
            ),
            "final_outputs": {
                "failure": failure,
                "user_visible_notices": [],
            },
        },
    )


def _trace_base(*, trace_id: str, qa_id: str, run_id: str, question: str, status: str) -> dict[str, object]:
    return {
        "trace_schema_version": "cga_graph_trace_v1",
        "trace_id": trace_id,
        "question_id": qa_id,
        "generation_run_id": run_id,
        "source_question": question,
        "started_at": "2026-05-27T00:00:00+00:00",
        "finished_at": "2026-05-27T00:00:01+00:00",
        "final_status": status,
        "semantic_model": {},
        "stages": [],
    }
