from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.cypher_generator_agent.app.ontology_layer.assets import OntologyAssets
from services.cypher_generator_agent.app.intent_layer.models import Intent, IntentOutput, InitialShapeField
from services.cypher_generator_agent.app.ontology_layer.ontology_path_selection import (
    OntologyPathSelectionValidationError,
    OntologyPathSelectionService,
    PathRequest,
    build_candidate_paths,
    build_path_requests,
)


def _intent_output() -> IntentOutput:
    return IntentOutput(
        intent=Intent(
            primary="record_retrieval_query",
            secondary="related_record_query",
            source="rule",
            decision="accept",
            confidence=0.91,
        ),
        planning_prompt_text="用户想查询相关记录，并返回某些字段。",
        initial_shape={
            "projection_expected": InitialShapeField(True, "taxonomy", "accept", 1.0),
            "relation_resolution_expected": InitialShapeField(True, "taxonomy", "pending", 0.8, pending_until="step_3_3"),
        },
        candidates=(),
        rule_signals_used=("返回",),
        diagnostics={},
    )


def _ontology_mapping() -> dict[str, object]:
    return {
        "ontology_objects": [
            {
                "object_id": "OO1",
                "class_id": "Service",
                "object_candidate_id": "SM1",
                "selected_roles": ["filter_subject", "path_subject"],
                "evidence_refs": ["E1"],
            },
            {
                "object_id": "OO2",
                "class_id": "Tunnel",
                "object_candidate_id": "SM2",
                "selected_roles": ["path_subject"],
                "evidence_refs": ["E2"],
            },
            {
                "object_id": "OO3",
                "class_id": "NetworkElement",
                "object_candidate_id": "SM3",
                "selected_roles": ["path_subject"],
                "role_hint": {
                    "relation_hint_id": "ORH2",
                    "relation_id": "TUNNEL_SRC",
                    "role": "source",
                    "source_class": "Tunnel",
                },
                "evidence_refs": ["E3"],
            },
        ],
        "ontology_relation_hints": [
            {
                "relation_hint_id": "ORH1",
                "relation_id": "SERVICE_USES_TUNNEL",
                "from_class": "Service",
                "to_class": "Tunnel",
                "object_candidate_id": "SM2",
                "selected_roles": ["path_subject"],
                "evidence_refs": ["E2"],
            },
            {
                "relation_hint_id": "ORH2",
                "relation_id": "TUNNEL_SRC",
                "from_class": "Tunnel",
                "to_class": "NetworkElement",
                "role": "source",
                "object_candidate_id": "SM3",
                "selected_roles": ["path_subject"],
                "evidence_refs": ["E3"],
            },
        ],
        "ontology_attributes": [],
        "ontology_values": [],
        "evidence": [
            {
                "evidence_id": "E1",
                "mention_id": "m_service_1",
                "mention_type": "OBJECT",
                "surface": "服务",
                "span": [4, 6],
                "ontology_id": "Service",
            },
            {
                "evidence_id": "E2",
                "mention_id": "m_path_through_1",
                "mention_type": "RELATION",
                "surface": "经过",
                "span": [6, 8],
                "ontology_id": "SERVICE_USES_TUNNEL",
            },
            {
                "evidence_id": "E3",
                "mention_id": "m_source_ne_1",
                "mention_type": "RELATION",
                "surface": "源网元",
                "span": [13, 16],
                "ontology_id": "TUNNEL_SRC",
            },
        ],
    }


def test_builds_path_requests_from_step_3_2_ontology_mapping() -> None:
    requests = build_path_requests(_ontology_mapping())

    assert [item.request_id for item in requests] == ["PR1", "PR2"]
    assert requests[0].from_class == "Service"
    assert requests[0].to_class == "Tunnel"
    assert requests[0].relation_hint == "SERVICE_USES_TUNNEL"
    assert requests[0].evidence_refs == ("E2",)
    assert requests[1].from_class == "Tunnel"
    assert requests[1].to_class == "NetworkElement"
    assert requests[1].relation_hint == "TUNNEL_SRC"
    assert requests[1].role == "source"
    assert requests[1].evidence_refs == ("E3",)


def test_build_path_requests_ignores_mappings_without_path_roles() -> None:
    mapping = _ontology_mapping()
    mapping["ontology_relation_hints"].append(
        {
            "relation_hint_id": "ORH3",
            "relation_id": "TUNNEL_PROTO",
            "from_class": "Tunnel",
            "to_class": "Protocol",
            "selected_roles": ["projection_target"],
            "evidence_refs": ["E4"],
        }
    )

    requests = build_path_requests(mapping)

    assert [item.relation_hint for item in requests] == ["SERVICE_USES_TUNNEL", "TUNNEL_SRC"]


