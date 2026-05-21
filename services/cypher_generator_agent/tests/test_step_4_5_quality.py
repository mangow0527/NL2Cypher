from __future__ import annotations

from services.cypher_generator_agent.app.intent_layer.models import Intent, InitialShapeField
from services.cypher_generator_agent.app.ontology_layer.assets import OntologyAssets
from services.cypher_generator_agent.app.ontology_layer.models import (
    OntologyLogicalPlan,
    PlanEdge,
    PlanFilter,
    PlanNode,
    PlanProjection,
)
from services.cypher_generator_agent.app.physical_orchestration.compiler import OntologyPhysicalCompiler
from services.cypher_generator_agent.app.validation_layer.validator import OntologySemanticValidator


def _intent() -> Intent:
    return Intent(
        primary="record_retrieval_query",
        secondary="related_record_query",
        source="fixture",
        decision="accept",
        confidence=1.0,
    )


def _shape() -> dict[str, InitialShapeField]:
    return {
        "answer_type": InitialShapeField(
            value="attribute_table",
            source="fixture",
            decision="accept",
            confidence=1.0,
        )
    }


def test_step_4_reports_missing_edge_endpoint_without_crashing() -> None:
    plan = OntologyLogicalPlan(
        root_operation="SELECT",
        intent=_intent(),
        shape=_shape(),
        nodes=(PlanNode(id="s1", type="Service", alias="s"),),
        edges=(PlanEdge(from_node="s1", to_node="t_missing", relation="SERVICE_USES_TUNNEL", edge_type="direct"),),
        projections=(PlanProjection(node="s1", attribute="name", alias="service_name"),),
    )

    trace = OntologySemanticValidator(OntologyAssets.from_default_resources()).validate(plan)
    checks = trace.to_dict()["checks"]

    assert trace.accepted is False
    assert any(
        check["check"] == "edge_nodes_exist"
        and check["edge"] == "SERVICE_USES_TUNNEL"
        and check["accepted"] is False
        for check in checks
    )


def test_step_4_validates_filter_attribute_owner() -> None:
    plan = OntologyLogicalPlan(
        root_operation="SELECT",
        intent=_intent(),
        shape=_shape(),
        nodes=(
            PlanNode(
                id="s1",
                type="Service",
                alias="s",
                filters=(PlanFilter(node="s1", attr="ip_address", operator="=", value="10.0.0.1"),),
            ),
        ),
        edges=(),
        projections=(PlanProjection(node="s1", attribute="name", alias="service_name"),),
    )

    trace = OntologySemanticValidator(OntologyAssets.from_default_resources()).validate(plan)
    checks = trace.to_dict()["checks"]

    assert trace.accepted is False
    assert any(
        check["check"] == "filter_attribute_exists"
        and check["attribute"] == "Service.ip_address"
        and check["accepted"] is False
        for check in checks
    )


def test_step_5_does_not_duplicate_multi_filter_expression() -> None:
    plan = OntologyLogicalPlan(
        root_operation="SELECT",
        intent=_intent(),
        shape=_shape(),
        nodes=(
            PlanNode(
                id="s1",
                type="Service",
                alias="s",
                filters=(
                    PlanFilter(node="s1", attr="quality_of_service", operator="=", value="ServiceQuality.Gold"),
                    PlanFilter(node="s1", attr="bandwidth", operator=">", value=100),
                ),
            ),
        ),
        edges=(),
        projections=(PlanProjection(node="s1", attribute="name", alias="service_name"),),
    )

    cypher = OntologyPhysicalCompiler().compile(plan).cypher

    assert cypher == (
        "MATCH (s:Service)\n"
        "WHERE s.quality_of_service = 'Gold' AND s.bandwidth > 100\n"
        "RETURN s.name AS service_name"
    )
