from __future__ import annotations

import pytest

from services.cypher_generator_agent.app.ontology_layer.assets import OntologyAssets
from services.cypher_generator_agent.app.clarification_layer.errors import ClarificationNeeded
from services.cypher_generator_agent.app.infrastructure.errors import EngineeringFailure, ResourceMissing
from services.cypher_generator_agent.app.intent_layer.models import Intent, IntentOutput, InitialShapeField
from services.cypher_generator_agent.app.ontology_layer.shape_finalization import (
    OntologyShapeFinalizer,
)
from services.cypher_generator_agent.app.physical_orchestration.compiler import OntologyPhysicalCompiler


def _intent_output(*, pending_relation: bool = True, projection_expected: bool = True) -> IntentOutput:
    return IntentOutput(
        intent=Intent(
            primary="record_retrieval_query",
            secondary="related_record_query",
            source="fixture",
            decision="accept",
            confidence=0.9,
        ),
        planning_prompt_text="用户想查询相关记录，并返回某些字段。",
        initial_shape={
            "answer_type": InitialShapeField("attribute_table", "taxonomy", "accept", 1.0),
            "projection_expected": InitialShapeField(projection_expected, "taxonomy", "accept", 1.0),
            "relation_resolution_expected": InitialShapeField(
                True,
                "taxonomy",
                "pending" if pending_relation else "accept",
                0.8,
                pending_until="step_3_3" if pending_relation else None,
            ),
            "path_answer_required": InitialShapeField(False, "taxonomy", "accept", 1.0),
            "aggregation_functions": InitialShapeField([], "taxonomy", "accept", 1.0),
            "group_by_required": InitialShapeField(False, "taxonomy", "accept", 1.0),
            "order_required": InitialShapeField(False, "taxonomy", "accept", 1.0),
            "limit_required": InitialShapeField(False, "taxonomy", "accept", 1.0),
            "time_grain_required": InitialShapeField(False, "taxonomy", "accept", 1.0),
        },
        candidates=(),
        rule_signals_used=(),
        diagnostics={},
    )


def _metric_intent_output() -> IntentOutput:
    return IntentOutput(
        intent=Intent(
            primary="metric_query",
            secondary="count_metric_query",
            source="fixture",
            decision="accept",
            confidence=0.9,
        ),
        planning_prompt_text="用户想统计对象数量。",
        initial_shape={
            "answer_type": InitialShapeField("metric", "taxonomy", "accept", 1.0),
            "projection_expected": InitialShapeField(False, "taxonomy", "accept", 1.0),
            "aggregation_required": InitialShapeField(True, "taxonomy", "accept", 1.0),
            "aggregation_functions": InitialShapeField(["count"], "taxonomy", "accept", 1.0),
            "relation_resolution_expected": InitialShapeField(False, "taxonomy", "accept", 1.0),
            "path_answer_required": InitialShapeField(False, "taxonomy", "accept", 1.0),
            "group_by_required": InitialShapeField(False, "taxonomy", "accept", 1.0),
            "order_required": InitialShapeField(False, "taxonomy", "accept", 1.0),
            "limit_required": InitialShapeField(False, "taxonomy", "accept", 1.0),
            "time_grain_required": InitialShapeField(False, "taxonomy", "accept", 1.0),
        },
        candidates=(),
        rule_signals_used=(),
        diagnostics={},
    )


def _entity_list_count_shape_intent_output() -> IntentOutput:
    return IntentOutput(
        intent=Intent(
            primary="record_retrieval_query",
            secondary="entity_list_query",
            source="fixture",
            decision="accept",
            confidence=0.9,
        ),
        planning_prompt_text="用户想查询对象列表。",
        initial_shape={
            "answer_type": InitialShapeField("record_table", "taxonomy", "accept", 1.0),
            "projection_expected": InitialShapeField(False, "taxonomy", "accept", 1.0),
            "aggregation_required": InitialShapeField(True, "shape_signal", "accept", 1.0),
            "aggregation_functions": InitialShapeField(["count"], "shape_signal", "accept", 1.0),
            "relation_resolution_expected": InitialShapeField(False, "taxonomy", "accept", 1.0),
            "path_answer_required": InitialShapeField(False, "taxonomy", "accept", 1.0),
            "group_by_required": InitialShapeField(False, "taxonomy", "accept", 1.0),
            "order_required": InitialShapeField(False, "taxonomy", "accept", 1.0),
            "limit_required": InitialShapeField(False, "taxonomy", "accept", 1.0),
            "time_grain_required": InitialShapeField(False, "taxonomy", "accept", 1.0),
        },
        candidates=(),
        rule_signals_used=("统计", "数量"),
        diagnostics={},
    )


