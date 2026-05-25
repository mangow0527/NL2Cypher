from __future__ import annotations

from types import SimpleNamespace

from services.cypher_generator_agent.app.ontology_layer.binding import OntologyBindingService
from services.cypher_generator_agent.app.intent_layer.models import Intent, IntentOutput, InitialShapeField
from services.cypher_generator_agent.app.ontology_layer.models import (
    ContextSignal,
)
from services.cypher_generator_agent.app.ontology_layer.prompts import PromptRegistry


def _intent_output() -> IntentOutput:
    return IntentOutput(
        intent=Intent(
            primary="record_retrieval_query",
            secondary="related_record_query",
            source="rule",
            decision="accept",
            confidence=0.92,
        ),
        planning_prompt_text="用户想查询相关记录，并返回某些字段。",
        initial_shape={
            "projection_expected": InitialShapeField(True, "taxonomy", "accept", 1.0),
            "filter_level": InitialShapeField(None, "taxonomy", "pending", 0.5, pending_until="step_3_5"),
        },
        candidates=(),
        rule_signals_used=("返回",),
        diagnostics={},
    )


def _merged_nodes() -> tuple[dict[str, object], ...]:
    return (
        {"node_id": "s1", "class_id": "Service", "mentions": ["m_service_1"]},
        {"node_id": "t1", "class_id": "Tunnel", "mentions": ["m_tunnel_1", "m_tunnel_2"]},
        {"node_id": "n1", "class_id": "NetworkElement", "mentions": ["m_source_ne_1", "m_source_ne_2"]},
    )


def _mapping(*mention_rows: dict[str, object]) -> dict[str, object]:
    ontology_attributes: list[dict[str, object]] = []
    ontology_values: list[dict[str, object]] = []
    evidence: list[dict[str, object]] = []
    for index, item in enumerate(mention_rows, start=1):
        evidence_id = f"E{index}"
        evidence.append(
            {
                "evidence_id": evidence_id,
                "mention_id": item.get("mention_id", ""),
                "mention_type": item.get("mention_type", ""),
                "surface": item.get("surface", ""),
                "span": item.get("span", [0, 0]),
                "ontology_id": item.get("ontology_id", ""),
            }
        )
        if item.get("ontology_kind") == "attribute":
            ontology_attributes.append(
                {
                    "attribute_ref_id": item.get("mapping_id", f"OA{index}"),
                    "attribute_id": item.get("ontology_id"),
                    "parent_class": item.get("parent_class"),
                    "attribute_candidates": item.get("attribute_candidates", [item.get("ontology_id")]),
                    "evidence_refs": [evidence_id],
                    "order": index,
                }
            )
        else:
            ontology_values.append(
                {
                    "value_ref_id": item.get("mapping_id", f"OV{index}"),
                    "value_id": item.get("ontology_id"),
                    **({"raw_value": item["raw_value"]} if "raw_value" in item else {}),
                    "constrains_attribute": item.get("constrains_attribute"),
                    "evidence_refs": [evidence_id],
                    "order": index,
                }
            )
    return {
        "ontology_objects": [],
        "ontology_relation_hints": [],
        "ontology_attributes": ontology_attributes,
        "ontology_values": ontology_values,
        "evidence": evidence,
    }


def _value_mapping(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "mapping_id": "OM1",
        "mention_id": "m_gold_1",
        "mention_type": "VALUE",
        "surface": "金牌",
        "span": [2, 4],
        "ontology_kind": "enum_value",
        "ontology_id": "ServiceQuality.Gold",
        "raw_value": "Gold",
        "constrains_attribute": "Service.quality_of_service",
    }
    payload.update(overrides)
    return payload


def _attribute_mapping(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "mapping_id": "OM2",
        "mention_id": "m_ietf_1",
        "mention_type": "ATTRIBUTE",
        "surface": "IETF标准",
        "span": [22, 28],
        "ontology_kind": "attribute",
        "ontology_id": "Tunnel.ietf_standard",
        "parent_class": "Tunnel",
    }
    payload.update(overrides)
    return payload


