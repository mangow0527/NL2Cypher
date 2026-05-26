from __future__ import annotations

import pytest

from services.cypher_generator_agent.app.ontology_layer.assets import OntologyAssets
from services.cypher_generator_agent.app.ontology_layer.object_role_selection import (
    ObjectRoleSelection,
    SelectedObjectRole,
)
from services.cypher_generator_agent.app.ontology_layer.models import LexerTrace, Mention
from services.cypher_generator_agent.app.ontology_layer.ontology_mapping import (
    OntologyMappingError,
    OntologyMappingService,
)


def _mention(
    canonical_id: str,
    mention_type: str,
    surface: str,
    span: tuple[int, int],
    metadata: dict[str, object] | None = None,
) -> Mention:
    return Mention(
        canonical_id=canonical_id,
        mention_type=mention_type,
        surface=surface,
        span_start=span[0],
        span_end=span[1],
        metadata=metadata or {},
    )


def _lexer_trace() -> LexerTrace:
    return LexerTrace(
        question="查询金牌服务经过的隧道及其源网元，返回隧道的IETF标准和源网元的IP地址",
        matcher="test",
        ac_matches=(),
        selected_hits=(),
        discarded_hits=(),
        resolution_summary={},
        unmatched_fragments=(),
        vector_recalls=(),
        mentions=(
            _mention("ServiceQuality.Gold", "VALUE", "金牌", (2, 4), {"constrains_field": "Service.quality_of_service"}),
            _mention("Service", "OBJECT", "服务", (4, 6)),
            _mention("REL_SERVICE_USES_TUNNEL", "RELATION", "经过", (6, 8)),
            _mention("Tunnel", "OBJECT", "隧道", (9, 11)),
            _mention("REL_TUNNEL_SRC", "RELATION", "源网元", (13, 16), {"role": "source"}),
            _mention("Tunnel", "OBJECT", "隧道", (19, 21)),
            _mention(
                "Protocol.standard",
                "ATTRIBUTE",
                "IETF标准",
                (22, 28),
                {"candidate_refs": ["Protocol.standard", "Tunnel.ietf_standard"]},
            ),
            _mention("ServiceQuality.Gold", "VALUE", "金牌", (38, 40), {"constrains_field": "Service.quality_of_service"}),
            _mention("SEM_GOLD_SERVICE", "OBJECT", "金牌服务", (41, 45)),
        ),
        unmatched_spans=(),
        context_signals=(),
        shape_signals=(),
    )


def _selection() -> ObjectRoleSelection:
    return ObjectRoleSelection(
        selected_objects=(
            SelectedObjectRole(
                candidate_id="SM1",
                mention_id="m_service_1",
                roles=("filter_subject", "path_subject"),
                evidence_ids=("E1",),
                selected_by="llm",
                reason="金牌修饰服务",
            ),
            SelectedObjectRole(
                candidate_id="SM2",
                mention_id="m_rel_tunnel_src_1",
                roles=("path_subject",),
                evidence_ids=("E2",),
                selected_by="llm",
                reason="源网元是角色化对象",
            ),
        )
    )


