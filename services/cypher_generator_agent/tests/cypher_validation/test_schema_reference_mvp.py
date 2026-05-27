from __future__ import annotations

from pathlib import Path

import pytest

from services.cypher_generator_agent.app.cypher_validation import (
    CypherSelfValidationRequest,
    CypherSelfValidator,
)
from services.cypher_generator_agent.app.semantic_model import load_graph_semantic_model


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "network_topology_graph_model.yaml"


@pytest.fixture
def validator() -> CypherSelfValidator:
    return CypherSelfValidator(load_graph_semantic_model(FIXTURE_PATH).registry)


def validate(validator: CypherSelfValidator, cypher: str):
    return validator.validate(
        CypherSelfValidationRequest(
            mode="generated_query",
            source_kind="compiled_query",
            cypher=cypher,
        )
    )


@pytest.mark.parametrize(
    ("cypher", "message_fragment"),
    [
        ("MATCH (x:UnknownLabel) RETURN x", "UnknownLabel"),
        ("MATCH (ne:NetworkElement) RETURN ne.unknown_property AS x", "unknown_property"),
        ("MATCH (t:Tunnel)-[:UNKNOWN_EDGE]->(ne:NetworkElement) RETURN ne", "UNKNOWN_EDGE"),
        ("MATCH (ne:NetworkElement)-[:PATH_THROUGH]->(t:Tunnel) RETURN ne", "PATH_THROUGH"),
        ("MATCH (ne:NetworkElement {unknown_property: $id}) RETURN ne", "unknown_property"),
    ],
)
def test_unknown_schema_references_are_invalid(
    validator: CypherSelfValidator,
    cypher: str,
    message_fragment: str,
) -> None:
    result = validate(validator, cypher)

    assert result.valid is False
    assert [error.code for error in result.errors] == ["cypher_schema_reference_invalid"]
    assert result.errors[0].check == "schema_reference"
    assert message_fragment in result.errors[0].message


def test_edge_variable_property_passes_when_property_belongs_to_edge(
    validator: CypherSelfValidator,
) -> None:
    result = validate(
        validator,
        "MATCH (t:Tunnel)-[p:PATH_THROUGH]->(ne:NetworkElement) RETURN p.hop_order AS hop",
    )

    assert result.valid is True
    assert result.errors == []


def test_edge_variable_property_is_rejected_when_property_does_not_belong_to_edge(
    validator: CypherSelfValidator,
) -> None:
    result = validate(
        validator,
        "MATCH (t:Tunnel)-[p:PATH_THROUGH]->(ne:NetworkElement) RETURN p.unknown_property AS hop",
    )

    assert result.valid is False
    assert [error.code for error in result.errors] == ["cypher_schema_reference_invalid"]
    assert "unknown_property" in result.errors[0].message


def test_reverse_edge_direction_uses_reversed_endpoint_validation(
    validator: CypherSelfValidator,
) -> None:
    result = validate(
        validator,
        "MATCH (ne:NetworkElement)<-[p:PATH_THROUGH]-(t:Tunnel) RETURN p.hop_order AS hop",
    )

    assert result.valid is True
    assert result.errors == []


@pytest.mark.parametrize(
    ("cypher", "message_fragment"),
    [
        ("MATCH (ne:NetworkElement:UnknownLabel) RETURN ne", "UnknownLabel"),
        ("MATCH (t:Tunnel)-[:PATH_THROUGH|UNKNOWN_EDGE]->(ne:NetworkElement) RETURN ne", "multiple edge types"),
        ("MATCH (ne:`NetworkElement`) RETURN ne", "backtick"),
    ],
)
def test_unsupported_compound_or_backtick_schema_references_are_invalid(
    validator: CypherSelfValidator,
    cypher: str,
    message_fragment: str,
) -> None:
    result = validate(validator, cypher)

    assert result.valid is False
    assert result.errors[0].code == "cypher_schema_reference_invalid"
    assert result.errors[0].check == "schema_reference"
    assert message_fragment in result.errors[0].message


def test_chained_pattern_validates_second_edge_endpoint(
    validator: CypherSelfValidator,
) -> None:
    result = validate(
        validator,
        (
            "MATCH (svc:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel)"
            "-[:HAS_PORT]->(p:Port) RETURN p"
        ),
    )

    assert result.valid is False
    assert result.errors[0].code == "cypher_schema_reference_invalid"
    assert "HAS_PORT" in result.errors[0].message


def test_endpoint_validation_uses_prior_variable_binding(
    validator: CypherSelfValidator,
) -> None:
    result = validate(
        validator,
        "MATCH (ne:NetworkElement) MATCH (ne)-[:HAS_PORT]->(p:Port) RETURN p.id AS port_id",
    )

    assert result.valid is True
    assert result.errors == []


def test_endpoint_validation_rejects_prior_variable_binding_mismatch(
    validator: CypherSelfValidator,
) -> None:
    result = validate(
        validator,
        "MATCH (t:Tunnel) MATCH (t)-[:HAS_PORT]->(p:Port) RETURN p.id AS port_id",
    )

    assert result.valid is False
    assert result.errors[0].code == "cypher_schema_reference_invalid"
    assert "HAS_PORT" in result.errors[0].message


def test_undirected_edge_endpoint_is_validated_against_either_direction(
    validator: CypherSelfValidator,
) -> None:
    result = validate(
        validator,
        "MATCH (t:Tunnel)-[:HAS_PORT]-(p:Port) RETURN p.id AS port_id",
    )

    assert result.valid is False
    assert result.errors[0].code == "cypher_schema_reference_invalid"
    assert "HAS_PORT" in result.errors[0].message
