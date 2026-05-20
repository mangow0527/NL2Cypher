from __future__ import annotations

import pytest

from services.cypher_generator_agent.app.ontology_generation.assets import OntologyAssets
from services.cypher_generator_agent.app.ontology_generation.errors import (
    ClarificationNeeded,
    EngineeringFailure,
    ResourceMissing,
)
from services.cypher_generator_agent.app.ontology_generation.models import IntentIdentity, IntentTrace, ShapeField
from services.cypher_generator_agent.app.ontology_generation.shape_finalization import (
    OntologyShapeFinalizer,
)


def _intent_trace(*, pending_relation: bool = True, projection_expected: bool = True) -> IntentTrace:
    return IntentTrace(
        intent=IntentIdentity(
            primary="record_retrieval_query",
            secondary="related_record_query",
            source="fixture",
            decision="accept",
            confidence=0.9,
        ),
        shape={
            "answer_type": ShapeField("attribute_table", "taxonomy", "accept", 1.0),
            "projection_expected": ShapeField(projection_expected, "taxonomy", "accept", 1.0),
            "relation_resolution_expected": ShapeField(
                True,
                "taxonomy",
                "pending" if pending_relation else "accept",
                0.8,
                pending_until="step_2_3" if pending_relation else None,
            ),
            "path_answer_required": ShapeField(False, "taxonomy", "accept", 1.0),
            "aggregation_functions": ShapeField([], "taxonomy", "accept", 1.0),
            "group_by_required": ShapeField(False, "taxonomy", "accept", 1.0),
            "order_required": ShapeField(False, "taxonomy", "accept", 1.0),
            "limit_required": ShapeField(False, "taxonomy", "accept", 1.0),
            "time_grain_required": ShapeField(False, "taxonomy", "accept", 1.0),
        },
        candidates=(),
        rule_signals_used=(),
    )


def _mapping() -> dict[str, object]:
    return {
        "mapped_mentions": [
            {
                "mapping_id": "OM1",
                "mention_id": "m_service_1",
                "mention_type": "OBJECT",
                "surface": "服务",
                "span": [4, 6],
                "ontology_kind": "class",
                "ontology_id": "Service",
            },
            {
                "mapping_id": "OM2",
                "mention_id": "m_tunnel_1",
                "mention_type": "OBJECT",
                "surface": "隧道",
                "span": [9, 11],
                "ontology_kind": "class",
                "ontology_id": "Tunnel",
            },
            {
                "mapping_id": "OM3",
                "mention_id": "m_source_ne_1",
                "mention_type": "RELATION",
                "surface": "源网元",
                "span": [13, 16],
                "ontology_kind": "relation_role",
                "ontology_id": "TUNNEL_SRC",
                "role": "source",
                "target_class": "NetworkElement",
            },
            {
                "mapping_id": "OM4",
                "mention_id": "m_gold_1",
                "mention_type": "VALUE",
                "surface": "金牌",
                "span": [2, 4],
                "ontology_kind": "enum_value",
                "ontology_id": "ServiceQuality.Gold",
                "constrains_attribute": "Service.quality_of_service",
            },
            {
                "mapping_id": "OM5",
                "mention_id": "m_ietf_1",
                "mention_type": "ATTRIBUTE",
                "surface": "IETF标准",
                "span": [22, 28],
                "ontology_kind": "attribute",
                "ontology_id": "Tunnel.ietf_standard",
                "parent_class": "Tunnel",
            },
            {
                "mapping_id": "OM6",
                "mention_id": "m_ip_1",
                "mention_type": "ATTRIBUTE",
                "surface": "IP地址",
                "span": [33, 37],
                "ontology_kind": "attribute",
                "ontology_id": "NetworkElement.ip_address",
                "parent_class": "NetworkElement",
            },
        ]
    }


def _coreference() -> dict[str, object]:
    return {
        "merged_nodes": [
            {"node_id": "s1", "class_id": "Service", "mapping_ids": ["OM1"]},
            {"node_id": "t1", "class_id": "Tunnel", "mapping_ids": ["OM2"]},
            {"node_id": "n1", "class_id": "NetworkElement", "mapping_ids": ["OM3"]},
        ],
        "unresolved_items": [],
    }


