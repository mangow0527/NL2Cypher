from __future__ import annotations

from pathlib import Path

import pytest

from services.cypher_generator_agent.app.cypher_validation import CypherSelfValidator
from services.cypher_generator_agent.app.semantic_model import load_graph_semantic_model


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "network_topology_graph_model.yaml"


@pytest.fixture
def validator() -> CypherSelfValidator:
    return CypherSelfValidator(load_graph_semantic_model(FIXTURE_PATH).registry)


@pytest.mark.parametrize(
    ("function_name", "expression"),
    [
        ("count", "ne.id"),
        ("sum", "t.bandwidth"),
        ("avg", "t.bandwidth"),
        ("min", "t.bandwidth"),
        ("max", "t.bandwidth"),
    ],
)
def test_allowed_aggregate_functions_pass_target_dialect(
    validator: CypherSelfValidator,
    function_name: str,
    expression: str,
) -> None:
    label = "Tunnel" if expression.startswith("t.") else "NetworkElement"
    variable = expression.split(".", 1)[0]
    result = validator.validate_generated_query(
        f"MATCH ({variable}:{label}) RETURN {function_name}({expression}) AS value"
    )

    assert result.valid is True
    assert {check.name: check.status for check in result.checks}["dialect"] == "passed"


@pytest.mark.parametrize(
    "cypher",
    [
        "MATCH p = shortestPath((a:NetworkElement)-[:HAS_PORT*1..8]->(b:Port)) RETURN p",
        "MATCH (ne:NetworkElement) RETURN apoc.text.join([ne.id], ',') AS joined",
    ],
)
def test_non_allowlisted_functions_fail_target_dialect(
    validator: CypherSelfValidator,
    cypher: str,
) -> None:
    result = validator.validate_generated_query(cypher)

    assert result.valid is False
    assert result.errors[0].code == "target_dialect_static_error"
    assert result.errors[0].check == "dialect"
    assert "function" in result.errors[0].message


@pytest.mark.parametrize(
    "cypher",
    [
        "MATCH (n:$(label)) RETURN n",
        "MATCH (n:$label) RETURN n",
        "MATCH (n)-[:$edge_type]->(m) RETURN m",
        "MATCH (n:NetworkElement) RETURN n[$property_name] AS value",
    ],
)
def test_dynamic_schema_references_fail_target_dialect(
    validator: CypherSelfValidator,
    cypher: str,
) -> None:
    result = validator.validate_generated_query(cypher)

    assert result.valid is False
    assert result.errors[0].code == "target_dialect_static_error"
    assert result.errors[0].check == "dialect"
    assert "dynamic" in result.errors[0].message