def test_maps_mentions_to_ontology_and_backfills_step_3_1_selection() -> None:
    service = OntologyMappingService(OntologyAssets.from_default_resources())

    mapping = service.map(lexer_trace=_lexer_trace(), object_role_selection=_selection())
    payload = mapping.to_dict()

    assert set(payload) == {
        "ontology_objects",
        "ontology_relation_hints",
        "ontology_attributes",
        "ontology_values",
        "evidence",
    }
    assert "mapped_mentions" not in payload
    for section in ("ontology_objects", "ontology_relation_hints", "ontology_attributes", "ontology_values"):
        for item in payload[section]:
            assert "mention_type" not in item
            assert "surface" not in item
            assert "span" not in item

    assert [(item["object_id"], item["class_id"]) for item in payload["ontology_objects"]] == [
        ("OO1", "Service"),
        ("OO2", "Tunnel"),
        ("OO3", "NetworkElement"),
        ("OO4", "Tunnel"),
    ]
    service_object = payload["ontology_objects"][0]
    assert service_object["object_candidate_id"] == "SM1"
    assert service_object["selected_roles"] == ["filter_subject", "path_subject"]
    source_ne = payload["ontology_objects"][2]
    assert source_ne["role_hint"] == {
        "relation_hint_id": "ORH2",
        "relation_id": "TUNNEL_SRC",
        "role": "source",
        "source_class": "Tunnel",
    }
    assert source_ne["object_candidate_id"] == "SM2"
    assert source_ne["selected_roles"] == ["path_subject"]

    relation_hints = [item for item in payload["ontology_relation_hints"] if "relation_id" in item]
    assert [(item["relation_hint_id"], item["relation_id"], item["from_class"], item["to_class"]) for item in relation_hints] == [
        ("ORH1", "SERVICE_USES_TUNNEL", "Service", "Tunnel"),
        ("ORH2", "TUNNEL_SRC", "Tunnel", "NetworkElement"),
    ]
    assert relation_hints[1]["role"] == "source"
    assert payload["ontology_attributes"][0]["attribute_candidates"] == ["Protocol.standard", "Tunnel.ietf_standard"]
    assert payload["ontology_values"][0]["constrains_attribute"] == "Service.quality_of_service"
    assert [item["mention_id"] for item in payload["evidence"] if item["ontology_id"] == "ServiceQuality.Gold"] == [
        "m_servicequality_gold_1",
        "m_servicequality_gold_2",
    ]


def test_candidate_refs_are_preserved_as_candidate_family_and_validated() -> None:
    service = OntologyMappingService(OntologyAssets.from_default_resources())
    trace = _lexer_trace()

    mapping = service.map(lexer_trace=trace, object_role_selection=ObjectRoleSelection(selected_objects=()))

    attribute = mapping.to_dict()["ontology_attributes"][0]
    assert attribute["attribute_candidates"] == ["Protocol.standard", "Tunnel.ietf_standard"]


def test_each_owner_return_attribute_keeps_owner_scope_from_question_framing_targets() -> None:
    trace = LexerTrace(
        question="查询所有服务使用的隧道，返回服务名称、隧道名称以及各自的延迟",
        matcher="test",
        ac_matches=(),
        selected_hits=(),
        discarded_hits=(),
        resolution_summary={},
        unmatched_fragments=(),
        vector_recalls=(),
        mentions=(
            _mention("Service", "OBJECT", "服务", (4, 6)),
            _mention("REL_SERVICE_USES_TUNNEL", "RELATION", "使用的", (6, 9)),
            _mention("Tunnel", "OBJECT", "隧道", (9, 11)),
            _mention(
                "Link.latency",
                "ATTRIBUTE",
                "延迟",
                (31, 33),
                {"candidate_refs": ["Link.latency", "Service.latency", "Tunnel.latency"]},
            ),
        ),
        unmatched_spans=(),
        context_signals=(),
        shape_signals=(),
        question_framing={
            "retrieval_plan": {
                "return_targets": [
                    {"atom_id": "QA2", "text": "服务名称", "span": [15, 19], "roles": ["RETURN_CONTENT"]},
                    {"atom_id": "QA3", "text": "隧道名称", "span": [20, 24], "roles": ["RETURN_CONTENT"]},
                    {"atom_id": "QA4", "text": "各自的延迟", "span": [26, 33], "roles": ["RETURN_CONTENT"]},
                ]
            }
        },
    )

    mapping = OntologyMappingService(OntologyAssets.from_default_resources()).map(
        lexer_trace=trace,
        object_role_selection=ObjectRoleSelection(selected_objects=()),
    )
    attribute = mapping.to_dict()["ontology_attributes"][0]

    assert attribute["attribute_id"] == "Link.latency"
    assert "parent_class" not in attribute
    assert attribute["attribute_candidates"] == ["Link.latency", "Service.latency", "Tunnel.latency"]
    assert attribute["projection_distribution"] == "each_owner"
    assert attribute["owner_scope"] == ["Service", "Tunnel"]
    assert attribute["metadata"]["owner_scope_source"] == "question_framing.return_targets"