def _entity_list_projection_intent_output() -> IntentOutput:
    return IntentOutput(
        intent=Intent(
            primary="record_retrieval_query",
            secondary="entity_list_query",
            source="fixture",
            decision="accept",
            confidence=0.9,
        ),
        planning_prompt_text="用户想查询对象列表。",
        initial_shape={
            "answer_type": InitialShapeField("record_table", "taxonomy", "accept", 1.0),
            "projection_expected": InitialShapeField(True, "shape_signal", "accept", 1.0),
            "aggregation_required": InitialShapeField(False, "taxonomy", "accept", 1.0),
            "aggregation_functions": InitialShapeField([], "taxonomy", "accept", 1.0),
            "relation_resolution_expected": InitialShapeField(False, "taxonomy", "accept", 1.0),
            "path_answer_required": InitialShapeField(False, "taxonomy", "accept", 1.0),
            "group_by_required": InitialShapeField(False, "taxonomy", "accept", 1.0),
            "order_required": InitialShapeField(False, "taxonomy", "accept", 1.0),
            "limit_required": InitialShapeField(False, "taxonomy", "accept", 1.0),
            "time_grain_required": InitialShapeField(False, "taxonomy", "accept", 1.0),
        },
        candidates=(),
        rule_signals_used=("类型",),
        diagnostics={},
    )


def _mapping() -> dict[str, object]:
    return {
        "ontology_objects": [
            {"object_id": "OO1", "class_id": "Service", "evidence_refs": ["E1"], "order": 1},
            {"object_id": "OO2", "class_id": "Tunnel", "evidence_refs": ["E2"], "order": 2},
            {
                "object_id": "OO3",
                "class_id": "NetworkElement",
                "role_hint": {"relation_hint_id": "ORH1", "relation_id": "TUNNEL_SRC", "role": "source", "source_class": "Tunnel"},
                "evidence_refs": ["E3"],
                "order": 3,
            },
        ],
        "ontology_relation_hints": [
            {"relation_hint_id": "ORH1", "relation_id": "TUNNEL_SRC", "from_class": "Tunnel", "to_class": "NetworkElement", "role": "source", "evidence_refs": ["E3"], "order": 3}
        ],
        "ontology_attributes": [
            {"attribute_ref_id": "OA1", "attribute_id": "Tunnel.ietf_standard", "parent_class": "Tunnel", "attribute_candidates": ["Tunnel.ietf_standard"], "evidence_refs": ["E5"], "order": 5},
            {"attribute_ref_id": "OA2", "attribute_id": "NetworkElement.ip_address", "parent_class": "NetworkElement", "attribute_candidates": ["NetworkElement.ip_address"], "evidence_refs": ["E6"], "order": 6},
        ],
        "ontology_values": [
            {"value_ref_id": "OV1", "value_id": "ServiceQuality.Gold", "constrains_attribute": "Service.quality_of_service", "evidence_refs": ["E4"], "order": 4}
        ],
        "evidence": [
            {"evidence_id": "E1", "mention_id": "m_service_1", "mention_type": "OBJECT", "surface": "服务", "span": [4, 6], "ontology_id": "Service"},
            {"evidence_id": "E2", "mention_id": "m_tunnel_1", "mention_type": "OBJECT", "surface": "隧道", "span": [9, 11], "ontology_id": "Tunnel"},
            {"evidence_id": "E3", "mention_id": "m_source_ne_1", "mention_type": "RELATION", "surface": "源网元", "span": [13, 16], "ontology_id": "TUNNEL_SRC"},
            {"evidence_id": "E4", "mention_id": "m_gold_1", "mention_type": "VALUE", "surface": "金牌", "span": [2, 4], "ontology_id": "ServiceQuality.Gold"},
            {"evidence_id": "E5", "mention_id": "m_ietf_1", "mention_type": "ATTRIBUTE", "surface": "IETF标准", "span": [22, 28], "ontology_id": "Tunnel.ietf_standard"},
            {"evidence_id": "E6", "mention_id": "m_ip_1", "mention_type": "ATTRIBUTE", "surface": "IP地址", "span": [33, 37], "ontology_id": "NetworkElement.ip_address"},
        ],
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
            {"request_id": "PR1", "path_id": "P1", "relation_chain": ["SERVICE_USES_TUNNEL"], "evidence_ids": ["PE1"]},
            {"request_id": "PR2", "path_id": "P2", "relation_chain": ["TUNNEL_SRC"], "evidence_ids": ["PE2"]},
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
                "result": {"node": "n1", "attribute": "NetworkElement.ip_address", "alias": "source_ne_ip_address"},
            },
        ],
        "shape_updates": {
            "filter_level": {"value": "record_filter", "source": "binding", "decision": "accept", "confidence": 1.0}
        },
        "unresolved_items": [],
    }


