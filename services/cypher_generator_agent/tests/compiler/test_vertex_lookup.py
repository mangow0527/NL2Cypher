from __future__ import annotations

from typing import Any

from services.cypher_generator_agent.app.compiler import compile_restricted_query_ast
from services.cypher_generator_agent.app.semantic_model import GraphSemanticRegistry

from .conftest import parse_dsl


def test_vertex_lookup_compiles_parameterized_filter(
    registry: GraphSemanticRegistry,
) -> None:
    ast = parse_dsl(_vertex_lookup_dsl(), registry)

    result = compile_restricted_query_ast(ast, registry)

    assert result.cypher == (
        "MATCH (ne:NetworkElement)\n"
        "WHERE ne.id = $id\n"
        "RETURN ne.name AS name"
    )
    assert result.parameters == {"id": "ne-0001"}
    assert "ne-0001" not in result.cypher
    assert result.validation_result.valid is True


def _vertex_lookup_dsl() -> dict[str, Any]:
    return {
        "schema_version": "restricted_query_dsl_v1",
        "query_id": "q-vertex",
        "query_shape": "vertex_lookup",
        "source_question": "查询设备 ne-0001 的名称",
        "bindings": {"target": {"vertex_name": "NetworkElement"}},
        "operations": [],
        "filters": [
            {
                "target": "target",
                "property": {"owner": "NetworkElement", "name": "id"},
                "operator": "eq",
                "value": {
                    "raw": "ne-0001",
                    "normalized": "ne-0001",
                    "resolver_match_type": "value_index_exact",
                },
            }
        ],
        "projection": {
            "items": [
                {
                    "alias": "name",
                    "target": "target",
                    "property": {"owner": "NetworkElement", "name": "name"},
                }
            ]
        },
    }
