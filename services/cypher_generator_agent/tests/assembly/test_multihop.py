from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from services.cypher_generator_agent.app.assembly.multihop import MultihopAssembler
from services.cypher_generator_agent.app.binding.models import CandidateBinding
from services.cypher_generator_agent.app.dsl.parser import parse_restricted_query_dsl
from services.cypher_generator_agent.app.semantic_model import GraphSemanticRegistry, load_graph_semantic_model


ARTIFACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "semantic_model"
    / "artifacts"
    / "tugraph_network_semantic_model.yaml"
)


@pytest.fixture(scope="module")
def registry() -> GraphSemanticRegistry:
    return load_graph_semantic_model(ARTIFACT_PATH).registry


def test_f4_unique_service_to_tunnel_path_projection_builds_parseable_traversal_dsl(
    registry: GraphSemanticRegistry,
) -> None:
    result = MultihopAssembler(registry).assemble(
        "F4 path_projection_multihop",
        candidates=[
            _candidate("vertex", "Service"),
            _candidate("vertex", "Tunnel"),
            _candidate("edge", "SERVICE_USES_TUNNEL"),
            _candidate("property", "Tunnel.id", owner="Tunnel", semantic_name="id"),
            _candidate("property", "Tunnel.name", owner="Tunnel", semantic_name="name"),
        ],
        structural_requirements={
            "path_terms": [
                {"text": "服务", "slot": "path", "order_index": 0},
                {"text": "使用", "slot": "path", "order_index": 1},
                {"text": "隧道", "slot": "path", "order_index": 2},
            ],
            "projection": [
                {"owner": "Tunnel", "property": "id", "alias": "tunnel_id"},
                {"owner": "Tunnel", "property": "name", "alias": "tunnel_name"},
            ],
            "min_path_hops": 1,
        },
    )

    assert result.success is True
    assert result.dsl is not None
    assert result.dsl["query_shape"] == "single_hop_traversal"
    assert result.dsl["bindings"] == {
        "v0": {"vertex_name": "Service"},
        "edge_0": {"edge_name": "SERVICE_USES_TUNNEL"},
        "v1": {"vertex_name": "Tunnel"},
    }
    assert result.dsl["operations"] == [
        {
            "op": "traverse_edge",
            "from": "v0",
            "edge": "edge_0",
            "to": "v1",
            "direction": "forward",
        }
    ]

    ast = parse_restricted_query_dsl(result.dsl, registry)
    assert ast.operations[0].edge_role.edge_name == "SERVICE_USES_TUNNEL"
    assert [(item.target.alias, item.property.owner, item.property.name) for item in ast.projection.items] == [
        ("v1", "Tunnel", "id"),
        ("v1", "Tunnel", "name"),
    ]


def test_f5_unique_service_filter_and_path_projection_builds_parseable_traversal_filter(
    registry: GraphSemanticRegistry,
) -> None:
    result = MultihopAssembler(registry).assemble(
        "F5 path_filter_multihop",
        candidates=[
            _candidate("vertex", "Service"),
            _candidate("vertex", "Tunnel"),
            _candidate("edge", "SERVICE_USES_TUNNEL"),
            _candidate("property", "Service.quality_of_service", owner="Service", semantic_name="quality_of_service"),
            _candidate("property", "Tunnel.id", owner="Tunnel", semantic_name="id"),
        ],
        structural_requirements={
            "path_terms": [
                {"text": "Gold 服务", "slot": "path", "order_index": 0},
                {"text": "使用隧道", "slot": "path", "order_index": 1},
            ],
            "filters": [{"owner": "Service", "property": "quality_of_service", "operator": "eq"}],
            "projection": [{"owner": "Tunnel", "property": "id", "alias": "tunnel_id"}],
            "min_path_hops": 1,
        },
        literals=[
            {
                "owner": "Service",
                "property": "quality_of_service",
                "raw": "Gold",
                "normalized": "GOLD",
                "resolver_match_type": "value_synonym",
            }
        ],
    )

    assert result.success is True
    assert result.dsl is not None
    ast = parse_restricted_query_dsl(result.dsl, registry)
    assert ast.filters[0].target.alias == "v0"
    assert ast.filters[0].property.owner == "Service"
    assert ast.filters[0].property.name == "quality_of_service"
    assert ast.filters[0].value.normalized == "GOLD"
    assert ast.projection.items[0].target.alias == "v1"


