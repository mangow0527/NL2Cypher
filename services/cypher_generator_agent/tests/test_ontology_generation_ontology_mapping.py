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


def test_maps_mentions_to_ontology_and_backfills_step_2_1_selection() -> None:
    service = OntologyMappingService(OntologyAssets.from_default_resources())

    mapping = service.map(lexer_trace=_lexer_trace(), object_role_selection=_selection())

    rows = [item.to_dict() for item in mapping.mapped_mentions]
    assert [(item["mapping_id"], item["mention_id"], item["ontology_kind"], item["ontology_id"]) for item in rows] == [
        ("OM1", "m_servicequality_gold_1", "enum_value", "ServiceQuality.Gold"),
        ("OM2", "m_service_1", "class", "Service"),
        ("OM3", "m_rel_service_uses_tunnel_1", "relation", "SERVICE_USES_TUNNEL"),
        ("OM4", "m_tunnel_1", "class", "Tunnel"),
        ("OM5", "m_rel_tunnel_src_1", "relation_role", "TUNNEL_SRC"),
        ("OM6", "m_tunnel_2", "class", "Tunnel"),
        ("OM7", "m_protocol_standard_1", "attribute", "Protocol.standard"),
        ("OM8", "m_servicequality_gold_2", "enum_value", "ServiceQuality.Gold"),
        ("OM9", "m_sem_gold_service_1", "semantic_object", "gold_service"),
    ]
    assert rows[0]["constrains_attribute"] == "Service.quality_of_service"
    assert rows[2]["domain_class"] == "Service"
    assert rows[2]["range_class"] == "Tunnel"
    assert rows[4]["role"] == "source"
    assert rows[4]["target_class"] == "NetworkElement"
    assert rows[6]["parent_class"] == "Protocol"
    assert rows[6]["attribute_candidates"] == ["Protocol.standard", "Tunnel.ietf_standard"]
    assert rows[8]["semantic_object_kind"] == "concept"
    assert rows[8]["definition_ref"] == "semantic_objects.gold_service"
    assert [item["mention_id"] for item in rows if item["ontology_id"] == "ServiceQuality.Gold"] == [
        "m_servicequality_gold_1",
        "m_servicequality_gold_2",
    ]
    assert rows[1]["object_candidate_id"] == "SM1"
    assert rows[1]["selected_roles"] == ["filter_subject", "path_subject"]
    assert rows[4]["object_candidate_id"] == "SM2"
    assert rows[4]["selected_roles"] == ["path_subject"]


def test_candidate_refs_are_preserved_as_candidate_family_and_validated() -> None:
    service = OntologyMappingService(OntologyAssets.from_default_resources())
    trace = _lexer_trace()

    mapping = service.map(lexer_trace=trace, object_role_selection=ObjectRoleSelection(selected_objects=()))

    attribute = mapping.mapped_mentions[6].to_dict()
    assert attribute["candidate_refs"] == ["Protocol.standard", "Tunnel.ietf_standard"]
    assert attribute["attribute_candidates"] == ["Protocol.standard", "Tunnel.ietf_standard"]


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
