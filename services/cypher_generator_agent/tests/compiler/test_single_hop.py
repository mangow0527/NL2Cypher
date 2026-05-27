from __future__ import annotations

from services.cypher_generator_agent.app.compiler import compile_restricted_query_ast
from services.cypher_generator_agent.app.semantic_model import GraphSemanticRegistry

from .conftest import parse_dsl, single_hop_dsl


def test_gold_service_uses_tunnel_compiles_parameterized_cypher(
    registry: GraphSemanticRegistry,
) -> None:
    ast = parse_dsl(single_hop_dsl(), registry)

    result = compile_restricted_query_ast(ast, registry)

    assert result.schema_version == "cypher_compilation_result_v1"
    assert result.cypher == (
        "MATCH (svc:Service)-[:SERVICE_USES_TUNNEL]->(tun:Tunnel)\n"
        "WHERE svc.quality_of_service = $quality_of_service\n"
        "RETURN tun.id AS tunnel_id"
    )
    assert result.parameters == {"quality_of_service": "GOLD"}
    assert "GOLD" not in result.cypher
    assert result.validation_result.valid is True
    assert {check.name: check.status for check in result.validation_result.checks}["shape"] == "passed"


def test_single_hop_duplicate_filter_property_names_get_unique_parameters(
    registry: GraphSemanticRegistry,
) -> None:
    dsl = single_hop_dsl()
    dsl["filters"] = [
        {
            "target": "start",
            "property": {"owner": "Service", "name": "id"},
            "operator": "eq",
            "value": {
                "raw": "svc-gold-001",
                "normalized": "svc-gold-001",
                "resolver_match_type": "value_index_exact",
            },
        },
        {
            "target": "end",
            "property": {"owner": "Tunnel", "name": "id"},
            "operator": "eq",
            "value": {
                "raw": "tun-mpls-001",
                "normalized": "tun-mpls-001",
                "resolver_match_type": "value_index_exact",
            },
        },
    ]
    dsl["projection"]["items"][0]["alias"] = "id"
    ast = parse_dsl(dsl, registry)

    result = compile_restricted_query_ast(ast, registry)

    assert "svc.id = $id" in result.cypher
    assert "tun.id = $id_2" in result.cypher
    assert result.parameters == {"id": "svc-gold-001", "id_2": "tun-mpls-001"}
    assert "svc-gold-001" not in result.cypher
    assert "tun-mpls-001" not in result.cypher


def test_projection_alias_controls_return_alias(
    registry: GraphSemanticRegistry,
) -> None:
    dsl = single_hop_dsl()
    dsl["projection"]["items"][0]["alias"] = "service_tunnel"
    ast = parse_dsl(dsl, registry)

    result = compile_restricted_query_ast(ast, registry)

    assert result.cypher.endswith("RETURN tun.id AS service_tunnel")