def _ontology_path_selection() -> dict[str, object]:
    return {
        "selected_paths": [
            {"request_id": "PR1", "path_id": "P1", "relation_chain": ["REL_SERVICE_USES_TUNNEL"], "evidence_ids": ["PE1"]},
            {"request_id": "PR2", "path_id": "P2", "relation_chain": ["REL_TUNNEL_SRC"], "evidence_ids": ["PE2"]},
        ],
        "shape_updates": {
            "hop_count": {"value": 2, "source": "ontology_path_selection", "decision": "accept", "confidence": 1.0},
            "relation_chain_type": {"value": "fixed_chain", "source": "ontology_path_selection", "decision": "accept", "confidence": 1.0},
        },
        "unresolved_items": [],
    }


def _binding() -> dict[str, object]:
    return {
        "filters": [
            {
                "item": "金牌@2-4",
                "kind": "filter",
                "decision": "accept",
                "result": {
                    "node": "s1",
                    "attribute": "Service.quality_of_service",
                    "operator": "equals",
                    "value": "ServiceQuality.Gold",
                },
            }
        ],
        "projections": [
            {
                "item": "IETF标准@22-28",
                "kind": "projection",
                "decision": "accept",
                "result": {"node": "t1", "attribute": "Tunnel.ietf_standard", "alias": "tunnel_ietf_standard"},
            },
            {
                "item": "IP地址@33-37",
                "kind": "projection",
                "decision": "accept",
                "result": {"node": "n1", "attribute": "NetworkElement.ip_address", "alias": "source_ne_ip"},
            },
        ],
        "shape_updates": {
            "filter_level": {"value": "record_filter", "source": "binding", "decision": "accept", "confidence": 1.0}
        },
        "unresolved_items": [],
    }


def _finalizer() -> OntologyShapeFinalizer:
    return OntologyShapeFinalizer(OntologyAssets.from_default_resources())


def test_finalize_builds_logical_plan_and_backfills_shape_with_warnings() -> None:
    result = _finalizer().finalize(
        intent_trace=_intent_trace(),
        ontology_mapping=_mapping(),
        ontology_path_selection=_ontology_path_selection(),
        coreference=_coreference(),
        binding=_binding(),
        unresolved_items=[
            {
                "id": "u_warn",
                "source_stage": "step_2_5",
                "type": "ambiguous_attribute_binding",
                "blocking": False,
                "message": "projection candidate kept as warning",
                "suggested_error_type": "ClarificationNeeded",
                "reason_code": "AMBIGUOUS_ATTRIBUTE_BINDING",
            }
        ],
    )

    plan = result.logical_plan
    assert result.precheck_result["passed"] is True
    assert result.warnings[0]["id"] == "u_warn"
    assert plan.shape["relation_resolution_expected"].decision == "accept"
    assert plan.shape["hop_count"].value == 2
    assert plan.shape["relation_chain_type"].value == "fixed_chain"
    assert plan.shape["filter_level"].value == "record_filter"
    assert [(edge.from_node, edge.to_node, edge.relation) for edge in plan.edges] == [
        ("s1", "t1", "REL_SERVICE_USES_TUNNEL"),
        ("t1", "n1", "REL_TUNNEL_SRC"),
    ]
    assert [projection.alias for projection in plan.projections] == ["tunnel_ietf_standard", "source_ne_ip"]


def test_finalize_keeps_legacy_path_filling_parameter_compatible() -> None:
    result = _finalizer().finalize(
        intent_trace=_intent_trace(),
        ontology_mapping=_mapping(),
        path_filling=_ontology_path_selection(),
        coreference=_coreference(),
        binding=_binding(),
    )

    assert result.logical_plan.shape["hop_count"].source == "ontology_path_selection"
    assert [(edge.from_node, edge.to_node, edge.relation) for edge in result.logical_plan.edges] == [
        ("s1", "t1", "REL_SERVICE_USES_TUNNEL"),
        ("t1", "n1", "REL_TUNNEL_SRC"),
    ]


def test_blocking_unresolved_is_classified_as_clarification_needed() -> None:
    with pytest.raises(ClarificationNeeded) as exc:
        _finalizer().finalize(
            intent_trace=_intent_trace(),
            ontology_mapping=_mapping(),
            ontology_path_selection=_ontology_path_selection(),
            coreference=_coreference(),
            binding=_binding(),
            unresolved_items=[
                {
                    "id": "u_path",
                    "source_stage": "step_2_3",
                    "type": "ambiguous_path",
                    "blocking": True,
                    "message": "服务到源网元存在多条候选路径",
                    "suggested_error_type": "ClarificationNeeded",
                    "reason_code": "AMBIGUOUS_PATH",
                    "candidates": [{"candidate_id": "P1", "label": "服务经过隧道的源网元"}],
                }
            ],
        )

    assert exc.value.stage == "step_2_6"
    assert exc.value.clarification["precheck_result"]["failures"][0]["reason_code"] == "AMBIGUOUS_PATH"
    assert exc.value.clarification["precheck_result"]["failures"][0]["clarification_options"][0]["option_id"] == "P1"


