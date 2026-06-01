from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from services.cypher_generator_agent.app.assembly.multihop import MultihopAssembler
from services.cypher_generator_agent.app.assembly.taxonomy import QueryShape
from services.cypher_generator_agent.app.binding.models import CandidateBinding
from services.cypher_generator_agent.app.core.pipeline import (
    _multihop_assembler_requirements,
    _projection_items_from_substantive_terms,
)
from services.cypher_generator_agent.app.dsl.parser import parse_restricted_query_dsl
from services.cypher_generator_agent.app.retrieval.models import CandidateRetrievalResult, SemanticCandidate
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


def test_f4_projection_owner_extends_path_to_unique_endpoint(
    registry: GraphSemanticRegistry,
) -> None:
    result = MultihopAssembler(registry).assemble(
        "F4 path_projection_multihop",
        candidates=[
            _candidate("vertex", "Service"),
            _candidate("vertex", "Tunnel"),
            _candidate("vertex", "NetworkElement"),
            _candidate("vertex", "Port"),
            _candidate("edge", "SERVICE_USES_TUNNEL"),
            _candidate("edge", "PATH_THROUGH"),
            _candidate("edge", "HAS_PORT"),
            _candidate("property", "Port.mac_address", owner="Port", semantic_name="mac_address"),
            _candidate("property", "Port.status", owner="Port", semantic_name="status"),
        ],
        structural_requirements={
            "path_terms": [
                {"text": "服务", "slot": "path", "order_index": 0},
                {"text": "隧道", "slot": "path", "order_index": 1},
                {"text": "网元", "slot": "path", "order_index": 2},
            ],
            "projection": [
                {"owner": "Port", "property": "mac_address", "alias": "port_mac_address"},
                {"owner": "Port", "property": "status", "alias": "port_status"},
            ],
            "min_path_hops": 2,
        },
    )

    assert result.success is True
    assert result.dsl is not None
    assert result.dsl["bindings"]["v3"] == {"vertex_name": "Port"}
    assert result.dsl["bindings"]["edge_2"] == {"edge_name": "HAS_PORT"}
    assert result.dsl["operations"][-1] == {
        "op": "traverse_edge",
        "from": "v2",
        "edge": "edge_2",
        "to": "v3",
        "direction": "forward",
    }

    ast = parse_restricted_query_dsl(result.dsl, registry)
    assert [(item.target.alias, item.property.owner, item.property.name) for item in ast.projection.items] == [
        ("v3", "Port", "mac_address"),
        ("v3", "Port", "status"),
    ]


def test_f4_projection_owners_extend_path_across_implicit_endpoints(
    registry: GraphSemanticRegistry,
) -> None:
    result = MultihopAssembler(registry).assemble(
        "F4 path_projection_multihop",
        candidates=[
            _candidate("vertex", "Service"),
            _candidate("vertex", "Tunnel"),
            _candidate("vertex", "NetworkElement"),
            _candidate("vertex", "Port"),
            _candidate("edge", "SERVICE_USES_TUNNEL"),
            _candidate("edge", "PATH_THROUGH"),
            _candidate("edge", "HAS_PORT"),
            _candidate("edge", "TUNNEL_DST"),
            _candidate("edge", "TUNNEL_SRC"),
            _candidate("property", "NetworkElement.location", owner="NetworkElement", semantic_name="location"),
            _candidate("property", "Port.mac_address", owner="Port", semantic_name="mac_address"),
        ],
        structural_requirements={
            "path_terms": [
                {"text": "服务", "slot": "path", "order_index": 0},
                {"text": "使用", "slot": "path", "order_index": 1},
                {"text": "隧道", "slot": "path", "order_index": 2},
                {"text": "经过", "slot": "path", "order_index": 3},
            ],
            "projection": [
                {"owner": "NetworkElement", "property": "location", "alias": "network_element_location"},
                {"owner": "Port", "property": "mac_address", "alias": "port_mac_address"},
            ],
            "min_path_hops": 2,
        },
    )

    assert result.success is True
    assert result.dsl is not None
    assert result.dsl["bindings"]["v2"] == {"vertex_name": "NetworkElement"}
    assert result.dsl["bindings"]["edge_1"] == {"edge_name": "PATH_THROUGH"}
    assert result.dsl["bindings"]["v3"] == {"vertex_name": "Port"}
    assert result.dsl["bindings"]["edge_2"] == {"edge_name": "HAS_PORT"}

    ast = parse_restricted_query_dsl(result.dsl, registry)
    assert [(item.target.alias, item.property.owner, item.property.name) for item in ast.projection.items] == [
        ("v2", "NetworkElement", "location"),
        ("v3", "Port", "mac_address"),
    ]