def test_f4_multiple_path_candidates_or_direction_ambiguity_falls_back(
    registry: GraphSemanticRegistry,
) -> None:
    unrelated_edges = MultihopAssembler(registry).assemble(
        "F4",
        candidates=[
            _candidate("vertex", "Service"),
            _candidate("vertex", "Tunnel"),
            _candidate("edge", "SERVICE_USES_TUNNEL"),
            _candidate("edge", "TUNNEL_SRC"),
            _candidate("property", "Tunnel.id", owner="Tunnel", semantic_name="id"),
        ],
        structural_requirements={
            "path_terms": [{"text": "服务使用隧道", "slot": "path", "order_index": 0}],
            "projection": [{"owner": "Tunnel", "property": "id"}],
            "min_path_hops": 1,
        },
    )

    assert unrelated_edges.success is True
    assert unrelated_edges.dsl is not None
    assert unrelated_edges.dsl["bindings"]["edge_0"] == {"edge_name": "SERVICE_USES_TUNNEL"}

    ambiguous_direction = MultihopAssembler(registry).assemble(
        "F4",
        candidates=[
            _candidate("vertex", "Tunnel"),
            _candidate("vertex", "NetworkElement"),
            _candidate("edge", "TUNNEL_SRC"),
            _candidate("property", "NetworkElement.id", owner="NetworkElement", semantic_name="id"),
        ],
        structural_requirements={
            "path_terms": [{"text": "查询隧道源和目的设备", "slot": "path", "order_index": 0}],
            "projection": [{"owner": "NetworkElement", "property": "id"}],
            "min_path_hops": 1,
        },
    )

    assert ambiguous_direction.success is False
    assert ambiguous_direction.dsl is None
    assert ambiguous_direction.fallback_reason == "ambiguous_direction_terms"


def test_f6_unique_path_group_topn_builds_top_n_dsl(
    registry: GraphSemanticRegistry,
) -> None:
    result = MultihopAssembler(registry).assemble(
        "F6 path_group_topn",
        candidates=[
            _candidate("vertex", "Service"),
            _candidate("vertex", "Tunnel"),
            _candidate("edge", "SERVICE_USES_TUNNEL"),
            _candidate("property", "Service.id", owner="Service", semantic_name="id"),
            _candidate("property", "Tunnel.id", owner="Tunnel", semantic_name="id"),
        ],
        structural_requirements={
            "path_terms": [{"text": "服务使用隧道", "slot": "path", "order_index": 0}],
            "requires_aggregate": True,
            "group_by": [{"owner": "Tunnel", "property": "id", "alias": "tunnel_id"}],
            "aggregate": {
                "function": "count",
                "owner": "Service",
                "property": "id",
                "alias": "service_count",
            },
            "order_by": [{"source": "measure.service_count", "direction": "desc"}],
            "limit": 3,
        },
    )

    assert result.success is True
    assert result.dsl is not None
    assert result.dsl["query_shape"] == "top_n"
    assert [operation["op"] for operation in result.dsl["operations"]] == [
        "traverse_edge",
        "aggregate",
        "sort",
        "limit",
    ]
    aggregate = result.dsl["operations"][1]
    assert aggregate["group_by"] == [
        {
            "alias": "tunnel_id",
            "target": "v1",
            "property": {"owner": "Tunnel", "name": "id"},
        }
    ]
    assert aggregate["measures"] == [
        {
            "alias": "service_count",
            "function": "count",
            "target": "v0",
            "property": {"owner": "Service", "name": "id"},
        }
    ]
    assert result.dsl["operations"][2] == {
        "op": "sort",
        "by": [{"source": "measure.service_count", "direction": "desc"}],
    }
    assert result.dsl["operations"][3] == {"op": "limit", "value": 3}


def test_f6_multiple_limit_values_falls_back_before_dsl_boundary(
    registry: GraphSemanticRegistry,
) -> None:
    result = MultihopAssembler(registry).assemble(
        "F6 path_group_topn",
        candidates=[
            _candidate("vertex", "Service"),
            _candidate("vertex", "Tunnel"),
            _candidate("edge", "SERVICE_USES_TUNNEL"),
            _candidate("property", "Service.id", owner="Service", semantic_name="id"),
            _candidate("property", "Tunnel.id", owner="Tunnel", semantic_name="id"),
        ],
        structural_requirements={
            "path_terms": [{"text": "服务使用隧道", "slot": "path", "order_index": 0}],
            "requires_aggregate": True,
            "group_by": [{"owner": "Tunnel", "property": "id", "alias": "tunnel_id"}],
            "aggregate": {
                "function": "count",
                "owner": "Service",
                "property": "id",
                "alias": "service_count",
            },
            "order_by": [{"source": "measure.service_count", "direction": "desc"}],
            "limit": [3, 5],
        },
    )

    assert result.success is False
    assert result.dsl is None
    assert result.fallback_reason == "ambiguous_limit_requirement"


def _candidate(
    semantic_type: str,
    semantic_id: str,
    *,
    owner: str | None = None,
    semantic_name: str | None = None,
    metadata: dict[str, Any] | None = None,
    score: float = 1.0,
) -> CandidateBinding:
    return CandidateBinding(
        semantic_type=semantic_type,
        semantic_id=semantic_id,
        semantic_name=semantic_name or semantic_id,
        owner=owner,
        score=score,
        match_type="exact",
        metadata=metadata or {},
    )