def test_each_owner_return_attribute_keeps_distribution_when_scope_requires_path_context() -> None:
    trace = LexerTrace(
        question="查询所有服务与隧道之间的连接关系，并返回双方的延迟",
        matcher="test",
        ac_matches=(),
        selected_hits=(),
        discarded_hits=(),
        resolution_summary={},
        unmatched_fragments=(),
        vector_recalls=(),
        mentions=(
            _mention("Service", "OBJECT", "服务", (4, 6)),
            _mention("Tunnel", "OBJECT", "隧道", (7, 9)),
            _mention(
                "Link.latency",
                "ATTRIBUTE",
                "延迟",
                (24, 26),
                {"candidate_refs": ["Link.latency", "Service.latency", "Tunnel.latency"]},
            ),
        ),
        unmatched_spans=(),
        context_signals=(),
        shape_signals=(),
        question_framing={
            "retrieval_plan": {
                "return_targets": [
                    {"atom_id": "QA2", "text": "双方的延迟", "span": [21, 26], "roles": ["RETURN_CONTENT"]},
                ]
            }
        },
    )

    mapping = OntologyMappingService(OntologyAssets.from_default_resources()).map(
        lexer_trace=trace,
        object_role_selection=ObjectRoleSelection(selected_objects=()),
    )
    attribute = mapping.to_dict()["ontology_attributes"][0]

    assert "parent_class" not in attribute
    assert attribute["projection_distribution"] == "each_owner"
    assert "owner_scope" not in attribute
    assert attribute["metadata"]["owner_scope_source"] == "pending_path_owner_scope"


def test_relation_selected_as_return_subject_backfills_target_object() -> None:
    service = OntologyMappingService(OntologyAssets.from_default_resources())
    trace = LexerTrace(
        question="查询所有业务使用的隧道节点信息",
        matcher="test",
        ac_matches=(),
        selected_hits=(),
        discarded_hits=(),
        resolution_summary={},
        unmatched_fragments=(),
        vector_recalls=(),
        mentions=(
            _mention("Service", "OBJECT", "业务", (4, 6)),
            _mention(
                "REL_SERVICE_USES_TUNNEL",
                "RELATION",
                "使用的隧道",
                (6, 11),
                {"domain": "Service", "range": "Tunnel"},
            ),
        ),
        unmatched_spans=(),
        context_signals=(),
        shape_signals=(),
    )

    mapping = service.map(
        lexer_trace=trace,
        object_role_selection=ObjectRoleSelection(
            selected_objects=(
                SelectedObjectRole(
                    candidate_id="SM1",
                    mention_id="m_service_1",
                    roles=("path_subject",),
                    evidence_ids=("E1",),
                    selected_by="llm",
                    reason="业务是路径起点",
                    class_id="Service",
                ),
                SelectedObjectRole(
                    candidate_id="SM2",
                    mention_id="m_rel_service_uses_tunnel_1",
                    roles=("path_subject", "return_subject"),
                    evidence_ids=("E2",),
                    selected_by="llm",
                    reason="使用的隧道是返回对象",
                    class_id="Tunnel",
                ),
            )
        ),
    )
    payload = mapping.to_dict()

    assert [(item["class_id"], item.get("selected_roles")) for item in payload["ontology_objects"]] == [
        ("Service", ["path_subject"]),
        ("Tunnel", ["path_subject", "return_subject"]),
    ]
    tunnel = payload["ontology_objects"][1]
    assert tunnel["relation_target_hint"] == {
        "relation_hint_id": "ORH1",
        "relation_id": "SERVICE_USES_TUNNEL",
        "source_class": "Service",
    }
    assert payload["ontology_relation_hints"] == [
        {
            "relation_hint_id": "ORH1",
            "relation_id": "SERVICE_USES_TUNNEL",
            "from_class": "Service",
            "to_class": "Tunnel",
            "object_candidate_id": "SM2",
            "selected_roles": ["path_subject", "return_subject"],
            "evidence_refs": ["E2"],
            "order": 2,
        }
    ]


