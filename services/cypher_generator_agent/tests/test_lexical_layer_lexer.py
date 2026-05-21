from __future__ import annotations

import yaml

from services.cypher_generator_agent.app.infrastructure import resource_paths
from services.cypher_generator_agent.app.lexical_layer.lexer import OntologyLexer
from services.cypher_generator_agent.app.ontology_layer.assets import OntologyAssets


def test_lexer_groups_projection_attributes_under_same_owner_and_keeps_all_scope_as_filter_signal() -> None:
    assets = OntologyAssets.from_default_resources()
    lexer_trace = OntologyLexer(assets, vector_retriever=None).run("查询所有服务的名称和带宽")

    assert lexer_trace.unmatched_fragments == ()
    assert (2, 4) not in lexer_trace.unmatched_spans
    assert [(item.surface, item.mention_type) for item in lexer_trace.mentions] == [
        ("查询", "OPERATION"),
        ("所有", "QUANTIFIER"),
        ("服务", "OBJECT"),
        ("名称", "ATTRIBUTE"),
        ("带宽", "ATTRIBUTE"),
    ]
    assert [(signal.text, signal.signal_type) for signal in lexer_trace.context_signals] == [
        ("所有服务", "QUANTIFIER_BINDING"),
        ("服务的名称和带宽", "PROXIMAL_MODIFIER"),
        ("所有", "NO_FILTER_CONDITION"),
    ]
    assert [(signal.text, signal.signal_type) for signal in lexer_trace.shape_signals if signal.text != "所有"] == [
        ("名称", "SHAPE_SIGNAL"),
        ("带宽", "SHAPE_SIGNAL"),
    ]


def test_lexer_treats_bare_id_as_generic_attribute_candidate_like_name() -> None:
    assets = OntologyAssets.from_default_resources()
    lexer_trace = OntologyLexer(assets, vector_retriever=None).run("查询所有服务的名称、带宽和ID")

    id_mentions = [item for item in lexer_trace.mentions if item.surface == "ID"]

    assert len(id_mentions) == 1
    assert id_mentions[0].mention_type == "ATTRIBUTE"
    assert "Service.id" in id_mentions[0].metadata["candidate_refs"]
    assert "ID" not in [item["surface"] for item in lexer_trace.unmatched_fragments]
    assert [(signal.text, signal.signal_type) for signal in lexer_trace.shape_signals if signal.text != "所有"] == [
        ("名称", "SHAPE_SIGNAL"),
        ("带宽", "SHAPE_SIGNAL"),
        ("ID", "SHAPE_SIGNAL"),
    ]


def test_lexer_extracts_structured_predicate_and_quantifier_mentions() -> None:
    assets = OntologyAssets.from_default_resources()
    lexer_trace = OntologyLexer(assets, vector_retriever=None).run("查询延迟小于20ms的所有金牌服务的ID")

    mention_by_surface = {item.surface: item for item in lexer_trace.mentions}

    assert mention_by_surface["小于"].mention_type == "COMPARISON_OPERATOR"
    assert mention_by_surface["小于"].canonical_id == "OP_LT"
    assert mention_by_surface["20ms"].mention_type == "LITERAL_VALUE"
    assert mention_by_surface["20ms"].metadata["raw"] == "20ms"
    assert mention_by_surface["所有"].mention_type == "QUANTIFIER"
    assert mention_by_surface["所有"].canonical_id == "QUANT_ALL"
    assert any(
        signal.signal_type == "PREDICATE_GROUP" and {"Service.latency", "OP_LT", "20ms"}.issubset(set(signal.supports))
        for signal in lexer_trace.context_signals
    )
    assert any(
        signal.text == "所有"
        and {"quantifier", "QUANT_ALL", "no_implicit_filter", "explicit_only_no_implicit"}.issubset(set(signal.supports))
        for signal in lexer_trace.shape_signals
    )


def test_scope_filter_terms_are_loaded_from_runtime_resource() -> None:
    payload = yaml.safe_load(resource_paths.lexer_signal_rules_path().read_text(encoding="utf-8"))

    assert payload["scope_filter_signals"]["all_records"]["surface_forms"] == ["所有", "全部", "全量"]