def test_blocking_unresolved_without_suggested_type_is_engineering_failure() -> None:
    with pytest.raises(EngineeringFailure):
        _finalizer().finalize(
            intent_trace=_intent_trace(),
            ontology_mapping=_mapping(),
            ontology_path_selection=_ontology_path_selection(),
            coreference=_coreference(),
            binding=_binding(),
            unresolved_items=[{"id": "u_bad", "blocking": True, "reason_code": "MISSING_CLASSIFICATION"}],
        )


def test_missing_binding_candidate_can_be_resource_missing() -> None:
    with pytest.raises(ResourceMissing) as exc:
        _finalizer().finalize(
            intent_trace=_intent_trace(),
            ontology_mapping=_mapping(),
            ontology_path_selection=_ontology_path_selection(),
            coreference=_coreference(),
            binding=_binding(),
            unresolved_items=[
                {
                    "id": "u_missing",
                    "source_stage": "step_2_5",
                    "type": "missing_binding_candidate",
                    "blocking": True,
                    "message": "系统资料中没有可绑定候选",
                    "suggested_error_type": "ResourceMissing",
                    "reason_code": "MISSING_BINDING_CANDIDATE",
                }
            ],
        )

    assert exc.value.stage == "step_2_6"
    assert exc.value.payload["precheck_result"]["failures"][0]["error_type"] == "ResourceMissing"


def test_pending_shape_is_rejected_after_backfill() -> None:
    with pytest.raises(EngineeringFailure) as exc:
        _finalizer().finalize(
            intent_trace=_intent_trace(),
            ontology_mapping=_mapping(),
            ontology_path_selection={**_ontology_path_selection(), "shape_updates": {}},
            coreference=_coreference(),
            binding=_binding(),
        )

    assert exc.value.payload["precheck_result"]["failures"][0]["check"] == "shape_no_pending"


def test_orphan_user_node_is_rejected_as_clarification() -> None:
    mapping = _mapping()
    mapping["mapped_mentions"].append(
        {
            "mapping_id": "OM7",
            "mention_id": "m_port_1",
            "mention_type": "OBJECT",
            "surface": "端口",
            "span": [38, 40],
            "ontology_kind": "class",
            "ontology_id": "Port",
        }
    )
    coreference = _coreference()
    coreference["merged_nodes"].append({"node_id": "p1", "class_id": "Port", "mapping_ids": ["OM7"]})

    with pytest.raises(ClarificationNeeded) as exc:
        _finalizer().finalize(
            intent_trace=_intent_trace(),
            ontology_mapping=mapping,
            ontology_path_selection=_ontology_path_selection(),
            coreference=coreference,
            binding=_binding(),
        )

    assert exc.value.clarification["precheck_result"]["failures"][0]["check"] == "no_orphan_nodes"


def test_physical_schema_terms_are_rejected_from_logical_plan() -> None:
    with pytest.raises(EngineeringFailure) as exc:
        _finalizer().finalize(
            intent_trace=_intent_trace(),
            ontology_mapping=_mapping(),
            ontology_path_selection=_ontology_path_selection(),
            coreference={"merged_nodes": [{"node_id": "svc1", "class_id": "node_label:Service", "mapping_ids": ["OM1"]}]},
            binding=_binding(),
        )

    assert exc.value.payload["precheck_result"]["failures"][0]["check"] == "logical_plan_ontology_only"


def test_projection_expected_requires_projection() -> None:
    binding = {**_binding(), "projections": []}

    with pytest.raises(EngineeringFailure) as exc:
        _finalizer().finalize(
            intent_trace=_intent_trace(projection_expected=True),
            ontology_mapping=_mapping(),
            ontology_path_selection=_ontology_path_selection(),
            coreference=_coreference(),
            binding=binding,
        )

    assert exc.value.payload["precheck_result"]["failures"][0]["check"] == "shape_projection_consistency"
