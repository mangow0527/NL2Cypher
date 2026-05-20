from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.cypher_generator_agent.app.ontology_layer.assets import OntologyAssets
from services.cypher_generator_agent.app.ontology_layer.models import (
    IntentIdentity,
    IntentTrace,
    ShapeField,
)
from services.cypher_generator_agent.app.ontology_layer.ontology_path_selection import (
    OntologyPathSelectionValidationError,
    OntologyPathSelectionService,
    PathRequest,
    build_candidate_paths,
    build_path_requests,
)


def _intent_trace() -> IntentTrace:
    return IntentTrace(
        intent=IntentIdentity(
            primary="record_retrieval_query",
            secondary="related_record_query",
            source="rule",
            decision="accept",
            confidence=0.91,
        ),
        shape={
            "projection_expected": ShapeField(True, "taxonomy", "accept", 1.0),
            "relation_resolution_expected": ShapeField(True, "taxonomy", "pending", 0.8, pending_until="step_2_3"),
        },
        candidates=(),
        rule_signals_used=("返回",),
    )


def _ontology_mapping() -> dict[str, object]:
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
                "object_candidate_id": "SM1",
                "selected_roles": ["filter_subject", "path_subject"],
            },
            {
                "mapping_id": "OM2",
                "mention_id": "m_path_through_1",
                "mention_type": "RELATION",
                "surface": "经过",
                "span": [6, 8],
                "ontology_kind": "relation",
                "ontology_id": "REL_SERVICE_USES_TUNNEL",
                "domain_class": "Service",
                "range_class": "Tunnel",
                "object_candidate_id": "SM2",
                "selected_roles": ["path_subject"],
            },
            {
                "mapping_id": "OM3",
                "mention_id": "m_source_ne_1",
                "mention_type": "RELATION",
                "surface": "源网元",
                "span": [13, 16],
                "ontology_kind": "relation_role",
                "ontology_id": "REL_TUNNEL_SRC",
                "role": "source",
                "target_class": "NetworkElement",
                "object_candidate_id": "SM3",
                "selected_roles": ["path_subject"],
            },
        ]
    }


def test_builds_path_requests_from_step_2_2_ontology_mapping() -> None:
    requests = build_path_requests(_ontology_mapping(), _intent_trace())

    assert [item.request_id for item in requests] == ["PR1", "PR2"]
    assert requests[0].from_class == "Service"
    assert requests[0].to_class == "Tunnel"
    assert requests[0].relation_hint == "REL_SERVICE_USES_TUNNEL"
    assert requests[0].source_mapping_id == "OM2"
    assert requests[1].from_class == "Tunnel"
    assert requests[1].to_class == "NetworkElement"
    assert requests[1].relation_hint == "REL_TUNNEL_SRC"
    assert requests[1].role == "source"


def test_build_path_requests_ignores_mappings_without_path_roles() -> None:
    mapping = _ontology_mapping()
    mapping["mapped_mentions"].append(
        {
            "mapping_id": "OM4",
            "ontology_kind": "relation",
            "ontology_id": "REL_TUNNEL_PROTO",
            "surface": "协议",
            "span": [20, 22],
            "domain_class": "Tunnel",
            "range_class": "Protocol",
            "selected_roles": ["projection_target"],
        }
    )

    requests = build_path_requests(mapping, _intent_trace())

    assert [item.source_mapping_id for item in requests] == ["OM2", "OM3"]


def test_enumerates_explicit_role_semantic_and_default_candidate_paths_without_graph_duplicates() -> None:
    assets = OntologyAssets.from_default_resources()
    requests = build_path_requests(
        {
            "mapped_mentions": [
                {
                    "mapping_id": "OM1",
                    "ontology_kind": "relation",
                    "ontology_id": "REL_SERVICE_USES_TUNNEL",
                    "surface": "经过",
                    "span": [0, 2],
                    "domain_class": "Service",
                    "range_class": "Tunnel",
                },
                {
                    "mapping_id": "OM2",
                    "ontology_kind": "relation_role",
                    "ontology_id": "REL_TUNNEL_SRC",
                    "role": "source",
                    "target_class": "NetworkElement",
                    "surface": "源网元",
                    "span": [3, 6],
                },
                {
                    "mapping_id": "OM3",
                    "ontology_kind": "semantic_object",
                    "ontology_id": "service_source_ne",
                    "surface": "服务源网元",
                    "span": [0, 6],
                },
            ]
        },
        _intent_trace(),
    )

    candidates = build_candidate_paths(requests, assets)
    chains_by_source = {(item.request_id, item.source): item.relation_chain for item in candidates}

    assert chains_by_source[("PR1", "explicit_relation_mapping")] == ("REL_SERVICE_USES_TUNNEL",)
    assert chains_by_source[("PR2", "role_relation_mapping")] == ("REL_TUNNEL_SRC",)
    assert chains_by_source[("PR3", "semantic_traversal")] == ("REL_SERVICE_USES_TUNNEL", "REL_TUNNEL_SRC")
    assert all(item.source != "ontology_relation_graph" for item in candidates)