def test_value_binding_prefers_constrains_attribute_and_sets_filter_level() -> None:
    trace = OntologyBindingService().bind(
        ontology_mapping=_mapping(_value_mapping()),
        merged_nodes=_merged_nodes(),
        candidate_family={},
        context_signals=(),
        shape_signals=(),
        intent_output=_intent_output(),
        question="查询金牌服务",
    )

    assert trace.filters[0].result == {
        "node": "s1",
        "attribute": "Service.quality_of_service",
        "operator": "equals",
        "value": "Gold",
        "value_id": "ServiceQuality.Gold",
        "value_kind": "enum",
    }
    assert trace.filters[0].selected == "bc_filter_1"
    assert trace.shape_updates["filter_level"].value == "record_filter"
    assert trace.shape_updates["filter_level"].derived_from == ("Gold",)


def test_enum_value_binding_uses_raw_value_and_keeps_value_id() -> None:
    trace = OntologyBindingService().bind(
        ontology_mapping=_mapping(
            _value_mapping(
                ontology_id="ServiceType.MPLS-VPN",
                surface="MPLS-VPN",
                raw_value="MPLS-VPN",
                constrains_attribute="Service.elem_type",
            )
        ),
        merged_nodes=_merged_nodes(),
        candidate_family={},
        context_signals=(),
        shape_signals=(),
        intent_output=_intent_output(),
        question="查询类型为MPLS-VPN的服务",
    )

    assert trace.filters[0].result == {
        "node": "s1",
        "attribute": "Service.elem_type",
        "operator": "equals",
        "value": "MPLS-VPN",
        "value_id": "ServiceType.MPLS-VPN",
        "value_kind": "enum",
    }


def test_binding_composes_attribute_operator_literal_predicate_before_enum_binding() -> None:
    ontology_mapping = {
        "ontology_objects": [],
        "ontology_relation_hints": [],
        "ontology_attributes": [
            {
                "attribute_ref_id": "OA1",
                "attribute_id": "Service.latency",
                "parent_class": "Service",
                "attribute_candidates": ["Tunnel.latency", "Service.latency"],
                "evidence_refs": ["E1"],
                "order": 1,
            },
            {
                "attribute_ref_id": "OA2",
                "attribute_id": "Service.id",
                "parent_class": "Service",
                "attribute_candidates": ["Service.id"],
                "evidence_refs": ["E5"],
                "order": 5,
            },
        ],
        "ontology_values": [
                {
                    "value_ref_id": "OV1",
                    "value_id": "ServiceQuality.Gold",
                    "raw_value": "Gold",
                    "constrains_attribute": "Service.quality_of_service",
                    "evidence_refs": ["E4"],
                    "order": 4,
            }
        ],
        "evidence": [
            {
                "evidence_id": "E1",
                "mention_id": "m_latency",
                "mention_type": "ATTRIBUTE",
                "surface": "延迟",
                "span": [2, 4],
                "ontology_kind": "attribute",
                "ontology_id": "Service.latency",
                "candidate_refs": ["Tunnel.latency", "Service.latency"],
            },
            {
                "evidence_id": "E2",
                "mention_id": "m_lt",
                "mention_type": "COMPARISON_OPERATOR",
                "surface": "小于",
                "span": [4, 6],
                "ontology_kind": "structured_mention",
                "ontology_id": "OP_LT",
                "metadata": {"cypher_op": "<"},
            },
            {
                "evidence_id": "E3",
                "mention_id": "m_literal",
                "mention_type": "LITERAL_VALUE",
                "surface": "20ms",
                "span": [6, 10],
                "ontology_kind": "structured_mention",
                "ontology_id": "LITERAL_RUNTIME",
                "metadata": {"raw": "20ms"},
            },
            {
                "evidence_id": "E4",
                "mention_id": "m_gold",
                "mention_type": "VALUE",
                "surface": "金牌",
                "span": [13, 15],
                "ontology_kind": "enum_value",
                "ontology_id": "ServiceQuality.Gold",
            },
            {
                "evidence_id": "E5",
                "mention_id": "m_id",
                "mention_type": "ATTRIBUTE",
                "surface": "ID",
                "span": [18, 20],
                "ontology_kind": "attribute",
                "ontology_id": "Service.id",
            },
        ],
    }

    trace = OntologyBindingService().bind(
        ontology_mapping=ontology_mapping,
        merged_nodes=({"node_id": "s1", "class_id": "Service"},),
        candidate_family={},
        context_signals=(),
        shape_signals=(),
        intent_output=_intent_output(),
        question="查询延迟小于20ms的所有金牌服务的ID",
    )

    assert [item.result for item in trace.filters] == [
        {
            "node": "s1",
            "attribute": "Service.latency",
            "operator": "<",
            "value": 20,
            "value_kind": "literal",
            "value_literal": {"raw": "20ms", "parsed": 20, "type": "duration_ms", "unit": "ms"},
        },
        {
            "node": "s1",
                "attribute": "Service.quality_of_service",
                "operator": "equals",
                "value": "Gold",
                "value_id": "ServiceQuality.Gold",
                "value_kind": "enum",
            },
    ]
    assert [item.result for item in trace.projections] == [
        {"node": "s1", "attribute": "Service.id", "alias": "service_id"}
    ]
    assert trace.shape_updates["filter_level"].value == "multi_predicate"