def test_f4_unique_edge_ignores_downstream_direction_term_leakage(
    registry: GraphSemanticRegistry,
) -> None:
    result = MultihopAssembler(registry).assemble(
        "F4 path_projection_multihop",
        candidates=[
            _candidate("vertex", "Service"),
            _candidate("vertex", "Tunnel"),
            _candidate("vertex", "NetworkElement"),
            _candidate("edge", "SERVICE_USES_TUNNEL"),
            _candidate("edge", "PATH_THROUGH"),
            _candidate("edge", "TUNNEL_DST"),
            _candidate("edge", "TUNNEL_SRC"),
            _candidate("property", "NetworkElement.ip_address", owner="NetworkElement", semantic_name="ip_address"),
        ],
        structural_requirements={
            "path_terms": [
                {"text": "服务", "slot": "path", "order_index": 0},
                {"text": "经过", "slot": "path", "order_index": 1},
                {"text": "隧道", "slot": "path", "order_index": 2},
                {"text": "穿过", "slot": "path", "order_index": 3},
                {"text": "网元设备", "slot": "path", "order_index": 4},
            ],
            "projection": [
                {"owner": "NetworkElement", "property": "ip_address", "alias": "network_element_ip_address"},
            ],
            "min_path_hops": 2,
        },
    )

    assert result.success is True
    assert result.dsl is not None
    assert result.dsl["bindings"]["edge_0"] == {"edge_name": "SERVICE_USES_TUNNEL"}
    assert result.dsl["bindings"]["edge_1"] == {"edge_name": "PATH_THROUGH"}


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


def test_projection_term_attached_to_multiple_path_owners_expands_each_owner(
    registry: GraphSemanticRegistry,
) -> None:
    projection = _projection_items_from_substantive_terms(
        decomposition={
            "original_question": "查询服务及其使用的隧道的时延。",
            "substantive_terms": [
                {"text": "服务", "slot": "path"},
                {"text": "使用", "slot": "path"},
                {"text": "隧道", "slot": "path"},
                {"text": "时延", "slot": "projection", "attached_to": "服务及其使用的隧道"},
            ],
        },
        candidates=[
            _semantic_candidate("vertex", "Service"),
            _semantic_candidate("vertex", "Tunnel"),
            _semantic_candidate("property", "Service.latency", owner="Service", semantic_name="latency"),
            _semantic_candidate("property", "Tunnel.latency", owner="Tunnel", semantic_name="latency"),
        ],
        registry=registry,
        selected_vertices=["Service", "Tunnel"],
    )

    assert [(item["owner"], item["name"]) for item in projection] == [
        ("Service", "latency"),
        ("Tunnel", "latency"),
    ]


def test_endpoint_projection_owner_can_be_embedded_inside_attachment_phrase(
    registry: GraphSemanticRegistry,
) -> None:
    projection = _projection_items_from_substantive_terms(
        decomposition={
            "original_question": "查询服务经隧道到网元下的端口ID和名称。",
            "substantive_terms": [
                {"text": "服务", "slot": "path"},
                {"text": "隧道", "slot": "path"},
                {"text": "网元", "slot": "path"},
                {"text": "端口", "slot": "path"},
                {"text": "ID", "slot": "projection", "attached_to": "网元下的端口"},
                {"text": "名称", "slot": "projection", "attached_to": "网元下的端口"},
            ],
        },
        candidates=[
            _semantic_candidate("vertex", "Service"),
            _semantic_candidate("vertex", "Tunnel"),
            _semantic_candidate("vertex", "NetworkElement"),
            _semantic_candidate("vertex", "Port"),
            _semantic_candidate("property", "Port.id", owner="Port", semantic_name="id"),
            _semantic_candidate("property", "Port.name", owner="Port", semantic_name="name"),
        ],
        registry=registry,
        selected_vertices=["Service", "Tunnel", "NetworkElement", "Port"],
    )

    assert [(item["owner"], item["name"]) for item in projection] == [
        ("Port", "id"),
        ("Port", "name"),
    ]


def test_endpoint_projection_matches_compact_ip_address_surface(
    registry: GraphSemanticRegistry,
) -> None:
    projection = _projection_items_from_substantive_terms(
        decomposition={
            "original_question": "查询所有服务经过隧道穿过的网元设备的IP地址。",
            "substantive_terms": [
                {"text": "服务", "slot": "path"},
                {"text": "隧道", "slot": "path"},
                {"text": "网元设备", "slot": "path"},
                {"text": "IP地址", "slot": "projection", "attached_to": "网元设备"},
            ],
        },
        candidates=[
            _semantic_candidate("vertex", "Service"),
            _semantic_candidate("vertex", "Tunnel"),
            _semantic_candidate("vertex", "NetworkElement"),
            _semantic_candidate(
                "property",
                "NetworkElement.ip_address",
                owner="NetworkElement",
                semantic_name="ip_address",
            ),
        ],
        registry=registry,
        selected_vertices=["Service", "Tunnel", "NetworkElement"],
    )

    assert [(item["owner"], item["name"]) for item in projection] == [
        ("NetworkElement", "ip_address"),
    ]


