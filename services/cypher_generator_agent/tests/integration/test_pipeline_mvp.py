from __future__ import annotations

import pytest

from services.cypher_generator_agent.app.api.main import parse_semantics
from services.cypher_generator_agent.app.api.models import SemanticParseRequest
from services.cypher_generator_agent.app.core.pipeline import run_pipeline


EXPECTED_STAGES = [
    "graph_model_loader",
    "question_decomposer",
    "candidate_retrieval",
    "literal_resolver",
    "grounded_understanding",
    "semantic_binder",
    "semantic_validator",
    "dsl_builder",
    "dsl_parser",
    "cypher_compiler",
    "cypher_self_validation",
    "output",
]


def test_gold_service_question_generates_single_hop_cypher() -> None:
    output = run_pipeline(
        question="Gold 服务使用了哪些隧道",
        qa_id="gq-001",
        generation_run_id="run-gq-001",
    )

    assert output.status == "generated"
    assert output.cypher is not None
    assert "MATCH (svc:Service)-[:SERVICE_USES_TUNNEL]->(tun:Tunnel)" in output.cypher
    assert "svc.quality_of_service = $quality_of_service" in output.cypher
    assert "RETURN tun.id AS tunnel_id" in output.cypher
    assert _compiler_parameters(output.trace)["quality_of_service"] == "GOLD"
    assert _stage_names(output.trace) == EXPECTED_STAGES
    assert "db_connection" not in _all_keys(output.trace)
    assert "execution_result" not in _all_keys(output.trace)


def test_tunnel_path_question_generates_named_path_pattern_cypher() -> None:
    output = run_pipeline(
        question="隧道 tun-mpls-001 经过哪些设备",
        qa_id="gq-003",
        generation_run_id="run-gq-003",
    )

    assert output.status == "generated"
    assert output.cypher is not None
    assert output.cypher == (
        "MATCH (t:Tunnel {id: $tunnel_id})-[p:PATH_THROUGH]->(ne:NetworkElement)\n"
        "RETURN ne AS device, p.hop_order AS hop\n"
        "ORDER BY p.hop_order ASC"
    )
    assert _compiler_parameters(output.trace) == {"tunnel_id": "tun-mpls-001"}
    assert output.dsl is not None
    assert output.dsl["query_shape"] == "named_path_pattern"
    assert output.dsl["operations"][0]["path_pattern_name"] == "tunnel_full_path"
    assert _stage_names(output.trace) == EXPECTED_STAGES


def test_coverage_failure_does_not_emit_cypher_or_dsl() -> None:
    output = run_pipeline(
        question="2024 年收入增长情况",
        qa_id="coverage-failure",
        generation_run_id="run-coverage-failure",
    )

    assert output.status in {"generation_failed", "unsupported_query_shape", "clarification_required"}
    assert output.cypher is None
    assert output.dsl is None
    assert output.failure is not None
    assert output.failure.reason == "coverage_failure"
    assert output.trace["final_outputs"]["cypher"] is None
    assert output.trace["final_outputs"]["dsl"] is None
    assert _stage_names(output.trace)[-2:] == ["semantic_validator", "output"]


def test_unresolved_literal_stops_before_dsl_or_cypher_generation() -> None:
    output = run_pipeline(
        question="Platinum 服务使用了哪些隧道",
        qa_id="literal-unresolved",
        generation_run_id="run-literal-unresolved",
    )

    assert output.status == "generation_failed"
    assert output.cypher is None
    assert output.dsl is None
    assert output.failure is not None
    assert output.failure.reason == "literal_unresolved"
    assert _stage_names(output.trace) == [
        "graph_model_loader",
        "question_decomposer",
        "candidate_retrieval",
        "literal_resolver",
        "output",
    ]


def test_self_validation_failure_records_self_validation_stage_without_final_cypher() -> None:
    output = run_pipeline(
        question="隧道 tun-mpls-001 经过哪些设备",
        qa_id="self-validation-failure",
        generation_run_id="run-self-validation-failure",
        _path_pattern_template_overrides_for_tests={
            "tunnel_full_path": (
                "MATCH (t:Tunnel {id: $tunnel_id})-[p:PATH_THROUGH]->(ne:NetworkElement)\n"
                "SET ne.name = 'bad'\n"
                "RETURN ne AS device, p.hop_order AS hop"
            )
        },
    )

    assert output.status == "generation_failed"
    assert output.cypher is None
    assert output.dsl is None
    assert output.failure is not None
    assert output.failure.reason == "cypher_readonly_violation"
    assert _stage_names(output.trace)[-2:] == ["cypher_self_validation", "output"]
    self_validation_stage = output.trace["stages"][-2]
    assert self_validation_stage["status"] == "failed"
    assert self_validation_stage["output_ref"]["value"]["valid"] is False


def test_model_loader_failure_returns_service_failure_envelope(tmp_path) -> None:
    output = run_pipeline(
        question="Gold 服务使用了哪些隧道",
        qa_id="model-loader-failure",
        generation_run_id="run-model-loader-failure",
        _model_path=tmp_path / "missing-model.yaml",
    )

    assert output.status == "service_failed"
    assert output.cypher is None
    assert output.dsl is None
    assert output.failure is not None
    assert output.failure.reason == "knowledge_context_unavailable"
    assert _stage_names(output.trace) == ["graph_model_loader", "output"]
    assert output.trace["stages"][0]["status"] == "failed"


@pytest.mark.asyncio
async def test_semantic_parse_api_uses_pipeline_for_happy_path() -> None:
    result = await parse_semantics(
        SemanticParseRequest(
            id="gq-001",
            question="Gold 服务使用了哪些隧道",
            generation_run_id="run-api-gq-001",
        )
    )

    assert result["status"] == "generated"
    assert "SERVICE_USES_TUNNEL" in result["cypher"]
    assert result["trace"]["final_status"] == "generated"
    assert _stage_names(result["trace"]) == EXPECTED_STAGES


def _stage_names(trace: dict[str, object]) -> list[str]:
    return [stage["stage"] for stage in trace["stages"]]


def _compiler_parameters(trace: dict[str, object]) -> dict[str, object]:
    for stage in trace["stages"]:
        if stage["stage"] == "cypher_compiler":
            return stage["output_ref"]["value"]["parameters"]
    raise AssertionError("missing cypher_compiler stage")


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for item in value.values():
            keys.update(_all_keys(item))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for item in value:
            keys.update(_all_keys(item))
        return keys
    return set()