def _finalizer() -> OntologyShapeFinalizer:
    return OntologyShapeFinalizer(OntologyAssets.from_default_resources())


def test_count_shape_generates_metric_and_suppresses_entity_return() -> None:
    result = _finalizer().finalize(
        intent_output=_entity_list_count_shape_intent_output(),
        ontology_mapping={
            "ontology_objects": [
                {
                    "object_id": "OO1",
                    "class_id": "Service",
                    "selected_roles": ["metric_subject"],
                    "evidence_refs": ["E1"],
                    "order": 1,
                }
            ],
            "ontology_relation_hints": [],
            "ontology_attributes": [],
            "ontology_values": [],
            "evidence": [],
        },
        ontology_path_selection={"selected_paths": [], "shape_updates": {}, "unresolved_items": []},
        coreference={"merged_nodes": [{"node_id": "s1", "class_id": "Service", "mapping_ids": ["OM1"]}], "unresolved_items": []},
        binding={"filters": [], "projections": [], "metric_conditions": [], "shape_updates": {}, "unresolved_items": []},
    )

    assert result.logical_plan.node_returns == ()
    assert [(item.function, item.node, item.alias, item.attribute) for item in result.logical_plan.metrics] == [
        ("count", "s1", "service_count", None)
    ]
    assert OntologyPhysicalCompiler().compile(result.logical_plan).cypher == "MATCH (s:Service)\nRETURN count(s) AS service_count"


def test_count_metric_uses_explicit_attribute_and_suppresses_projection_column() -> None:
    result = _finalizer().finalize(
        intent_output=_metric_intent_output(),
        ontology_mapping={
            "ontology_objects": [
                {
                    "object_id": "OO1",
                    "class_id": "Service",
                    "selected_roles": ["metric_subject"],
                    "evidence_refs": ["E1"],
                    "order": 1,
                }
            ],
            "ontology_relation_hints": [],
            "ontology_attributes": [
                {
                    "attribute_ref_id": "OA1",
                    "attribute_id": "Service.latency",
                    "parent_class": "Service",
                    "attribute_candidates": ["Service.latency"],
                    "evidence_refs": ["E2"],
                    "order": 2,
                }
            ],
            "ontology_values": [],
            "evidence": [],
        },
        ontology_path_selection={"selected_paths": [], "shape_updates": {}, "unresolved_items": []},
        coreference={"merged_nodes": [{"node_id": "s1", "class_id": "Service", "mapping_ids": ["OM1"]}], "unresolved_items": []},
        binding={
            "filters": [],
            "projections": [
                {
                    "item": "延迟@4-6",
                    "kind": "projection",
                    "decision": "accept",
                    "result": {"node": "s1", "attribute": "Service.latency", "alias": "service_latency"},
                }
            ],
            "metric_conditions": [],
            "shape_updates": {},
            "unresolved_items": [],
        },
    )

    assert result.logical_plan.projections == ()
    assert [(item.function, item.node, item.alias, item.attribute) for item in result.logical_plan.metrics] == [
        ("count", "s1", "total", "latency")
    ]
    assert OntologyPhysicalCompiler().compile(result.logical_plan).cypher == "MATCH (s:Service)\nRETURN count(s.latency) AS total"