def test_build_path_requests_consumes_ir_without_mention_fields() -> None:
    mapping = _ontology_mapping()
    assert "mapped_mentions" not in mapping
    for section in ("ontology_objects", "ontology_relation_hints", "ontology_attributes", "ontology_values"):
        for item in mapping[section]:
            assert not {"mention_type", "surface", "span"}.intersection(item)

    requests = build_path_requests(mapping)

    assert [(item.from_class, item.to_class, item.relation_hint) for item in requests] == [
        ("Service", "Tunnel", "SERVICE_USES_TUNNEL"),
        ("Tunnel", "NetworkElement", "TUNNEL_SRC"),
    ]


def test_role_relation_evidence_does_not_create_duplicate_tunnel_to_network_element_request() -> None:
    requests = build_path_requests(_ontology_mapping())

    assert [(item.from_class, item.to_class) for item in requests].count(("Tunnel", "NetworkElement")) == 1


def test_terminal_projection_subject_gets_path_request_from_previous_path_endpoint() -> None:
    assets = OntologyAssets.from_default_resources()
    mapping = {
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
                "class_id": "NetworkElement",
                "selected_roles": ["path_subject"],
                "evidence_refs": ["E5"],
                "order": 5,
            },
            {
                "object_id": "OO3",
                "class_id": "Port",
                "selected_roles": ["projection_subject"],
                "evidence_refs": ["E6"],
                "order": 6,
            },
        ],
        "ontology_relation_hints": [
            {
                "relation_hint_id": "ORH1",
                "relation_id": "SERVICE_USES_TUNNEL",
                "from_class": "Service",
                "to_class": "Tunnel",
                "selected_roles": ["path_subject"],
                "evidence_refs": ["E3"],
                "order": 3,
            },
            {
                "relation_hint_id": "ORH2",
                "relation_id": "PATH_THROUGH",
                "from_class": "Tunnel",
                "to_class": "NetworkElement",
                "selected_roles": ["path_subject"],
                "evidence_refs": ["E4"],
                "order": 4,
            },
        ],
        "ontology_attributes": [],
        "ontology_values": [],
        "evidence": [],
    }

    requests = build_path_requests(mapping, assets=assets)
    candidates = build_candidate_paths(requests, assets)

    assert [(item.from_class, item.to_class, item.source_kind) for item in requests] == [
        ("Service", "Tunnel", "relation"),
        ("Tunnel", "NetworkElement", "relation"),
        ("NetworkElement", "Port", "projection_subject_link"),
    ]
    assert [item.relation_chain for item in candidates if item.request_id == "PR3"] == [("HAS_PORT",)]


def test_path_subject_pair_does_not_add_default_path_when_relation_hints_already_bridge_pair() -> None:
    mapping = {
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
                "class_id": "NetworkElement",
                "selected_roles": ["path_subject"],
                "evidence_refs": ["E5"],
                "order": 5,
            },
            {
                "object_id": "OO3",
                "class_id": "Port",
                "selected_roles": ["projection_subject"],
                "evidence_refs": ["E6"],
                "order": 6,
            },
        ],
        "ontology_relation_hints": [
            {
                "relation_hint_id": "ORH1",
                "relation_id": "SERVICE_USES_TUNNEL",
                "from_class": "Service",
                "to_class": "Tunnel",
                "selected_roles": ["path_subject"],
                "evidence_refs": ["E3"],
                "order": 3,
            },
            {
                "relation_hint_id": "ORH2",
                "relation_id": "PATH_THROUGH",
                "from_class": "Tunnel",
                "to_class": "NetworkElement",
                "selected_roles": ["path_subject"],
                "evidence_refs": ["E4"],
                "order": 4,
            },
        ],
        "ontology_attributes": [],
        "ontology_values": [],
        "evidence": [],
    }

    requests = build_path_requests(mapping)

    assert [(item.from_class, item.to_class, item.relation_hint, item.source_kind) for item in requests] == [
        ("Service", "Tunnel", "SERVICE_USES_TUNNEL", "relation"),
        ("Tunnel", "NetworkElement", "PATH_THROUGH", "relation"),
        ("NetworkElement", "Port", None, "projection_subject_link"),
    ]


