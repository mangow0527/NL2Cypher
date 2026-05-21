from __future__ import annotations

from services.cypher_generator_agent.app.intent_layer.models import Intent, IntentOutput, InitialShapeField
from services.cypher_generator_agent.app.lexical_layer.lexer import OntologyLexer
from services.cypher_generator_agent.app.ontology_layer.assets import OntologyAssets
from services.cypher_generator_agent.app.ontology_layer.object_role_selection import ObjectRoleSelection
from services.cypher_generator_agent.app.ontology_layer.ontology_mapping import OntologyMappingService


QUESTION = "查询金牌服务经过的隧道及其源网元，返回隧道的IETF标准和源网元的IP地址"


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


def _lexer_and_mapping():
    assets = OntologyAssets.from_default_resources()
    lexer_trace = OntologyLexer(assets).run(QUESTION)
    mapping = OntologyMappingService(assets).map(
        lexer_trace=lexer_trace,
        object_role_selection=ObjectRoleSelection(selected_objects=()),
    )
    return lexer_trace, mapping


def test_service_through_tunnel_context_exposes_service_uses_tunnel_mapping() -> None:
    lexer_trace, mapping = _lexer_and_mapping()

    relation_mentions = [mention for mention in lexer_trace.mentions if mention.mention_type == "RELATION"]
    assert any(
        mention.canonical_id == "REL_PATH_THROUGH"
        and mention.surface == "经过"
        for mention in relation_mentions
    )
    assert any(mention.canonical_id == "REL_TUNNEL_SRC" for mention in relation_mentions)
    assert all(mention.canonical_id.startswith("REL_") for mention in relation_mentions)
    assert not any(mention.canonical_id.startswith("SEM_") for mention in lexer_trace.mentions)

    mapping_payload = mapping.to_dict()
    mapped_items = mapping_payload["ontology_relation_hints"]
    assert any(
        item["semantic_object_id"] == "service_traverses_tunnel"
        and item["semantic_object_kind"] == "traversal"
        for item in mapped_items
    )
    assert any(item.get("relation_id") == "TUNNEL_SRC" for item in mapped_items)
    assert all(not str(item.get("relation_id", "")).startswith("REL_") for item in mapped_items)
    assert any(
        evidence["ontology_id"] == "service_traverses_tunnel"
        and evidence["map_source"] == "contextual_semantic_traversal"
        for evidence in mapping_payload["evidence"]
    )


def test_ietf_standard_family_keeps_tunnel_candidate_and_binds_to_tunnel_owner() -> None:
    lexer_trace, mapping = _lexer_and_mapping()

    ietf_mentions = [mention for mention in lexer_trace.mentions if mention.surface == "IETF标准"]
    assert len(ietf_mentions) == 1
    assert ietf_mentions[0].canonical_id == "Tunnel.ietf_standard"
    assert ietf_mentions[0].metadata["candidate_refs"] == ["Protocol.standard", "Tunnel.ietf_standard"]

    ietf_mappings = [
        item
        for item in mapping.to_dict()["ontology_attributes"]
        if item["attribute_id"] == "Tunnel.ietf_standard"
    ]
    assert len(ietf_mappings) == 1
    assert ietf_mappings[0]["attribute_candidates"] == ["Protocol.standard", "Tunnel.ietf_standard"]
    assert any(
        evidence["ontology_id"] == "Tunnel.ietf_standard"
        and evidence["candidate_refs"] == ["Protocol.standard", "Tunnel.ietf_standard"]
        for evidence in mapping.to_dict()["evidence"]
    )
