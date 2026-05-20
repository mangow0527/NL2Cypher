from __future__ import annotations

from types import SimpleNamespace

from services.cypher_generator_agent.app.ontology_generation.binding import OntologyBindingService
from services.cypher_generator_agent.app.ontology_generation.models import (
    ContextSignal,
    IntentIdentity,
    IntentTrace,
    ShapeField,
)
from services.cypher_generator_agent.app.ontology_generation.prompts import PromptRegistry


def _intent_trace() -> IntentTrace:
    return IntentTrace(
        intent=IntentIdentity(
            primary="record_retrieval_query",
            secondary="related_record_query",
            source="rule",
            decision="accept",
            confidence=0.92,
        ),
        shape={
            "projection_expected": ShapeField(True, "taxonomy", "accept", 1.0),
            "filter_level": ShapeField(None, "taxonomy", "pending", 0.5, pending_until="step_2_5"),
        },
        candidates=(),
        rule_signals_used=("返回",),
    )


def _merged_nodes() -> tuple[dict[str, object], ...]:
    return (
        {"node_id": "s1", "class_id": "Service", "mentions": ["m_service_1"]},
        {"node_id": "t1", "class_id": "Tunnel", "mentions": ["m_tunnel_1", "m_tunnel_2"]},
        {"node_id": "n1", "class_id": "NetworkElement", "mentions": ["m_source_ne_1", "m_source_ne_2"]},
    )


def _mapping(*mapped_mentions: dict[str, object]) -> dict[str, object]:
    return {"mapped_mentions": list(mapped_mentions)}


def _value_mapping(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "mapping_id": "OM1",
        "mention_id": "m_gold_1",
        "mention_type": "VALUE",
        "surface": "金牌",
        "span": [2, 4],
        "ontology_kind": "enum_value",
        "ontology_id": "ServiceQuality.Gold",
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
        intent_trace=_intent_trace(),
        question="查询金牌服务",
    )

    assert trace.filters[0].result == {
        "node": "s1",
        "attribute": "Service.quality_of_service",
        "operator": "equals",
        "value": "ServiceQuality.Gold",
    }
    assert trace.filters[0].selected == "bc_filter_1"
    assert trace.shape_updates["filter_level"].value == "record_filter"
    assert trace.shape_updates["filter_level"].derived_from == ("ServiceQuality.Gold",)


def test_attribute_parent_class_binds_projection_owner_node() -> None:
    trace = OntologyBindingService().bind(
        ontology_mapping=_mapping(_attribute_mapping()),
        merged_nodes=_merged_nodes(),
        candidate_family={},
        context_signals=(),
        shape_signals=(),
        intent_trace=_intent_trace(),
        question="返回隧道的IETF标准",
    )

    assert trace.projections[0].result == {
        "node": "t1",
        "attribute": "Tunnel.ietf_standard",
        "alias": "tunnel_ietf_standard",
    }
    assert trace.projections[0].decision == "accept"


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
        intent_trace=_intent_trace(),
        question="返回隧道的IETF标准",
    )

    assert [item.attribute for item in trace.projections[0].candidates] == ["Tunnel.ietf_standard"]
    assert trace.projections[0].result["node"] == "t1"


def test_projection_region_signal_supports_projection_candidate() -> None:
    shape_signal = ContextSignal(
        signal_id="S1",
        signal_type="PROJECTION_REGION_CUE",
        text="返回",
        span_start=17,
        span_end=19,
        supports=("answer_projection_region", "Tunnel"),
    )

    trace = OntologyBindingService().bind(
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
        intent_trace=_intent_trace(),
        question="查询服务经过的隧道，返回隧道名称",
    )

    assert trace.projections[0].result == {"node": "t1", "attribute": "Tunnel.name", "alias": "tunnel_name"}
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
        intent_trace=_intent_trace(),
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
        intent_trace=_intent_trace(),
        question="查询名称",
    )

    assert trace.projections == ()
    assert trace.unresolved_items[0]["reason_code"] == "invalid_llm_binding"
    assert "unknown candidate_id" in trace.unresolved_items[0]["reason"]


def test_missing_binding_candidate_is_reported() -> None:
    trace = OntologyBindingService().bind(
        ontology_mapping=_mapping(_value_mapping(constrains_attribute="Customer.level")),
        merged_nodes=_merged_nodes(),
        candidate_family={},
        context_signals=(),
        shape_signals=(),
        intent_trace=_intent_trace(),
        question="查询金牌客户",
    )

    assert trace.filters == ()
    assert trace.unresolved_items[0]["reason_code"] == "missing_binding_candidate"


def test_binding_prompt_is_step_2_5_specific_and_accepts_binding_candidate_ids() -> None:
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

    assert "属性/值/投影绑定候选选择器" in rendered.prompt
    assert "COMMON_PREFIX" not in rendered.prompt
    assert rendered.candidate_ids == ("bc_projection_1", "bc_projection_2")
    parsed = PromptRegistry.default().validate_output(
        rendered,
        '{"decision":"accept","candidate_id":"bc_projection_2","signal_id":"S1","span_start":10,"span_end":12,"reason":"邻近修饰"}',
    )
    assert parsed["candidate_id"] == "bc_projection_2"