def test_attribute_parent_class_binds_projection_owner_node() -> None:
    trace = OntologyBindingService().bind(
        ontology_mapping=_mapping(_attribute_mapping()),
        merged_nodes=_merged_nodes(),
        candidate_family={},
        context_signals=(),
        shape_signals=(),
        intent_output=_intent_output(),
        question="返回隧道的IETF标准",
    )

    assert trace.projections[0].result == {
        "node": "t1",
        "attribute": "Tunnel.ietf_standard",
        "alias": "tunnel_ietf_standard",
    }
    assert trace.projections[0].decision == "accept"


def test_type_projection_in_service_possessive_context_prefers_service_owner() -> None:
    context_signal = ContextSignal(
        signal_id="S1",
        signal_type="PROXIMAL_MODIFIER",
        text="服务的ID、名称和网元类型",
        span_start=0,
        span_end=13,
        supports=("Service", "NetworkElement.elem_type"),
        strength=0.9,
    )

    trace = OntologyBindingService().bind(
        ontology_mapping=_mapping(
            _attribute_mapping(
                surface="网元类型",
                span=[9, 13],
                ontology_id="NetworkElement.elem_type",
                parent_class="NetworkElement",
                attribute_candidates=["NetworkElement.elem_type"],
            )
        ),
        merged_nodes=_merged_nodes(),
        candidate_family={},
        context_signals=(context_signal,),
        shape_signals=(),
        intent_output=_intent_output(),
        question="查询所有服务的ID、名称和网元类型",
    )

    assert trace.projections[0].result == {
        "node": "s1",
        "attribute": "Service.elem_type",
        "alias": "service_elem_type",
    }
    assert "projection_owner_context" in trace.projections[0].candidates[0].evidence


def test_type_projection_keeps_explicit_source_ne_owner() -> None:
    context_signal = ContextSignal(
        signal_id="S1",
        signal_type="PROXIMAL_MODIFIER",
        text="源网元的网元类型",
        span_start=0,
        span_end=8,
        supports=("NetworkElement", "NetworkElement.elem_type"),
        strength=0.9,
    )

    trace = OntologyBindingService().bind(
        ontology_mapping=_mapping(
            _attribute_mapping(
                surface="网元类型",
                span=[4, 8],
                ontology_id="NetworkElement.elem_type",
                parent_class="NetworkElement",
                attribute_candidates=["NetworkElement.elem_type"],
            )
        ),
        merged_nodes=_merged_nodes(),
        candidate_family={},
        context_signals=(context_signal,),
        shape_signals=(),
        intent_output=_intent_output(),
        question="查询服务源网元的网元类型",
    )

    assert trace.projections[0].result == {
        "node": "n1",
        "attribute": "NetworkElement.elem_type",
        "alias": "source_ne_elem_type",
    }