def test_uses_ontology_relation_graph_only_as_fallback() -> None:
    assets = OntologyAssets.from_default_resources()
    request = PathRequest(
        request_id="PR1",
        from_class="Tunnel",
        to_class="Port",
        source_mapping_id="OM1",
        source_surface="端口",
        source_kind="relation_role",
    )

    candidates = build_candidate_paths((request,), assets)

    assert [(item.source, item.relation_chain) for item in candidates] == [
        ("ontology_relation_graph", ("REL_TUNNEL_SRC", "REL_HAS_PORT")),
        ("ontology_relation_graph", ("REL_TUNNEL_DST", "REL_HAS_PORT")),
        ("ontology_relation_graph", ("REL_PATH_THROUGH", "REL_HAS_PORT")),
    ]


def test_auto_accepts_single_candidate_requests_without_calling_llm() -> None:
    class Selector:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def select(self, prompt_name: str, variables: dict[str, object]):
            self.calls.append({"prompt_name": prompt_name, **variables})
            raise AssertionError("single-candidate path requests must not call the LLM")

    service = OntologyPathSelectionService(assets=OntologyAssets.from_default_resources(), llm_selector=Selector())

    trace = service.fill(
        ontology_mapping=_ontology_mapping(),
        intent_trace=_intent_trace(),
        question="查询金牌服务经过的隧道及其源网元",
    )

    assert trace.llm_raw_output == ""
    assert [(item.request_id, item.path_id) for item in trace.selected_paths] == [("PR1", "P1"), ("PR2", "P2")]
    assert [item.evidence_ids for item in trace.selected_paths] == [("PE1",), ("PE2",)]
    assert [item.selected_by for item in trace.selected_paths] == ["auto_single_candidate", "auto_single_candidate"]
    assert trace.shape_updates["hop_count"].value == 2
    assert trace.shape_updates["relation_chain_type"].value == "fixed_chain"
    assert service.llm_selector.calls == []


def test_calls_llm_only_for_multi_candidate_requests_with_local_cards() -> None:
    class Selector:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def select(self, prompt_name: str, variables: dict[str, object]):
            self.calls.append({"prompt_name": prompt_name, **variables})
            return SimpleNamespace(raw_response="选择 PR2：P2。理由：源网元明确要求选择隧道源端。")

    mapping = _ontology_mapping()
    mapping["mapped_mentions"][2] = {
        "mapping_id": "OM3",
        "mention_id": "m_source_ne_1",
        "mention_type": "RELATION",
        "surface": "源网元",
        "span": [13, 16],
        "ontology_kind": "relation_role",
        "role": "source",
        "domain_class": "Tunnel",
        "target_class": "NetworkElement",
        "object_candidate_id": "SM3",
        "selected_roles": ["path_subject"],
    }
    service = OntologyPathSelectionService(assets=OntologyAssets.from_default_resources(), llm_selector=Selector())

    trace = service.fill(
        ontology_mapping=mapping,
        intent_trace=_intent_trace(),
        question="查询金牌服务经过的隧道及其源网元",
    )

    assert trace.llm_raw_output == "选择 PR2：P2。理由：源网元明确要求选择隧道源端。"
    assert [(item.request_id, item.path_id, item.selected_by) for item in trace.selected_paths] == [
        ("PR1", "P1", "auto_single_candidate"),
        ("PR2", "P2", "llm"),
    ]
    assert service.llm_selector.calls[0]["prompt_name"] == "ontology_path_selection"
    assert set(service.llm_selector.calls[0]) == {"prompt_name", "question", "path_selection_cards"}
    card_text = str(service.llm_selector.calls[0]["path_selection_cards"])
    assert "任务 PR2" in card_text
    assert "任务 PR1" not in card_text
    assert "P2" in card_text
    assert "P1" not in card_text
    assert "path_id_by_request" not in card_text
    assert "allowed_request_ids" not in card_text
    assert "review_default_path_options" not in card_text


def test_needs_review_default_path_generates_service_clarification_without_prompting() -> None:
    class Selector:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def select(self, prompt_name: str, variables: dict[str, object]):
            self.calls.append(variables)
            raise AssertionError("needs_review default path should not be sent to the LLM prompt")

    request_mapping = {
        "mapped_mentions": [
            {
                "mapping_id": "OM1",
                "ontology_kind": "relation_role",
                "surface": "端口",
                "span": [8, 10],
                "domain_class": "Service",
                "target_class": "Port",
                "selected_roles": ["path_subject"],
            }
        ]
    }
    service = OntologyPathSelectionService(assets=OntologyAssets.from_default_resources(), llm_selector=Selector())

    trace = service.fill(ontology_mapping=request_mapping, intent_trace=_intent_trace(), question="查询服务端口")

    assert trace.candidate_paths == ()
    assert service.llm_selector.calls == []
    assert trace.llm_raw_output == ""
    assert trace.clarification["options"] == ["Service -> Tunnel -> NetworkElement -> Port"]