def test_entity_list_with_explicit_projection_does_not_add_node_return() -> None:
    result = _finalizer().finalize(
        intent_output=_entity_list_projection_intent_output(),
        ontology_mapping={
            "ontology_objects": [
                {
                    "object_id": "OO1",
                    "class_id": "Service",
                    "selected_roles": ["projection_subject"],
                    "evidence_refs": ["E1"],
                    "order": 1,
                }
            ],
            "ontology_relation_hints": [],
            "ontology_attributes": [
                {
                    "attribute_ref_id": "OA1",
                    "attribute_id": "Service.elem_type",
                    "parent_class": "Service",
                    "attribute_candidates": ["Service.elem_type"],
                    "evidence_refs": ["E2"],
                    "order": 2,
                }
            ],
            "ontology_values": [],
            "evidence": [],
        },
        ontology_path_selection={"selected_paths": [], "shape_updates": {}, "unresolved_items": []},
        coreference={"merged_nodes": [{"node_id": "s1", "class_id": "Service", "mapping_ids": ["OM1"]}], "unresolved_items": []},
        binding={
            "filters": [],
            "projections": [
                {
                    "item": "元素类型@6-10",
                    "kind": "projection",
                    "decision": "accept",
                    "result": {"node": "s1", "attribute": "Service.elem_type", "alias": "service_elem_type"},
                }
            ],
            "metric_conditions": [],
            "shape_updates": {},
            "unresolved_items": [],
        },
    )

    assert result.logical_plan.node_returns == ()
    assert [(item.node, item.attribute, item.alias) for item in result.logical_plan.projections] == [
        ("s1", "elem_type", "service_elem_type")
    ]


def test_projection_subject_without_bound_fields_returns_terminal_path_node() -> None:
    result = _finalizer().finalize(
        intent_output=_intent_output(pending_relation=False, projection_expected=True),
        ontology_mapping={
            "ontology_objects": [
                {
                    "object_id": "OO1",
                    "class_id": "Service",
                    "selected_roles": ["path_subject"],
                    "evidence_refs": ["E1"],
                    "order": 1,
                },
                {
                    "object_id": "OO2",
                    "class_id": "Tunnel",
                    "selected_roles": ["path_subject"],
                    "evidence_refs": ["E2"],
                    "order": 2,
                },
                {
                    "object_id": "OO3",
                    "class_id": "NetworkElement",
                    "selected_roles": ["projection_subject", "path_subject"],
                    "evidence_refs": ["E3"],
                    "order": 3,
                },
            ],
            "ontology_relation_hints": [],
            "ontology_attributes": [],
            "ontology_values": [],
            "evidence": [],
        },
        ontology_path_selection={
            "selected_paths": [
                {
                    "request_id": "PR1",
                    "path_id": "P1",
                    "relation_chain": ["SERVICE_USES_TUNNEL", "TUNNEL_SRC"],
                    "evidence_ids": ["PE1"],
                }
            ],
            "shape_updates": {},
            "unresolved_items": [],
        },
        coreference={
            "merged_nodes": [
                {"node_id": "s1", "class_id": "Service", "mapping_ids": ["OO1"]},
                {"node_id": "t1", "class_id": "Tunnel", "mapping_ids": ["OO2"]},
                {"node_id": "n1", "class_id": "NetworkElement", "mapping_ids": ["OO3"]},
            ],
            "unresolved_items": [],
        },
        binding={"filters": [], "projections": [], "metric_conditions": [], "shape_updates": {}, "unresolved_items": []},
    )

    assert result.precheck_result["passed"] is True
    assert result.logical_plan.projections == ()
    assert [(item.node, item.alias) for item in result.logical_plan.node_returns] == [("n1", "ne")]
    assert (
        OntologyPhysicalCompiler().compile(result.logical_plan).cypher
        == "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel)-[:TUNNEL_SRC]->(ne:NetworkElement)\nRETURN ne"
    )


