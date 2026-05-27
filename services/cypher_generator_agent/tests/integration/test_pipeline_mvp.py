from __future__ import annotations

import pytest

from services.cypher_generator_agent.app.api.main import parse_semantics
from services.cypher_generator_agent.app.api.models import SemanticParseRequest
from services.cypher_generator_agent.app.core import pipeline as pipeline_module
from services.cypher_generator_agent.app.core.pipeline import run_pipeline
from services.cypher_generator_agent.app.core.result import ClarificationRequest
from services.cypher_generator_agent.app.decomposition.models import QuestionDecompositionClarification


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

    assert output.status == "clarification_required"
    assert output.cypher is None
    assert output.dsl is None
    assert output.failure is None
    assert output.clarification is not None
    assert "收入" in output.clarification.question
    assert output.trace["final_outputs"]["clarification"]["question"] == output.clarification.question
    assert output.trace["final_outputs"]["cypher"] is None
    assert output.trace["final_outputs"]["dsl"] is None
    assert _stage_names(output.trace)[-3:] == ["semantic_validator", "repair_controller", "output"]


def test_unsupported_query_shape_from_validator_returns_unsupported_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unsupported_understanding(
        decomposition: dict[str, object],
        literal_results: list[object],
    ) -> dict[str, object]:
        return {
            "query_shape": "shortest_path",
            "selected_vertices": ["Service"],
            "projection": [{"semantic_type": "vertex", "name": "Service"}],
        }

    monkeypatch.setattr(pipeline_module, "_mock_understand", unsupported_understanding)

    output = run_pipeline(
        question="Gold 服务使用了哪些隧道",
        qa_id="unsupported-shape",
        generation_run_id="run-unsupported-shape",
    )

    assert output.status == "unsupported_query_shape"
    assert output.cypher is None
    assert output.dsl is None
    assert output.failure is not None
    assert output.failure.reason == "unsupported_query_shape"
    assert _stage_names(output.trace)[-3:] == ["semantic_validator", "repair_controller", "output"]


def test_unresolved_literal_stops_before_dsl_or_cypher_generation() -> None:
    output = run_pipeline(
        question="Platinum 服务使用了哪些隧道",
        qa_id="literal-unresolved",
        generation_run_id="run-literal-unresolved",
    )

    assert output.status == "clarification_required"
    assert output.cypher is None
    assert output.dsl is None
    assert output.failure is None
    assert output.clarification is not None
    assert "Platinum" in output.clarification.question
    assert _stage_names(output.trace) == [
        "graph_model_loader",
        "question_decomposer",
        "candidate_retrieval",
        "literal_resolver",
        "repair_controller",
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
    assert _stage_names(output.trace)[-3:] == ["cypher_self_validation", "repair_controller", "output"]
    self_validation_stage = output.trace["stages"][-3]
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


def test_decomposer_clarification_outcome_short_circuits_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def clarification_decompose(question: str) -> QuestionDecompositionClarification:
        return QuestionDecompositionClarification(
            original_question=question,
            clarification=ClarificationRequest(question="请说明“它”指的是哪个设备或服务。"),
            missing_referents=["它"],
        )

    monkeypatch.setattr(pipeline_module, "_mock_decompose", clarification_decompose)

    output = run_pipeline(
        question="它最近 down 了吗",
        qa_id="decomposer-clarification",
        generation_run_id="run-decomposer-clarification",
    )

    assert output.status == "clarification_required"
    assert output.cypher is None
    assert output.dsl is None
    assert output.clarification is not None
    assert output.clarification.question == "请说明“它”指的是哪个设备或服务。"
    assert _stage_names(output.trace) == ["graph_model_loader", "question_decomposer", "output"]


def test_grounded_understanding_schema_output_is_converted_before_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def grounded_schema_understanding(
        decomposition: dict[str, object],
        literal_results: list[object],
    ) -> dict[str, object]:
        return {
            "schema_version": "grounded_understanding_v1",
            "status": "grounded",
            "query_shape": "single_hop",
            "selected_bindings": [
                _grounded_binding("source", "vertex", "Service"),
                _grounded_binding("target", "vertex", "Tunnel"),
                _grounded_binding("relation", "edge", "SERVICE_USES_TUNNEL", direction="forward"),
                _grounded_binding(
                    "filter_property",
                    "property",
                    "Service.quality_of_service",
                    semantic_name="quality_of_service",
                    owner="Service",
                ),
            ],
            "selected_literals": [
                result.model_dump(mode="json")
                for result in literal_results
            ],
            "filters": [
                {
                    "owner": "Service",
                    "property": "quality_of_service",
                    "operator": "=",
                    "raw_literal": "Gold",
                }
            ],
            "projection": [{"semantic_type": "vertex", "name": "Tunnel"}],
            "coverage": {
                "substantive_terms": {
                    "total": 4,
                    "covered": 4,
                    "uncovered": [],
                }
            },
            "unsupported": None,
            "confidence": 0.93,
        }

    monkeypatch.setattr(pipeline_module, "_mock_understand", grounded_schema_understanding)

    output = run_pipeline(
        question="Gold 服务使用了哪些隧道",
        qa_id="grounded-schema",
        generation_run_id="run-grounded-schema",
    )

    assert output.status == "generated"
    assert output.cypher is not None
    assert "SERVICE_USES_TUNNEL" in output.cypher
    assert _stage_names(output.trace) == EXPECTED_STAGES


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


def _grounded_binding(
    role: str,
    semantic_type: str,
    semantic_id: str,
    *,
    semantic_name: str | None = None,
    owner: str | None = None,
    direction: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "role": role,
        "semantic_type": semantic_type,
        "candidate_id": f"{semantic_type}:{semantic_id}",
        "semantic_id": semantic_id,
        "semantic_name": semantic_name or semantic_id,
        "confidence": 0.95,
    }
    if owner is not None:
        payload["owner"] = owner
    if direction is not None:
        payload["direction"] = direction
    return payload