def test_enumerates_explicit_role_semantic_and_default_candidate_paths_without_graph_duplicates() -> None:
    assets = OntologyAssets.from_default_resources()
    requests = build_path_requests(
        {
            "ontology_objects": [],
            "ontology_relation_hints": [
                {
                    "relation_hint_id": "ORH1",
                    "relation_id": "SERVICE_USES_TUNNEL",
                    "from_class": "Service",
                    "to_class": "Tunnel",
                    "evidence_refs": ["E1"],
                },
                {
                    "relation_hint_id": "ORH2",
                    "relation_id": "TUNNEL_SRC",
                    "role": "source",
                    "from_class": "Tunnel",
                    "to_class": "NetworkElement",
                    "evidence_refs": ["E2"],
                },
                {
                    "relation_hint_id": "ORH3",
                    "semantic_object_id": "service_source_ne",
                    "evidence_refs": ["E3"],
                },
            ],
            "ontology_attributes": [],
            "ontology_values": [],
            "evidence": [],
        },
    )

    candidates = build_candidate_paths(requests, assets)
    chains_by_source = {(item.request_id, item.source): item.relation_chain for item in candidates}

    assert chains_by_source[("PR1", "explicit_relation_mapping")] == ("SERVICE_USES_TUNNEL",)
    assert chains_by_source[("PR2", "role_relation_mapping")] == ("TUNNEL_SRC",)
    assert chains_by_source[("PR3", "semantic_traversal")] == ("SERVICE_USES_TUNNEL", "TUNNEL_SRC")
    assert all(item.source != "ontology_relation_graph" for item in candidates)


def test_uses_ontology_relation_graph_only_as_fallback() -> None:
    assets = OntologyAssets.from_default_resources()
    request = PathRequest(
        request_id="PR1",
        from_class="Tunnel",
        to_class="Port",
        source_id="ORH1",
        source_kind="relation_role",
        evidence_refs=("E1",),
    )

    candidates = build_candidate_paths((request,), assets)

    assert [(item.source, item.relation_chain) for item in candidates] == [
        ("ontology_relation_graph", ("TUNNEL_SRC", "HAS_PORT")),
        ("ontology_relation_graph", ("TUNNEL_DST", "HAS_PORT")),
        ("ontology_relation_graph", ("PATH_THROUGH", "HAS_PORT")),
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
        question="查询金牌服务经过的隧道及其源网元",
    )

    assert trace.llm_raw_output == ""
    assert [(item.request_id, item.path_id) for item in trace.selected_paths] == [("PR1", "P1"), ("PR2", "P2")]
    assert [item.evidence_ids for item in trace.selected_paths] == [("PE1",), ("PE2",)]
    assert [item.selected_by for item in trace.selected_paths] == ["auto_single_candidate", "auto_single_candidate"]
    assert trace.shape_updates["hop_count"].value == 2
    assert trace.shape_updates["relation_chain_type"].value == "fixed_chain"
    assert service.llm_selector.calls == []


def test_zero_hop_attribute_projection_marks_relation_resolution_complete() -> None:
    class Selector:
        def select(self, prompt_name: str, variables: dict[str, object]):
            raise AssertionError("zero-hop attribute projection must not call the path-selection LLM")

    service = OntologyPathSelectionService(assets=OntologyAssets.from_default_resources(), llm_selector=Selector())
    trace = service.fill(
        ontology_mapping={
            "ontology_objects": [
                {
                    "object_id": "OO1",
                    "class_id": "Service",
                    "selected_roles": ["path_subject"],
                    "evidence_refs": ["E1"],
                    "order": 1,
                }
            ],
            "ontology_relation_hints": [],
            "ontology_attributes": [
                {
                    "attribute_ref_id": "OA1",
                    "attribute_id": "Service.name",
                    "parent_class": "Service",
                    "attribute_candidates": ["Service.name"],
                    "evidence_refs": ["E2"],
                    "order": 2,
                },
                {
                    "attribute_ref_id": "OA2",
                    "attribute_id": "Service.bandwidth",
                    "parent_class": "Service",
                    "attribute_candidates": ["Service.bandwidth"],
                    "evidence_refs": ["E3"],
                    "order": 3,
                },
            ],
            "ontology_values": [],
            "evidence": [],
        },
        question="查询所有服务的名称和带宽。",
    )

    assert trace.path_requests == ()
    assert trace.selected_paths == ()
    assert trace.clarification is None
    assert trace.shape_updates["hop_count"].value == 0
    assert trace.shape_updates["relation_chain_type"].value == "zero_hop"
    assert trace.shape_updates["relation_resolution_expected"].value is False
    assert trace.shape_updates["relation_resolution_expected"].decision == "accept"