def test_value_mapping_preserves_enum_raw_value_separately_from_value_id() -> None:
    service = OntologyMappingService(OntologyAssets.from_default_resources())
    trace = LexerTrace(
        question="查询类型为MPLS-VPN的服务",
        matcher="test",
        ac_matches=(),
        selected_hits=(),
        discarded_hits=(),
        resolution_summary={},
        unmatched_fragments=(),
        vector_recalls=(),
        mentions=(
            _mention(
                "ServiceType.MPLS-VPN",
                "VALUE",
                "MPLS-VPN",
                (5, 13),
                {"constrains_field": "Service.elem_type", "raw_value": "MPLS-VPN"},
            ),
            _mention("Service", "OBJECT", "服务", (14, 16)),
        ),
        unmatched_spans=(),
        context_signals=(),
        shape_signals=(),
    )

    mapping = service.map(lexer_trace=trace, object_role_selection=ObjectRoleSelection(selected_objects=()))
    value = mapping.to_dict()["ontology_values"][0]

    assert value["value_id"] == "ServiceType.MPLS-VPN"
    assert value["raw_value"] == "MPLS-VPN"
    assert value["constrains_attribute"] == "Service.elem_type"


def test_maps_inferred_object_selection_from_attribute_owner() -> None:
    service = OntologyMappingService(OntologyAssets.from_default_resources())
    trace = LexerTrace(
        question="查询服务质量等级为 Gold 的服务名称",
        matcher="test",
        ac_matches=(),
        selected_hits=(),
        discarded_hits=(),
        resolution_summary={},
        unmatched_fragments=(),
        vector_recalls=(),
        mentions=(
            _mention("Service.quality_of_service", "ATTRIBUTE", "服务质量等级", (2, 8), {"parent_object": "Service"}),
            _mention(
                "ServiceQuality.Gold",
                "VALUE",
                "Gold",
                (10, 14),
                {"constrains_field": "Service.quality_of_service", "raw_value": "Gold"},
            ),
            _mention("Service.name", "ATTRIBUTE", "服务名称", (16, 20), {"parent_object": "Service"}),
        ),
        unmatched_spans=(),
        context_signals=(),
        shape_signals=(),
    )

    mapping = service.map(
        lexer_trace=trace,
        object_role_selection=ObjectRoleSelection(
            selected_objects=(
                SelectedObjectRole(
                    candidate_id="SM1",
                    mention_id="m_service_quality_of_service_1",
                    roles=("filter_subject", "projection_subject"),
                    evidence_ids=("E1",),
                    selected_by="llm",
                    reason="属性和值共同指向服务",
                    class_id="Service",
                ),
            )
        ),
    ).to_dict()

    assert mapping["ontology_objects"][0]["class_id"] == "Service"
    assert mapping["ontology_objects"][0]["selected_roles"] == ["filter_subject", "projection_subject"]
    assert mapping["ontology_objects"][0]["object_candidate_id"] == "SM1"
    assert mapping["ontology_attributes"][0]["attribute_id"] == "Service.quality_of_service"
    assert mapping["ontology_values"][0]["constrains_attribute"] == "Service.quality_of_service"


def test_default_ontology_assets_validate_mention_mappings_without_dictionary_fallbacks() -> None:
    assets = OntologyAssets.from_default_resources()
    service = OntologyMappingService(
        OntologyAssets(
            entries=(),
            mention_to_ontology=assets.mention_to_ontology,
            domain_ontology=assets.domain_ontology,
            semantic_objects=assets.semantic_objects,
        )
    )
    mention_types = {
        "class": "OBJECT",
        "relation": "RELATION",
        "relation_role": "RELATION",
        "attribute": "ATTRIBUTE",
        "enum_value": "VALUE",
    }

    for mapping in assets.mention_to_ontology["mappings"]:
        trace = LexerTrace(
            question="资产校验",
            matcher="test",
            ac_matches=(),
            selected_hits=(),
            discarded_hits=(),
            resolution_summary={},
            unmatched_fragments=(),
            vector_recalls=(),
            mentions=(
                _mention(
                    str(mapping["mention_id"]),
                    mention_types[str(mapping["ontology_kind"])],
                    str(mapping["mention_id"]),
                    (0, 1),
                ),
            ),
            unmatched_spans=(),
            context_signals=(),
            shape_signals=(),
        )

        service.map(lexer_trace=trace, object_role_selection=ObjectRoleSelection(selected_objects=()))


