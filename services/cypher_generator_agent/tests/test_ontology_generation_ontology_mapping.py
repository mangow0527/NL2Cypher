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
