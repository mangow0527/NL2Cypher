from __future__ import annotations

from services.cypher_generator_agent.app.compiler import compile_restricted_query_ast
from services.cypher_generator_agent.app.semantic_model import GraphSemanticRegistry

from .conftest import parse_dsl


def test_top_n_metric_aggregate_compiles_order_and_limit(
    registry: GraphSemanticRegistry,
) -> None:
    ast = parse_dsl(_top_n_port_count_dsl(), registry)

    result = compile_restricted_query_ast(ast, registry)

    assert result.cypher == (
        "MATCH (ne:NetworkElement)-[:HAS_PORT]->(port:Port)\n"
        "RETURN ne.id AS device, count(port) AS port_count\n"
        "ORDER BY port_count DESC\n"
        "LIMIT 5"
    )
    assert result.parameters == {}
    assert result.validation_result.valid is True


def test_two_step_aggregate_compiles_with_chain(
    registry: GraphSemanticRegistry,
) -> None:
    ast = parse_dsl(_two_step_status_count_dsl(), registry)

    result = compile_restricted_query_ast(ast, registry)

    assert result.cypher == (
        "MATCH (port:Port)\n"
        "WITH port.status AS status, count(port.id) AS port_count\n"
        "RETURN status AS status, port_count AS port_count\n"
        "ORDER BY port_count DESC\n"
        "LIMIT 5"
    )
    assert result.parameters == {}
    assert result.validation_result.valid is True


def test_two_step_aggregate_compiles_filter_subquery(
    registry: GraphSemanticRegistry,
) -> None:
    dsl = _two_step_status_count_dsl()
    dsl["operations"].insert(
        1,
        {
            "op": "filter_subquery",
            "source": "port_status_counts",
            "predicate": {"property": "port_count", "operator": "gt", "value": 10},
        },
    )
    ast = parse_dsl(dsl, registry)

    result = compile_restricted_query_ast(ast, registry)

    assert result.cypher == (
        "MATCH (port:Port)\n"
        "WITH port.status AS status, count(port.id) AS port_count\n"
        "WHERE port_count > $port_count\n"
        "RETURN status AS status, port_count AS port_count\n"
        "ORDER BY port_count DESC\n"
        "LIMIT 5"
    )
    assert result.parameters == {"port_count": 10}


def _top_n_port_count_dsl() -> dict:
    return {
        "schema_version": "restricted_query_dsl_v1",
        "query_id": "q-top-n-ports",
        "query_shape": "top_n",
        "source_question": "端口最多的 5 台设备",
        "bindings": {"metric": {"metric_name": "port_count"}},
        "operations": [
            {
                "op": "metric_aggregate",
                "metric_name": "port_count",
                "group_by": [
                    {
                        "alias": "device",
                        "target": "ne",
                        "property": {"owner": "NetworkElement", "name": "id"},
                    }
                ],
                "filters": [],
            },
            {"op": "sort", "by": [{"source": "metric.port_count", "direction": "desc"}]},
            {"op": "limit", "value": 5},
        ],
        "projection": {
            "items": [
                {"alias": "device", "source": "group.device"},
                {"alias": "port_count", "source": "metric.port_count"},
            ]
        },
    }


def _two_step_status_count_dsl() -> dict:
    return {
        "schema_version": "restricted_query_dsl_v1",
        "query_id": "q-two-step-port-status",
        "query_shape": "two_step_aggregate",
        "source_question": "先按状态统计端口，再取最多的 5 个状态",
        "bindings": {"port": {"vertex_name": "Port"}},
        "operations": [
            {
                "op": "subquery",
                "bind_as": "port_status_counts",
                "query_shape": "ad_hoc_aggregate",
                "group_by": [
                    {
                        "alias": "status",
                        "target": "port",
                        "property": {"owner": "Port", "name": "status"},
                    }
                ],
                "measures": [
                    {
                        "alias": "port_count",
                        "function": "count",
                        "target": "port",
                        "property": {"owner": "Port", "name": "id"},
                    }
                ],
            },
            {"op": "sort", "by": [{"source": "port_status_counts.port_count", "direction": "desc"}]},
            {"op": "limit", "value": 5},
        ],
        "projection": {
            "items": [
                {"alias": "status", "source": "port_status_counts.status"},
                {"alias": "port_count", "source": "port_status_counts.port_count"},
            ]
        },
    }