def test_endpoint_projection_matches_compact_mac_address_surface(
    registry: GraphSemanticRegistry,
) -> None:
    projection = _projection_items_from_substantive_terms(
        decomposition={
            "original_question": "查询业务所经隧道路径上网元的端口，返回MAC地址。",
            "substantive_terms": [
                {"text": "业务", "slot": "path"},
                {"text": "隧道", "slot": "path"},
                {"text": "网元", "slot": "path"},
                {"text": "端口", "slot": "path"},
                {"text": "MAC地址", "slot": "projection", "attached_to": "端口"},
            ],
        },
        candidates=[
            _semantic_candidate("vertex", "Service"),
            _semantic_candidate("vertex", "Tunnel"),
            _semantic_candidate("vertex", "NetworkElement"),
            _semantic_candidate("vertex", "Port"),
            _semantic_candidate("property", "Port.mac_address", owner="Port", semantic_name="mac_address"),
        ],
        registry=registry,
        selected_vertices=["Service", "Tunnel", "NetworkElement", "Port"],
    )

    assert [(item["owner"], item["name"]) for item in projection] == [
        ("Port", "mac_address"),
    ]


def test_projection_attachment_anchor_is_not_projected_as_property(
    registry: GraphSemanticRegistry,
) -> None:
    projection = _projection_items_from_substantive_terms(
        decomposition={
            "original_question": "查询业务所经隧道路径上网元的端口，返回MAC地址和状态。",
            "substantive_terms": [
                {"text": "业务", "slot": "path"},
                {"text": "隧道", "slot": "path"},
                {"text": "网元", "slot": "path"},
                {"text": "端口", "slot": "projection", "attached_to": "网元"},
                {"text": "MAC地址", "slot": "projection", "attached_to": "端口"},
                {"text": "状态", "slot": "projection", "attached_to": "端口"},
            ],
        },
        candidates=[
            _semantic_candidate("vertex", "Service"),
            _semantic_candidate("vertex", "Tunnel"),
            _semantic_candidate("vertex", "NetworkElement"),
            _semantic_candidate("vertex", "Port"),
            _semantic_candidate("property", "NetworkElement.id", owner="NetworkElement", semantic_name="id"),
            _semantic_candidate("property", "Port.mac_address", owner="Port", semantic_name="mac_address"),
            _semantic_candidate("property", "Port.status", owner="Port", semantic_name="status"),
        ],
        registry=registry,
        selected_vertices=["Service", "Tunnel", "NetworkElement", "Port"],
    )

    assert [(item["owner"], item["name"]) for item in projection] == [
        ("Port", "mac_address"),
        ("Port", "status"),
    ]


def test_projection_object_term_projects_matched_vertex_id(
    registry: GraphSemanticRegistry,
) -> None:
    projection = _projection_items_from_substantive_terms(
        decomposition={
            "original_question": "查询所有服务使用的隧道所经过的网元。",
            "substantive_terms": [
                {"text": "服务", "slot": "path"},
                {"text": "使用", "slot": "path"},
                {"text": "隧道", "slot": "path"},
                {"text": "经过", "slot": "path"},
                {"text": "网元", "slot": "projection"},
            ],
        },
        candidates=[
            _semantic_candidate("vertex", "Service"),
            _semantic_candidate("vertex", "Tunnel"),
            _semantic_candidate("vertex", "NetworkElement"),
            _semantic_candidate("property", "Tunnel.id", owner="Tunnel", semantic_name="id"),
            _semantic_candidate("property", "NetworkElement.id", owner="NetworkElement", semantic_name="id"),
        ],
        registry=registry,
        selected_vertices=["Service", "Tunnel", "NetworkElement"],
    )

    assert [(item["owner"], item["name"], item["projection_terms"]) for item in projection] == [
        ("NetworkElement", "id", ["网元"]),
    ]


def test_f4_requirements_report_uncovered_projection_slot_by_attachment(
    registry: GraphSemanticRegistry,
) -> None:
    requirements = _multihop_assembler_requirements(
        shape=QueryShape.F4_PATH_PROJECTION_MULTIHOP,
        decomposition={
            "original_question": "查询服务及其使用的隧道的服务质量等级。",
            "substantive_terms": [
                {"text": "服务", "slot": "path"},
                {"text": "使用", "slot": "path"},
                {"text": "隧道", "slot": "path"},
                {"text": "服务质量等级", "slot": "projection", "attached_to": "服务及其使用的隧道"},
            ],
        },
        retrieval_result=CandidateRetrievalResult(
            candidates=[
                _semantic_candidate("vertex", "Service"),
                _semantic_candidate("vertex", "Tunnel"),
                _semantic_candidate(
                    "property",
                    "Service.quality_of_service",
                    owner="Service",
                    semantic_name="quality_of_service",
                ),
            ],
        ),
        literal_results=[],
        registry=registry,
    )

    assert requirements["projection_uncovered_terms"] == ["服务及其使用的隧道.服务质量等级"]


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


def _semantic_candidate(
    semantic_type: str,
    semantic_id: str,
    *,
    owner: str | None = None,
    semantic_name: str | None = None,
) -> SemanticCandidate:
    return SemanticCandidate(
        semantic_type=semantic_type,
        semantic_id=semantic_id,
        semantic_name=semantic_name or semantic_id.rsplit(".", 1)[-1],
        owner=owner,
        score=1.0,
        match_type="exact",
        evidence=[],
        metadata={},
    )