def test_trace_root_dict_uses_ontology_path_selection_field() -> None:
    class Selector:
        def select(self, prompt_name: str, variables: dict[str, object]):
            return SimpleNamespace(
                raw_response=(
                    "选择 PR1：P1。理由：经过对应服务到隧道。\n"
                    "选择 PR2：P2。理由：源网元对应隧道源端。"
                )
            )

    service = OntologyPathSelectionService(assets=OntologyAssets.from_default_resources(), llm_selector=Selector())

    trace = service.fill(
        ontology_mapping=_ontology_mapping(),
        intent_trace=_intent_trace(),
        question="查询金牌服务经过的隧道及其源网元",
    )

    output = trace.to_stage_dict()

    assert set(output) == {"ontology_path_selection"}
    assert "path_filling" not in output
    assert output["ontology_path_selection"]["selected_paths"]


def test_legacy_path_filling_import_keeps_new_root_field() -> None:
    from services.cypher_generator_agent.app.ontology_layer.path_filling import OntologyPathFillingService

    class Selector:
        def select(self, prompt_name: str, variables: dict[str, object]):
            return SimpleNamespace(
                raw_response=(
                    "选择 PR1：P1。理由：经过对应服务到隧道。\n"
                    "选择 PR2：P2。理由：源网元对应隧道源端。"
                )
            )

    trace = OntologyPathFillingService(
        assets=OntologyAssets.from_default_resources(),
        llm_selector=Selector(),
    ).fill(
        ontology_mapping=_ontology_mapping(),
        intent_trace=_intent_trace(),
        question="查询金牌服务经过的隧道及其源网元",
    )

    assert set(trace.to_stage_dict()) == {"ontology_path_selection"}


def test_clarify_selection_generates_unresolved_clarification() -> None:
    class Selector:
        def select(self, prompt_name: str, variables: dict[str, object]):
            return SimpleNamespace(
                raw_response="需要澄清：源网元存在多条候选路径。选项：隧道源网元；经过网元"
            )

    service = OntologyPathSelectionService(assets=OntologyAssets.from_default_resources(), llm_selector=Selector())
    mapping = _ontology_mapping()
    mapping["mapped_mentions"][2] = {
        "mapping_id": "OM3",
        "mention_id": "m_source_ne_1",
        "mention_type": "RELATION",
        "surface": "源网元",
        "span": [13, 16],
        "ontology_kind": "relation_role",
        "role": "source",
        "domain_class": "Tunnel",
        "target_class": "NetworkElement",
        "object_candidate_id": "SM3",
        "selected_roles": ["path_subject"],
    }

    trace = service.fill(
        ontology_mapping=mapping,
        intent_trace=_intent_trace(),
        question="查询金牌服务经过的隧道及其源网元",
    )

    assert [(item.request_id, item.path_id, item.selected_by) for item in trace.selected_paths] == [
        ("PR1", "P1", "auto_single_candidate")
    ]
    assert trace.shape_updates["relation_resolution_expected"].decision == "clarify"
    assert trace.clarification == {
            "status": "unresolved",
            "reason_code": "ambiguous_path",
            "reason": "源网元存在多条候选路径",
            "options": ["隧道源网元", "经过网元"],
        }


@pytest.mark.parametrize(
    "raw,error_part",
    [
        ('{"decision":"accept","selected_paths":[],"clarification":null}', "unrecognized"),
        (
            "选择 PR999：P1。理由：bad",
            "unknown request_id",
        ),
        (
            "选择 PR2：P999。理由：bad",
            "unknown path_id",
        ),
        (
            "选择 PR2：P1。理由：bad",
            "unknown path_id",
        ),
        ("随便说一句", "unrecognized"),
    ],
)
def test_rejects_llm_selection_outside_service_boundaries(raw: str, error_part: str) -> None:
    class Selector:
        def select(self, prompt_name: str, variables: dict[str, object]):
            return SimpleNamespace(raw_response=raw)

    service = OntologyPathSelectionService(assets=OntologyAssets.from_default_resources(), llm_selector=Selector())
    mapping = _ontology_mapping()
    mapping["mapped_mentions"][2] = {
        "mapping_id": "OM3",
        "mention_id": "m_source_ne_1",
        "mention_type": "RELATION",
        "surface": "源网元",
        "span": [13, 16],
        "ontology_kind": "relation_role",
        "role": "source",
        "domain_class": "Tunnel",
        "target_class": "NetworkElement",
        "object_candidate_id": "SM3",
        "selected_roles": ["path_subject"],
    }

    with pytest.raises(OntologyPathSelectionValidationError, match=error_part):
        service.fill(
            ontology_mapping=mapping,
            intent_trace=_intent_trace(),
            question="查询金牌服务经过的隧道及其源网元",
        )