def test_calls_llm_only_for_multi_candidate_requests_with_local_cards() -> None:
    class Selector:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def select(self, prompt_name: str, variables: dict[str, object]):
            self.calls.append({"prompt_name": prompt_name, **variables})
            return SimpleNamespace(raw_response="选择 PR2：P2。理由：源网元明确要求选择隧道源端。")

    mapping = _ontology_mapping()
    mapping["ontology_relation_hints"][1] = {
        "relation_hint_id": "ORH2",
        "role": "source",
        "from_class": "Tunnel",
        "to_class": "NetworkElement",
        "object_candidate_id": "SM3",
        "selected_roles": ["path_subject"],
        "evidence_refs": ["E3"],
    }
    service = OntologyPathSelectionService(assets=OntologyAssets.from_default_resources(), llm_selector=Selector())

    trace = service.fill(
        ontology_mapping=mapping,
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


def test_retrieval_plan_relation_candidate_auto_selects_unique_multi_candidate_path() -> None:
    class Selector:
        def select(self, prompt_name: str, variables: dict[str, object]):
            raise AssertionError("unique retrieval-plan-supported path should not call the LLM")

    service = OntologyPathSelectionService(assets=OntologyAssets.from_default_resources(), llm_selector=Selector())
    mapping = {
        "ontology_objects": [
            {
                "object_id": "OO1",
                "class_id": "Tunnel",
                "selected_roles": ["path_subject"],
                "evidence_refs": ["E1"],
                "order": 1,
            },
            {
                "object_id": "OO2",
                "class_id": "NetworkElement",
                "selected_roles": ["path_subject", "return_subject"],
                "evidence_refs": ["E2"],
                "order": 2,
            },
        ],
        "ontology_relation_hints": [],
        "ontology_attributes": [],
        "ontology_values": [],
        "evidence": [
            {"evidence_id": "E1", "surface": "隧道"},
            {"evidence_id": "E2", "surface": "源端网元"},
        ],
    }
    lexer_trace = SimpleNamespace(
        vector_recalls=(
            {
                "source": "question_framing_retrieval_plan",
                "query_id": "PQ1",
                "fragment": "服务 使用的隧道 源端网元",
                "candidates": [
                    {
                        "candidate_id": "vc_tunnel_src",
                        "canonical_id": "REL_TUNNEL_SRC",
                        "mention_type": "RELATION",
                        "score": 0.83,
                    }
                ],
            },
        )
    )

    trace = service.fill(
        ontology_mapping=mapping,
        question="查询所有服务使用的隧道对应的源端网元",
        lexer_trace=lexer_trace,
    )

    assert trace.llm_raw_output == ""
    assert [(item.relation_chain, item.selected_by) for item in trace.selected_paths] == [
        (("TUNNEL_SRC",), "auto_retrieval_plan_relation")
    ]
    selected = trace.selected_paths[0]
    candidate = next(item for item in trace.candidate_paths if item.path_id == selected.path_id)
    assert any(evidence.type == "retrieval_plan_relation_candidate" for evidence in candidate.evidence)


def test_needs_review_default_path_generates_service_clarification_without_prompting() -> None:
    class Selector:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def select(self, prompt_name: str, variables: dict[str, object]):
            self.calls.append(variables)
            raise AssertionError("needs_review default path should not be sent to the LLM prompt")

    request_mapping = {
        "ontology_objects": [],
        "ontology_relation_hints": [
            {
                "relation_hint_id": "ORH1",
                "from_class": "Service",
                "to_class": "Port",
                "selected_roles": ["path_subject"],
                "evidence_refs": ["E1"],
            }
        ],
        "ontology_attributes": [],
        "ontology_values": [],
        "evidence": [],
    }
    service = OntologyPathSelectionService(assets=OntologyAssets.from_default_resources(), llm_selector=Selector())

    trace = service.fill(ontology_mapping=request_mapping, question="查询服务端口")

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
        question="查询金牌服务经过的隧道及其源网元",
    )

    output = trace.to_stage_dict()

    assert set(output) == {"ontology_path_selection"}
    assert "path_filling" not in output
    assert output["ontology_path_selection"]["selected_paths"]


def test_clarify_selection_generates_unresolved_clarification() -> None:
    class Selector:
        def select(self, prompt_name: str, variables: dict[str, object]):
            return SimpleNamespace(
                raw_response="需要澄清：源网元存在多条候选路径。选项：隧道源网元；经过网元"
            )

    service = OntologyPathSelectionService(assets=OntologyAssets.from_default_resources(), llm_selector=Selector())
    mapping = _ontology_mapping()
    mapping["ontology_relation_hints"][1] = {
        "relation_hint_id": "ORH2",
        "role": "source",
        "from_class": "Tunnel",
        "to_class": "NetworkElement",
        "object_candidate_id": "SM3",
        "selected_roles": ["path_subject"],
        "evidence_refs": ["E3"],
    }

    trace = service.fill(
        ontology_mapping=mapping,
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
    mapping["ontology_relation_hints"][1] = {
        "relation_hint_id": "ORH2",
        "role": "source",
        "from_class": "Tunnel",
        "to_class": "NetworkElement",
        "object_candidate_id": "SM3",
        "selected_roles": ["path_subject"],
        "evidence_refs": ["E3"],
    }

    with pytest.raises(OntologyPathSelectionValidationError, match=error_part):
        service.fill(
            ontology_mapping=mapping,
            question="查询金牌服务经过的隧道及其源网元",
        )