def test_finalize_builds_logical_plan_and_backfills_shape_with_warnings() -> None:
    result = _finalizer().finalize(
        intent_output=_intent_output(),
        ontology_mapping=_mapping(),
        ontology_path_selection=_ontology_path_selection(),
        coreference=_coreference(),
        binding=_binding(),
        unresolved_items=[
            {
                "id": "u_warn",
                "source_stage": "step_3_5",
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
        ("s1", "t1", "SERVICE_USES_TUNNEL"),
        ("t1", "n1", "TUNNEL_SRC"),
    ]
    assert [projection.alias for projection in plan.projections] == ["tunnel_ietf_standard", "source_ne_ip_address"]


def test_finalize_uses_ontology_path_selection_parameter() -> None:
    result = _finalizer().finalize(
        intent_output=_intent_output(),
        ontology_mapping=_mapping(),
        ontology_path_selection=_ontology_path_selection(),
        coreference=_coreference(),
        binding=_binding(),
    )

    assert result.logical_plan.shape["hop_count"].source == "ontology_path_selection"
    assert [(edge.from_node, edge.to_node, edge.relation) for edge in result.logical_plan.edges] == [
        ("s1", "t1", "SERVICE_USES_TUNNEL"),
        ("t1", "n1", "TUNNEL_SRC"),
    ]


def test_blocking_unresolved_is_classified_as_clarification_needed() -> None:
    with pytest.raises(ClarificationNeeded) as exc:
        _finalizer().finalize(
            intent_output=_intent_output(),
            ontology_mapping=_mapping(),
            ontology_path_selection=_ontology_path_selection(),
            coreference=_coreference(),
            binding=_binding(),
            unresolved_items=[
                {
                    "id": "u_path",
                    "source_stage": "step_3_3",
                    "type": "ambiguous_path",
                    "blocking": True,
                    "message": "服务到源网元存在多条候选路径",
                    "suggested_error_type": "ClarificationNeeded",
                    "reason_code": "AMBIGUOUS_PATH",
                    "candidates": [{"candidate_id": "P1", "label": "服务经过隧道的源网元"}],
                }
            ],
        )

    assert exc.value.stage == "step_3_6"
    assert exc.value.clarification["source_step"] == "step_3_3"
    assert exc.value.clarification["precheck_result"]["failures"][0]["reason_code"] == "AMBIGUOUS_PATH"
    assert exc.value.clarification["precheck_result"]["failures"][0]["clarification_options"][0]["option_id"] == "P1"


def test_blocking_unresolved_preserves_coreference_source_step() -> None:
    with pytest.raises(ClarificationNeeded) as exc:
        _finalizer().finalize(
            intent_output=_intent_output(),
            ontology_mapping=_mapping(),
            ontology_path_selection=_ontology_path_selection(),
            coreference=_coreference(),
            binding=_binding(),
            unresolved_items=[
                {
                    "id": "u_coref",
                    "source_stage": "step_3_4_coreference",
                    "type": "ambiguous_coreference",
                    "blocking": True,
                    "message": "两个服务对象是否同指不明确",
                    "suggested_error_type": "ClarificationNeeded",
                    "reason_code": "AMBIGUOUS_COREFERENCE",
                    "options": ["same_instance", "distinct_instances"],
                }
            ],
        )

    assert exc.value.stage == "step_3_6"
    assert exc.value.clarification["source_step"] == "step_3_4_coreference"
    failure = exc.value.clarification["precheck_result"]["failures"][0]
    assert failure["source_step"] == "step_3_4_coreference"
    assert failure["reason_code"] == "AMBIGUOUS_COREFERENCE"


def test_blocking_unresolved_without_suggested_type_is_engineering_failure() -> None:
    with pytest.raises(EngineeringFailure):
        _finalizer().finalize(
            intent_output=_intent_output(),
            ontology_mapping=_mapping(),
            ontology_path_selection=_ontology_path_selection(),
            coreference=_coreference(),
            binding=_binding(),
            unresolved_items=[{"id": "u_bad", "blocking": True, "reason_code": "MISSING_CLASSIFICATION"}],
        )


def test_missing_binding_candidate_can_be_resource_missing() -> None:
    with pytest.raises(ResourceMissing) as exc:
        _finalizer().finalize(
            intent_output=_intent_output(),
            ontology_mapping=_mapping(),
            ontology_path_selection=_ontology_path_selection(),
            coreference=_coreference(),
            binding=_binding(),
            unresolved_items=[
                {
                    "id": "u_missing",
                    "source_stage": "step_3_5",
                    "type": "missing_binding_candidate",
                    "blocking": True,
                    "message": "系统资料中没有可绑定候选",
                    "suggested_error_type": "ResourceMissing",
                    "reason_code": "MISSING_BINDING_CANDIDATE",
                }
            ],
        )

    assert exc.value.stage == "step_3_6"
    assert exc.value.payload["precheck_result"]["failures"][0]["error_type"] == "ResourceMissing"


def test_pending_shape_is_rejected_after_backfill() -> None:
    with pytest.raises(EngineeringFailure) as exc:
        _finalizer().finalize(
            intent_output=_intent_output(),
            ontology_mapping=_mapping(),
            ontology_path_selection={**_ontology_path_selection(), "shape_updates": {}},
            coreference=_coreference(),
            binding=_binding(),
        )

    assert exc.value.payload["precheck_result"]["failures"][0]["check"] == "shape_no_pending"


def test_orphan_user_node_is_rejected_as_clarification() -> None:
    mapping = _mapping()
    mapping["ontology_objects"].append(
        {"object_id": "OO4", "class_id": "Port", "evidence_refs": ["E7"], "order": 7}
    )
    mapping["evidence"].append(
        {"evidence_id": "E7", "mention_id": "m_port_1", "mention_type": "OBJECT", "surface": "端口", "span": [38, 40], "ontology_id": "Port"}
    )
    coreference = _coreference()
    coreference["merged_nodes"].append({"node_id": "p1", "class_id": "Port", "mapping_ids": ["OM7"]})

    with pytest.raises(ClarificationNeeded) as exc:
        _finalizer().finalize(
            intent_output=_intent_output(),
            ontology_mapping=mapping,
            ontology_path_selection=_ontology_path_selection(),
            coreference=coreference,
            binding=_binding(),
        )

    assert exc.value.clarification["precheck_result"]["failures"][0]["check"] == "no_orphan_nodes"


def test_physical_schema_terms_are_rejected_from_logical_plan() -> None:
    with pytest.raises(EngineeringFailure) as exc:
        _finalizer().finalize(
            intent_output=_intent_output(),
            ontology_mapping=_mapping(),
            ontology_path_selection=_ontology_path_selection(),
            coreference={"merged_nodes": [{"node_id": "svc1", "class_id": "node_label:Service", "mapping_ids": ["OM1"]}]},
            binding=_binding(),
        )

    assert exc.value.payload["precheck_result"]["failures"][0]["check"] == "logical_plan_ontology_only"


def test_projection_expected_requires_projection() -> None:
    binding = {**_binding(), "projections": []}

    with pytest.raises(ClarificationNeeded) as exc:
        _finalizer().finalize(
            intent_output=_intent_output(projection_expected=True),
            ontology_mapping=_mapping(),
            ontology_path_selection=_ontology_path_selection(),
            coreference=_coreference(),
            binding=binding,
        )

    failure = exc.value.clarification["precheck_result"]["failures"][0]
    assert failure["check"] == "shape_projection_consistency"
    assert failure["reason_code"] == "MISSING_PROJECTION_TARGET"
    assert [item["label"] for item in failure["clarification_options"]] == [
        "返回 Service 对象",
        "返回 Tunnel 对象",
        "返回 NetworkElement 对象",
    ]
    assert "no_option_reason" not in failure


def test_explicit_projections_override_shape_projection_expected_false() -> None:
    result = _finalizer().finalize(
        intent_output=_intent_output(projection_expected=False),
        ontology_mapping=_mapping(),
        ontology_path_selection=_ontology_path_selection(),
        coreference=_coreference(),
        binding=_binding(),
    )

    assert result.precheck_result["passed"] is True
    assert result.logical_plan.shape["projection_expected"].value is True
    assert result.logical_plan.shape["projection_expected"].source == "shape_finalization.reconciled"
    assert result.trace["shape_backfilled"]["projection_expected"]["source"] == "shape_finalization.reconciled"
    assert [item["reason_code"] for item in result.warnings] == ["PROJECTION_EXPECTATION_RECONCILED"]


def test_single_node_projection_expected_without_fields_returns_entity() -> None:
    result = _finalizer().finalize(
        intent_output=_intent_output(pending_relation=False, projection_expected=True),
        ontology_mapping={
            "ontology_objects": [{"object_id": "OO1", "class_id": "Service", "evidence_refs": ["E1"], "order": 1}],
            "ontology_relation_hints": [],
            "ontology_attributes": [],
            "ontology_values": [
                {
                    "value_ref_id": "OV1",
                    "value_id": "ServiceQuality.Gold",
                    "constrains_attribute": "Service.quality_of_service",
                    "evidence_refs": ["E2"],
                    "order": 2,
                }
            ],
            "evidence": [],
        },
        ontology_path_selection={"selected_paths": [], "shape_updates": {}, "unresolved_items": []},
        coreference={"merged_nodes": [{"node_id": "s1", "class_id": "Service", "mapping_ids": ["OM1"]}], "unresolved_items": []},
        binding={**_binding(), "projections": []},
    )

    assert result.precheck_result["passed"] is True
    assert [(item.node, item.alias) for item in result.logical_plan.node_returns] == [("s1", "s")]
    assert [item["reason_code"] for item in result.warnings] == ["PROJECTION_TARGET_DEFAULTED_TO_ENTITY"]


def test_disconnected_explicit_nodes_require_path_clarification() -> None:
    with pytest.raises(ClarificationNeeded) as exc:
        _finalizer().finalize(
            intent_output=_intent_output(pending_relation=False),
            ontology_mapping=_mapping(),
            ontology_path_selection={"selected_paths": [], "shape_updates": {}, "unresolved_items": []},
            coreference=_coreference(),
            binding=_binding(),
        )

    failure = exc.value.clarification["precheck_result"]["failures"][0]
    assert failure["check"] == "no_cartesian_product"
    assert failure["reason_code"] == "AMBIGUOUS_PATH"
    assert [item["label"] for item in failure["clarification_options"]] == [
        "Service -> Tunnel（SERVICE_USES_TUNNEL）",
        "Tunnel -> NetworkElement（TUNNEL_SRC）",
        "Tunnel -> NetworkElement（TUNNEL_DST）",
        "Tunnel -> NetworkElement（PATH_THROUGH）",
        "Service -> NetworkElement（SERVICE_USES_TUNNEL -> TUNNEL_SRC）",
    ]


def test_metric_query_without_target_object_requires_clarification() -> None:
    with pytest.raises(ClarificationNeeded) as exc:
        _finalizer().finalize(
            intent_output=_metric_intent_output(),
            ontology_mapping={"ontology_objects": [], "ontology_relation_hints": [], "ontology_attributes": [], "ontology_values": [], "evidence": []},
            ontology_path_selection={"selected_paths": [], "shape_updates": {}, "unresolved_items": []},
            coreference={"merged_nodes": [], "unresolved_items": []},
            binding={"filters": [], "projections": [], "metric_conditions": [], "shape_updates": {}, "unresolved_items": []},
        )

    assert exc.value.stage == "step_3_6"
    assert exc.value.clarification["reason_code"] == "MISSING_METRIC_TARGET"
    assert exc.value.clarification["options"] == []
    assert exc.value.clarification["no_option_reason"] == "当前 logical plan 中没有可统计的本体对象。"
