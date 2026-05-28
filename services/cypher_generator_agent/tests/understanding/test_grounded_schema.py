from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from services.cypher_generator_agent.app.binding import SemanticBinder
from services.cypher_generator_agent.app.decomposition.models import QuestionDecomposition
from services.cypher_generator_agent.app.literals.models import LiteralEvidence, LiteralResolverResult
from services.cypher_generator_agent.app.retrieval.models import (
    CandidateEvidence,
    CandidateRetrievalResult,
    SemanticCandidate,
)
from services.cypher_generator_agent.app.semantic_model.loader import load_graph_semantic_model
from services.cypher_generator_agent.app.understanding import (
    GROUNDED_UNDERSTANDING_SCHEMA_VERSION,
    GroundedUnderstanding,
    GroundedUnderstandingFailure,
    GroundedUnderstandingSelector,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "network_topology_graph_model.yaml"
)


class FakeProviderUnavailable(RuntimeError):
    pass


class FakeGroundedLLMClient:
    provider = "fake-grounded-llm"

    def __init__(
        self,
        responses: list[Mapping[str, Any]] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def generate_structured(
        self,
        *,
        prompt: str,
        schema_name: str,
        schema: Mapping[str, Any],
        attempt: int,
    ) -> Mapping[str, Any]:
        self.calls.append(
            {
                "prompt": prompt,
                "schema_name": schema_name,
                "schema": schema,
                "attempt": attempt,
            }
        )
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


def test_selecting_service_uses_tunnel_yields_binder_compatible_payload() -> None:
    literal_result = _gold_literal_result()
    candidates = _gold_candidates()
    client = FakeGroundedLLMClient(
        [
            {
                "schema_version": "grounded_understanding_v1",
                "status": "grounded",
                "query_shape": "single_hop",
                "selected_bindings": [
                    _binding("source", "vertex", "Service"),
                    _binding("target", "vertex", "Tunnel"),
                    _binding("relation", "edge", "SERVICE_USES_TUNNEL", direction="forward"),
                    _binding(
                        "filter_property",
                        "property",
                        "Service.quality_of_service",
                        semantic_name="quality_of_service",
                        owner="Service",
                    ),
                ],
                "selected_literals": [literal_result.model_dump()],
                "filters": [
                    {
                        "owner": "Service",
                        "property": "quality_of_service",
                        "operator": "=",
                        "raw_literal": "Gold",
                    }
                ],
                "projection": [{"semantic_type": "vertex", "name": "Tunnel"}],
                "limit": 50,
                "coverage": _coverage(["Gold", "服务", "使用", "隧道"]),
                "unsupported": None,
                "confidence": 0.93,
            }
        ]
    )

    result = GroundedUnderstandingSelector(client).select(
        question_decomposition=_gold_decomposition(),
        candidates=candidates,
        literal_results=[literal_result],
    )

    assert isinstance(result, GroundedUnderstanding)
    assert result.schema_version == "grounded_understanding_v1"
    assert result.status == "grounded"
    assert result.coverage.substantive_terms.uncovered == []
    assert result.unsupported is None
    assert result.confidence == 0.93
    assert [call["schema_name"] for call in client.calls] == [GROUNDED_UNDERSTANDING_SCHEMA_VERSION]
    assert "vertex:Service" in client.calls[0]["prompt"]
    assert "literal_resolver_result_v1" in client.calls[0]["prompt"]
    assert "你是图原生 Cypher 生成流水线中的语义落地理解选择器" in client.calls[0]["prompt"]
    assert "只能从 top_candidates 中按 candidate_id 选择" in client.calls[0]["prompt"]
    assert "You are the Grounded Understanding selector" not in client.calls[0]["prompt"]

    binder = SemanticBinder(load_graph_semantic_model(FIXTURE_PATH).registry)
    plan = binder.bind(result.to_binder_payload(), candidates=candidates)

    assert plan.query_shape == "single_hop_traversal"
    assert [binding.name for binding in plan.vertex_bindings] == ["Service", "Tunnel"]
    assert [binding.name for binding in plan.edge_bindings] == ["SERVICE_USES_TUNNEL"]
    assert [(binding.owner, binding.name) for binding in plan.property_bindings] == [
        ("Service", "quality_of_service")
    ]
    assert plan.filters[0].value == "GOLD"
    assert plan.projection == [{"semantic_type": "vertex", "name": "Tunnel"}]


def test_schema_violation_retries_then_returns_valid_grounding() -> None:
    client = FakeGroundedLLMClient(
        [
            {"schema_version": "grounded_understanding_v1", "query_shape": "single_hop"},
            _valid_minimal_payload(),
        ]
    )

    result = GroundedUnderstandingSelector(client).select(
        question_decomposition=_gold_decomposition(),
        candidates=_gold_candidates(),
        literal_results=[],
    )

    assert isinstance(result, GroundedUnderstanding)
    assert [call["attempt"] for call in client.calls] == [1, 2]


def test_schema_violation_stops_after_initial_attempt_plus_two_retries() -> None:
    client = FakeGroundedLLMClient(
        [
            {"schema_version": "grounded_understanding_v1", "query_shape": "single_hop"},
            {"schema_version": "grounded_understanding_v1", "query_shape": "single_hop"},
            {"schema_version": "grounded_understanding_v1", "query_shape": "single_hop"},
        ]
    )

    result = GroundedUnderstandingSelector(client).select(
        question_decomposition=_gold_decomposition(),
        candidates=_gold_candidates(),
        literal_results=[],
    )

    assert isinstance(result, GroundedUnderstandingFailure)
    assert result.status == "generation_failed"
    assert result.reason == "grounded_understanding_schema_invalid"
    assert result.provider == "fake-grounded-llm"
    assert result.error_type == "ValidationError"
    assert result.attempts == 3
    assert result.retry_count == 2
    assert [call["attempt"] for call in client.calls] == [1, 2, 3]


def test_provider_unavailable_returns_service_failed_without_deterministic_fallback() -> None:
    client = FakeGroundedLLMClient(error=FakeProviderUnavailable("provider unavailable"))

    result = GroundedUnderstandingSelector(client).select(
        question_decomposition=_gold_decomposition(),
        candidates=_gold_candidates(),
        literal_results=[],
    )

    assert isinstance(result, GroundedUnderstandingFailure)
    assert result.status == "service_failed"
    assert result.reason == "model_invocation_failed"
    assert result.provider == "fake-grounded-llm"
    assert result.error_type == "FakeProviderUnavailable"
    assert result.attempts == 1
    assert result.retry_count == 0
    assert len(client.calls) == 1


def test_unsupported_output_preserves_coverage_gap_without_binder_payload() -> None:
    client = FakeGroundedLLMClient(
        [
            {
                "schema_version": "grounded_understanding_v1",
                "status": "unsupported_query_shape",
                "query_shape": "unsupported",
                "selected_bindings": [],
                "selected_literals": [],
                "filters": [],
                "projection": [],
                "coverage": _coverage([], uncovered=["收入", "增长"]),
                "unsupported": {
                    "reason_code": "coverage_gap_unknown_metric",
                    "message": "No revenue or growth metric exists in the graph semantic model.",
                },
                "confidence": 0.88,
            }
        ]
    )

    result = GroundedUnderstandingSelector(client).select(
        question_decomposition={
            "schema_version": "question_decomposition_v1",
            "result_type": "decomposition",
            "intent_type": "compare",
            "original_question": "收入增长情况",
            "target_concepts": ["收入"],
            "relation_phrases": ["增长"],
            "literal_candidates": [],
            "substantive_terms": ["收入", "增长"],
            "stopword_terms": [],
            "modality_terms": [],
            "time_terms": [],
            "unparsed_terms": [],
            "output_shape": "unknown",
        },
        candidates=CandidateRetrievalResult(candidates=[]),
        literal_results=[],
    )

    assert isinstance(result, GroundedUnderstanding)
    assert result.status == "unsupported_query_shape"
    assert result.unsupported is not None
    assert result.unsupported.reason_code == "coverage_gap_unknown_metric"
    assert result.coverage.substantive_terms.uncovered == ["收入", "增长"]


def _valid_minimal_payload() -> dict[str, Any]:
    return {
        "schema_version": "grounded_understanding_v1",
        "status": "grounded",
        "query_shape": "lookup",
        "selected_bindings": [_binding("target", "vertex", "Service")],
        "selected_literals": [],
        "filters": [],
        "projection": [],
        "coverage": _coverage(["服务"]),
        "unsupported": None,
        "confidence": 0.9,
    }


def _gold_decomposition() -> QuestionDecomposition:
    return QuestionDecomposition(
        result_type="decomposition",
        intent_type="list",
        original_question="Gold 服务使用了哪些隧道",
        target_concepts=["服务", "隧道"],
        relation_phrases=["使用"],
        literal_candidates=[
            {"text": "Gold", "kind_hint": "enum_or_name", "attached_to": "服务"}
        ],
        substantive_terms=["Gold", "服务", "使用", "隧道"],
        stopword_terms=[],
        modality_terms=[],
        time_terms=[],
        unparsed_terms=[],
        output_shape="rows",
    )


def _gold_literal_result() -> LiteralResolverResult:
    return LiteralResolverResult(
        raw_literal="Gold",
        resolved=True,
        resolved_value="GOLD",
        normalized_value="GOLD",
        match_type="value_synonym",
        confidence=0.98,
        expected_vertex="Service",
        expected_property="quality_of_service",
        evidence=[
            LiteralEvidence(
                source="property.value_synonyms",
                matched="Gold",
                target="GOLD",
            )
        ],
    )


def _gold_candidates() -> CandidateRetrievalResult:
    return CandidateRetrievalResult(
        candidates=[
            _candidate("vertex", "Service"),
            _candidate("vertex", "Tunnel"),
            _candidate("edge", "SERVICE_USES_TUNNEL"),
            _candidate(
                "property",
                "Service.quality_of_service",
                owner="Service",
                semantic_name="quality_of_service",
            ),
        ]
    )


def _binding(
    role: str,
    semantic_type: str,
    semantic_id: str,
    *,
    semantic_name: str | None = None,
    owner: str | None = None,
    direction: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "role": role,
        "semantic_type": semantic_type,
        "candidate_id": f"{semantic_type}:{semantic_id}",
        "semantic_id": semantic_id,
        "semantic_name": semantic_name or semantic_id,
    }
    if owner is not None:
        payload["owner"] = owner
    if direction is not None:
        payload["direction"] = direction
    return payload


def _candidate(
    semantic_type: str,
    semantic_id: str,
    *,
    owner: str | None = None,
    semantic_name: str | None = None,
) -> SemanticCandidate:
    return SemanticCandidate(
        semantic_type=semantic_type,
        semantic_id=semantic_id,
        semantic_name=semantic_name or semantic_id,
        owner=owner,
        score=1.0,
        match_type="exact",
        evidence=[
            CandidateEvidence(
                term=semantic_id,
                source="test",
                matched_text=semantic_id,
            )
        ],
    )


def _coverage(covered: list[str], *, uncovered: list[str] | None = None) -> dict[str, Any]:
    covered_terms = covered
    uncovered_terms = uncovered or []
    return {
        "substantive_terms": {
            "total": len(covered_terms) + len(uncovered_terms),
            "covered": len(covered_terms),
            "uncovered": uncovered_terms,
        }
    }
