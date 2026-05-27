from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from services.cypher_generator_agent.app.binding.models import (
    BindingPlan,
    CandidateBinding,
    EdgeBinding,
    FilterBinding,
    LiteralBinding,
    VertexBinding,
)
from services.cypher_generator_agent.app.dsl.builder import RestrictedDslBuilder
from services.cypher_generator_agent.app.dsl.parser import parse_restricted_query_dsl
from services.cypher_generator_agent.app.semantic_model import GraphSemanticRegistry, load_graph_semantic_model


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "network_topology_graph_model.yaml"


@pytest.fixture(scope="module")
def registry() -> GraphSemanticRegistry:
    return load_graph_semantic_model(FIXTURE_PATH).registry


def test_gold_service_tunnel_plan_builds_single_hop_dsl(registry: GraphSemanticRegistry) -> None:
    literal = LiteralBinding(
        raw_literal="Gold",
        resolved=True,
        value="GOLD",
        normalized_value="GOLD",
        match_type="value_synonym",
        confidence=0.98,
        owner="Service",
        property="quality_of_service",
    )
    plan = BindingPlan(
        query_shape="single_hop_traversal",
        vertex_bindings=[
            VertexBinding(name="Service", candidate=_candidate("vertex", "Service")),
            VertexBinding(name="Tunnel", candidate=_candidate("vertex", "Tunnel")),
        ],
        edge_bindings=[
            EdgeBinding(
                name="SERVICE_USES_TUNNEL",
                candidate=_candidate("edge", "SERVICE_USES_TUNNEL"),
                direction="forward",
            )
        ],
        literal_bindings=[literal],
        filters=[
            FilterBinding(
                owner="Service",
                property="quality_of_service",
                operator="eq",
                raw_literal="Gold",
                value="GOLD",
                literal=literal,
            )
        ],
        projection=[{"semantic_type": "vertex", "name": "Tunnel"}],
        assumptions=[
            {
                "type": "literal_fuzzy_match",
                "raw_literal": "Gold",
                "owner": "Service",
                "property": "quality_of_service",
                "value": "GOLD",
                "confidence": 0.98,
            }
        ],
    )

    dsl = RestrictedDslBuilder(registry).build(
        plan,
        source_question="Gold 服务使用了哪些隧道",
        query_id="q-single-hop",
    )

    assert dsl == {
        "schema_version": "restricted_query_dsl_v1",
        "query_id": "q-single-hop",
        "query_shape": "single_hop_traversal",
        "source_question": "Gold 服务使用了哪些隧道",
        "bindings": {
            "start": {"vertex_name": "Service"},
            "edge": {"edge_name": "SERVICE_USES_TUNNEL"},
            "end": {"vertex_name": "Tunnel"},
        },
        "operations": [
            {
                "op": "traverse_edge",
                "from": "start",
                "edge": "edge",
                "to": "end",
                "direction": "forward",
            }
        ],
        "filters": [
            {
                "target": "start",
                "property": {"owner": "Service", "name": "quality_of_service"},
                "operator": "eq",
                "value": {
                    "raw": "Gold",
                    "normalized": "GOLD",
                    "resolver_match_type": "value_synonym",
                },
            }
        ],
        "projection": {
            "items": [
                {
                    "alias": "tunnel_id",
                    "target": "end",
                    "property": {"owner": "Tunnel", "name": "id"},
                }
            ]
        },
        "assumptions": [
            {
                "type": "literal_fuzzy_match",
                "raw_literal": "Gold",
                "owner": "Service",
                "property": "quality_of_service",
                "value": "GOLD",
                "confidence": 0.98,
            }
        ],
    }
    assert "raw_cypher" not in _all_keys(dsl)
    ast = parse_restricted_query_dsl(dsl, registry)
    assert ast.operations[0].edge_role.edge_name == "SERVICE_USES_TUNNEL"
    assert ast.filters[0].target.alias == "start"
    assert ast.projection.items[0].target.alias == "end"


def test_single_hop_uses_backward_edge_direction(registry: GraphSemanticRegistry) -> None:
    plan = BindingPlan(
        query_shape="single_hop_traversal",
        vertex_bindings=[
            VertexBinding(name="Tunnel", candidate=_candidate("vertex", "Tunnel")),
            VertexBinding(name="Service", candidate=_candidate("vertex", "Service")),
        ],
        edge_bindings=[
            EdgeBinding(
                name="SERVICE_USES_TUNNEL",
                candidate=_candidate("edge", "SERVICE_USES_TUNNEL"),
                direction="backward",
            )
        ],
        projection=[{"target": "end", "property": {"owner": "Service", "name": "id"}}],
    )

    dsl = RestrictedDslBuilder(registry).build(
        plan,
        source_question="哪些服务使用了这个隧道",
        query_id="q-backward",
    )

    assert dsl["operations"][0]["direction"] == "backward"
    assert dsl["operations"][0]["from"] == "start"
    assert dsl["operations"][0]["to"] == "end"
    assert dsl["bindings"]["start"] == {"vertex_name": "Tunnel"}
    assert dsl["bindings"]["end"] == {"vertex_name": "Service"}


def test_single_hop_rejects_sort_or_limit_until_compiler_supports_them(
    registry: GraphSemanticRegistry,
) -> None:
    plan = BindingPlan(
        query_shape="single_hop_traversal",
        vertex_bindings=[
            VertexBinding(name="Service", candidate=_candidate("vertex", "Service")),
            VertexBinding(name="Tunnel", candidate=_candidate("vertex", "Tunnel")),
        ],
        edge_bindings=[
            EdgeBinding(name="SERVICE_USES_TUNNEL", candidate=_candidate("edge", "SERVICE_USES_TUNNEL")),
        ],
        projection=[{"semantic_type": "vertex", "name": "Tunnel"}],
        limit=10,
    )

    with pytest.raises(ValueError, match="sort/limit"):
        RestrictedDslBuilder(registry).build(
            plan,
            source_question="Gold 服务使用了哪些隧道",
            query_id="q-single-hop-limit",
        )


def _candidate(semantic_type: str, semantic_id: str) -> CandidateBinding:
    return CandidateBinding(
        semantic_type=semantic_type,
        semantic_id=semantic_id,
        semantic_name=semantic_id,
        score=1.0,
        match_type="exact",
    )


def _all_keys(value: Any) -> set[str]:
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
