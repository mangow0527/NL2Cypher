from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from services.cypher_generator_agent.app.assembly.zero_hop import ZeroHopAssembler
from services.cypher_generator_agent.app.binding.models import CandidateBinding
from services.cypher_generator_agent.app.dsl.parser import parse_restricted_query_dsl
from services.cypher_generator_agent.app.semantic_model import GraphSemanticRegistry, load_graph_semantic_model
from services.cypher_generator_agent.app.validation.structural_requirements import StructuralRequirements


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "network_topology_graph_model.yaml"


@pytest.fixture(scope="module")
def registry() -> GraphSemanticRegistry:
    return load_graph_semantic_model(FIXTURE_PATH).registry


def test_f1_unique_vertex_and_projection_properties_builds_parseable_vertex_lookup(
    registry: GraphSemanticRegistry,
) -> None:
    result = ZeroHopAssembler(registry).assemble(
        "F1",
        candidates=[
            _candidate("vertex", "Service"),
            _candidate("property", "Service.quality_of_service", owner="Service", semantic_name="quality_of_service"),
            _candidate("property", "Service.service_type", owner="Service", semantic_name="service_type"),
        ],
        structural_requirements={
            "projection": [
                {"property": "quality_of_service", "alias": "qos"},
                {"property": "service_type", "alias": "service_type"},
            ]
        },
    )

    assert result.success is True
    assert result.dsl is not None
    ast = parse_restricted_query_dsl(result.dsl, registry)
    assert ast.query_shape.value == "vertex_lookup"
    assert result.dsl["bindings"]["target"]["vertex_name"] == "Service"
    assert ast.projection.items[0].target.vertex_name == "Service"
    assert [(item.alias, item.property.owner, item.property.name) for item in ast.projection.items] == [
        ("qos", "Service", "quality_of_service"),
        ("service_type", "Service", "service_type"),
    ]


def test_f1_accepts_taxonomy_shape_value_and_mir006_projection_terms(
    registry: GraphSemanticRegistry,
) -> None:
    result = ZeroHopAssembler(registry).assemble(
        "F1 vertex_projection_0hop",
        candidates=[
            _candidate("vertex", "Service"),
            _candidate("property", "Service.id", owner="Service", semantic_name="id"),
        ],
        structural_requirements=StructuralRequirements(projection_terms=["id"]).model_dump(mode="json"),
    )

    assert result.success is True
    assert result.dsl is not None
    ast = parse_restricted_query_dsl(result.dsl, registry)
    assert ast.projection.items[0].property.owner == "Service"
    assert ast.projection.items[0].property.name == "id"


def test_f1_ambiguous_vertex_or_projection_owner_falls_back(registry: GraphSemanticRegistry) -> None:
    vertex_result = ZeroHopAssembler(registry).assemble(
        "F1",
        candidates=[
            _candidate("vertex", "Service"),
            _candidate("vertex", "Tunnel"),
            _candidate("property", "Service.id", owner="Service", semantic_name="id"),
        ],
        structural_requirements={"projection": [{"property": "id"}]},
    )
    assert vertex_result.success is False
    assert vertex_result.dsl is None
    assert vertex_result.fallback_reason == "ambiguous_vertex_candidate"

    property_result = ZeroHopAssembler(registry).assemble(
        "F1",
        candidates=[
            _candidate("vertex", "Service"),
            _candidate("property", "Service.id", owner="Service", semantic_name="id"),
            _candidate("property", "Tunnel.id", owner="Tunnel", semantic_name="id"),
        ],
        structural_requirements={"projection": [{"property": "id"}]},
    )
    assert property_result.success is False
    assert property_result.dsl is None
    assert property_result.fallback_reason == "ambiguous_projection_property"


def test_f2_unique_filter_property_and_literal_builds_parseable_filter(
    registry: GraphSemanticRegistry,
) -> None:
    result = ZeroHopAssembler(registry).assemble(
        "F2",
        candidates=[
            _candidate("vertex", "Service"),
            _candidate("property", "Service.quality_of_service", owner="Service", semantic_name="quality_of_service"),
            _candidate("property", "Service.id", owner="Service", semantic_name="id"),
        ],
        structural_requirements={
            "filters": [{"property": "quality_of_service", "operator": "eq"}],
            "projection": [{"property": "id", "alias": "service_id"}],
        },
        literals=[
            {
                "property": "quality_of_service",
                "owner": "Service",
                "raw": "Gold",
                "normalized": "GOLD",
                "resolver_match_type": "value_synonym",
            }
        ],
    )

    assert result.success is True
    assert result.dsl is not None
    ast = parse_restricted_query_dsl(result.dsl, registry)
    assert ast.filters[0].target.alias == "target"
    assert ast.filters[0].property.owner == "Service"
    assert ast.filters[0].property.name == "quality_of_service"
    assert ast.filters[0].value.normalized == "GOLD"
    assert ast.projection.items[0].property.name == "id"


def test_f3_unique_vertex_count_builds_parseable_aggregate(registry: GraphSemanticRegistry) -> None:
    result = ZeroHopAssembler(registry).assemble(
        "F3",
        candidates=[
            _candidate("vertex", "Service"),
            _candidate("property", "Service.id", owner="Service", semantic_name="id"),
        ],
        structural_requirements={"aggregate": {"function": "count", "alias": "service_count"}},
    )

    assert result.success is True
    assert result.dsl is not None
    ast = parse_restricted_query_dsl(result.dsl, registry)
    assert ast.query_shape.value == "ad_hoc_aggregate"
    assert ast.operations[0].group_by == []
    assert ast.operations[0].measures[0].function == "count"
    assert ast.operations[0].measures[0].target.alias == "target"
    assert ast.operations[0].measures[0].property.name == "id"
    assert ast.projection.items[0].source.namespace == "measure"
    assert ast.projection.items[0].source.name == "service_count"


def test_f3_with_group_order_or_limit_falls_back(registry: GraphSemanticRegistry) -> None:
    for structural_requirements in (
        {"aggregate": {"function": "count"}, "group_by": [{"property": "quality_of_service"}]},
        {"aggregate": {"function": "count"}, "order_by": [{"source": "measure.service_count"}]},
        {"aggregate": {"function": "count"}, "limit": 5},
    ):
        result = ZeroHopAssembler(registry).assemble(
            "F3",
            candidates=[
                _candidate("vertex", "Service"),
                _candidate("property", "Service.id", owner="Service", semantic_name="id"),
            ],
            structural_requirements=structural_requirements,
        )

        assert result.success is False
        assert result.dsl is None
        assert result.fallback_reason == "unsupported_f3_modifier"


def _candidate(
    semantic_type: str,
    semantic_id: str,
    *,
    owner: str | None = None,
    semantic_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> CandidateBinding:
    return CandidateBinding(
        semantic_type=semantic_type,
        semantic_id=semantic_id,
        semantic_name=semantic_name or semantic_id,
        owner=owner,
        score=1.0,
        match_type="exact",
        metadata=metadata or {},
    )