def test_both_sides_elem_type_projection_binds_path_endpoint_owners() -> None:
    relation_atom = ContextSignal(
        signal_id="S1",
        signal_type="QUESTION_FRAMING_ATOM",
        text="所有服务与隧道之间的连接关系",
        span_start=2,
        span_end=16,
        supports=("question_framing", "QA1", "FIND_OBJECT", "RELATION_PATH"),
        strength=0.9,
    )
    return_atom = ContextSignal(
        signal_id="S2",
        signal_type="QUESTION_FRAMING_ATOM",
        text="双方的元素类型",
        span_start=20,
        span_end=27,
        supports=("question_framing", "QA2", "RETURN_CONTENT"),
        strength=0.9,
    )

    trace = OntologyBindingService().bind(
        ontology_mapping=_mapping(
            _attribute_mapping(
                surface="类型",
                span=[25, 27],
                ontology_id="Tunnel.elem_type",
                parent_class="Tunnel",
                attribute_candidates=[
                    "Fiber.elem_type",
                    "Link.elem_type",
                    "NetworkElement.elem_type",
                    "Port.elem_type",
                    "Service.elem_type",
                    "Tunnel.elem_type",
                ],
            )
        ),
        merged_nodes=_merged_nodes(),
        candidate_family={},
        context_signals=(relation_atom, return_atom),
        shape_signals=(),
        intent_output=_intent_output(),
        question="查询所有服务与隧道之间的连接关系，并返回双方的元素类型。",
    )

    assert [item.result for item in trace.projections] == [
        {"node": "s1", "attribute": "Service.elem_type", "alias": "service_elem_type"},
        {"node": "t1", "attribute": "Tunnel.elem_type", "alias": "tunnel_elem_type"},
    ]
    assert trace.unresolved_items == ()


def test_attribute_family_is_disambiguated_in_binding_stage() -> None:
    trace = OntologyBindingService().bind(
        ontology_mapping=_mapping(
            _attribute_mapping(
                ontology_id="Protocol.standard",
                parent_class="Protocol",
                attribute_candidates=["Protocol.standard", "Tunnel.ietf_standard"],
                candidate_refs=["Protocol.standard", "Tunnel.ietf_standard"],
            )
        ),
        merged_nodes=_merged_nodes(),
        candidate_family={},
        context_signals=(),
        shape_signals=(),
        intent_output=_intent_output(),
        question="返回隧道的IETF标准",
    )

    assert [item.attribute for item in trace.projections[0].candidates] == ["Tunnel.ietf_standard"]
    assert trace.projections[0].result["node"] == "t1"


def test_projection_region_signal_supports_projection_candidate() -> None:
    class Selector:
        def select(self, prompt_name: str, variables: dict[str, object]):
            assert prompt_name == "binding_selection"
            return SimpleNamespace(
                raw_response=(
                    '{"decision":"accept","candidate_id":"bc_projection_2","signal_id":"S1",'
                    '"span_start":19,"span_end":21,"reason":"返回区域和候选线索指向隧道"}'
                )
            )

    shape_signal = ContextSignal(
        signal_id="S1",
        signal_type="PROJECTION_REGION_CUE",
        text="返回",
        span_start=17,
        span_end=19,
        supports=("answer_projection_region", "Tunnel"),
    )

    trace = OntologyBindingService(llm_selector=Selector()).bind(
        ontology_mapping=_mapping(
            _attribute_mapping(
                surface="名称",
                span=[19, 21],
                ontology_id="Service.name",
                parent_class="Service",
                attribute_candidates=["Service.name", "Tunnel.name"],
                candidate_refs=["Service.name", "Tunnel.name"],
            )
        ),
        merged_nodes=_merged_nodes(),
        candidate_family={},
        context_signals=(),
        shape_signals=(shape_signal,),
        intent_output=_intent_output(),
        question="查询服务经过的隧道，返回隧道名称",
    )

    assert trace.projections[0].result == {"node": "t1", "attribute": "Tunnel.name", "alias": "tunnel_name"}
    assert trace.projections[0].selected_by == "llm"
    assert "S1" in trace.projections[0].evidence_ids