def test_default_relation_ontology_ids_use_ontology_layer_names() -> None:
    assets = OntologyAssets.from_default_resources()
    relation_ids = {str(item["id"]) for item in assets.domain_ontology["relations"]}
    relation_targets = {
        str(item["ontology_id"])
        for item in assets.mention_to_ontology["mappings"]
        if str(item["ontology_kind"]) in {"relation", "relation_role"}
    }

    assert all(not relation_id.startswith("REL_") for relation_id in relation_ids)
    assert relation_targets <= relation_ids


def test_default_semantic_relation_chains_reference_domain_relation_ids() -> None:
    assets = OntologyAssets.from_default_resources()
    relation_ids = {str(item["id"]) for item in assets.domain_ontology["relations"]}
    chains = [
        item["relation_chain"]
        for section in (assets.domain_ontology["default_paths"], assets.semantic_objects["traversals"])
        for item in section
    ]

    assert chains
    assert all(str(relation_id) in relation_ids for chain in chains for relation_id in chain)
    assert all(not str(relation_id).startswith("REL_") for chain in chains for relation_id in chain)


def test_rejects_unknown_ontology_references_from_mapping_assets() -> None:
    service = OntologyMappingService(OntologyAssets.from_default_resources())
    trace = LexerTrace(
        question="坏引用",
        matcher="test",
        ac_matches=(),
        selected_hits=(),
        discarded_hits=(),
        resolution_summary={},
        unmatched_fragments=(),
        vector_recalls=(),
        mentions=(_mention("UNKNOWN_CLASS", "OBJECT", "坏引用", (0, 3)),),
        unmatched_spans=(),
        context_signals=(),
        shape_signals=(),
    )

    with pytest.raises(OntologyMappingError, match="unknown class"):
        service.map(lexer_trace=trace, object_role_selection=ObjectRoleSelection(selected_objects=()))


@pytest.mark.parametrize(
    ("ontology_kind", "ontology_id", "mention_type", "canonical_id", "error"),
    [
        ("relation", "MISSING_RELATION", "RELATION", "REL_MISSING", "unknown relation"),
        ("attribute", "Service.missing", "ATTRIBUTE", "Service.missing", "unknown attribute"),
        ("enum_value", "ServiceQuality.Missing", "VALUE", "ServiceQuality.Missing", "unknown value"),
        ("semantic_object", "missing_semantic", "OBJECT", "SEM_MISSING", "unknown semantic_object"),
    ],
)
def test_rejects_unknown_ontology_references_declared_in_mention_mapping(
    ontology_kind: str,
    ontology_id: str,
    mention_type: str,
    canonical_id: str,
    error: str,
) -> None:
    service = OntologyMappingService(
        OntologyAssets(
            entries=(),
            mention_to_ontology={
                "mappings": [
                    {
                        "mention_id": canonical_id,
                        "ontology_kind": ontology_kind,
                        "ontology_id": ontology_id,
                    }
                ]
            },
            domain_ontology={
                "classes": [{"id": "Service"}],
                "relations": [],
                "attributes": [],
                "values": [],
            },
            semantic_objects={},
        )
    )
    trace = LexerTrace(
        question="坏引用",
        matcher="test",
        ac_matches=(),
        selected_hits=(),
        discarded_hits=(),
        resolution_summary={},
        unmatched_fragments=(),
        vector_recalls=(),
        mentions=(_mention(canonical_id, mention_type, "坏引用", (0, 3)),),
        unmatched_spans=(),
        context_signals=(),
        shape_signals=(),
    )

    with pytest.raises(OntologyMappingError, match=error):
        service.map(lexer_trace=trace, object_role_selection=ObjectRoleSelection(selected_objects=()))