def test_gray_area_llm_accept_is_limited_to_existing_candidate_and_signal_ids() -> None:
    class Selector:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def select(self, prompt_name: str, variables: dict[str, object]):
            self.calls.append({"prompt_name": prompt_name, **variables})
            return SimpleNamespace(
                raw_response=(
                    '{"decision":"accept","candidate_id":"bc_projection_2","signal_id":"S1",'
                    '"span_start":10,"span_end":12,"reason":"上下文指向隧道"}'
                )
            )

    signal = ContextSignal(
        "S1",
        "PROXIMAL_MODIFIER",
        "名称",
        10,
        12,
        ("bc_projection_1", "bc_projection_2"),
        1.0,
    )
    selector = Selector()
    trace = OntologyBindingService(llm_selector=selector).bind(
        ontology_mapping=_mapping(
            _attribute_mapping(
                surface="名称",
                span=[10, 12],
                ontology_id="Service.name",
                parent_class=None,
                attribute_candidates=["Service.name", "Tunnel.name"],
                candidate_refs=["Service.name", "Tunnel.name"],
            )
        ),
        merged_nodes=(
            {"node_id": "s1", "class_id": "Service"},
            {"node_id": "t1", "class_id": "Tunnel"},
        ),
        candidate_family={},
        context_signals=(signal,),
        shape_signals=(),
        intent_output=_intent_output(),
        question="查询服务经过的隧道名称",
    )

    assert trace.llm_raw_output.startswith('{"decision":"accept"')
    assert trace.projections[0].selected == "bc_projection_2"
    assert trace.projections[0].selected_by == "llm"
    assert selector.calls[0]["prompt_name"] == "binding_selection"
    assert "bc_projection_2" in str(selector.calls[0]["allowed_candidate_ids"])


def test_illegal_llm_candidate_or_signal_is_rejected_as_unresolved() -> None:
    class Selector:
        def select(self, prompt_name: str, variables: dict[str, object]):
            return SimpleNamespace(
                raw_response=(
                    '{"decision":"accept","candidate_id":"bc_projection_999","signal_id":"S999",'
                    '"span_start":10,"span_end":12,"reason":"bad"}'
                )
            )

    trace = OntologyBindingService(llm_selector=Selector()).bind(
        ontology_mapping=_mapping(
            _attribute_mapping(
                surface="名称",
                span=[10, 12],
                ontology_id="Service.name",
                parent_class=None,
                attribute_candidates=["Service.name", "Tunnel.name"],
                candidate_refs=["Service.name", "Tunnel.name"],
            )
        ),
        merged_nodes=(
            {"node_id": "s1", "class_id": "Service"},
            {"node_id": "t1", "class_id": "Tunnel"},
        ),
        candidate_family={},
        context_signals=(ContextSignal("S1", "PROXIMAL_MODIFIER", "名称", 10, 12, ("bc_projection_1",), 1.0),),
        shape_signals=(),
        intent_output=_intent_output(),
        question="查询名称",
    )

    assert trace.projections == ()
    assert trace.unresolved_items[0]["reason_code"] == "invalid_llm_binding"
    assert "unknown candidate_id" in trace.unresolved_items[0]["reason"]
    assert [option["label"] for option in trace.unresolved_items[0]["options"]] == [
        "名称 -> Service.name",
        "名称 -> Tunnel.name",
    ]


def test_missing_binding_candidate_is_reported() -> None:
    trace = OntologyBindingService().bind(
        ontology_mapping=_mapping(_value_mapping(constrains_attribute="Customer.level")),
        merged_nodes=_merged_nodes(),
        candidate_family={},
        context_signals=(),
        shape_signals=(),
        intent_output=_intent_output(),
        question="查询金牌客户",
    )

    assert trace.filters == ()
    assert trace.unresolved_items[0]["reason_code"] == "missing_binding_candidate"
    assert trace.unresolved_items[0]["options"] == []
    assert trace.unresolved_items[0]["no_option_reason"] == "没有可用的绑定候选。"


def test_binding_prompt_is_step_3_5_specific_and_accepts_binding_candidate_ids() -> None:
    rendered = PromptRegistry.default().render(
        "binding_selection",
        {
            "question": "返回隧道名称",
            "surface": "名称",
            "span_start": 10,
            "span_end": 12,
            "binding_candidate_list_with_ids": "bc_projection_1: owner=s1 attribute=Service.name\nbc_projection_2: owner=t1 attribute=Tunnel.name",
            "signal_list_with_ids": "S1: text=隧道名称 span=8-12 supports=bc_projection_2",
            "allowed_candidate_ids": "bc_projection_1,bc_projection_2",
            "allowed_signal_ids": "S1",
        },
    )

    assert "为待绑定片段选择它应该绑定到哪个候选" in rendered.prompt
    assert "COMMON_PREFIX" not in rendered.prompt
    assert rendered.candidate_ids == ("bc_projection_1", "bc_projection_2")
    parsed = PromptRegistry.default().validate_output(
        rendered,
        "选择 bc_projection_2。理由：邻近修饰指向隧道。",
    )
    assert parsed["candidate_id"] == "bc_projection_2"
