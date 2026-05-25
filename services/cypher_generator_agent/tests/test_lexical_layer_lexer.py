from __future__ import annotations

import pytest

from services.cypher_generator_agent.app.infrastructure import resource_paths
from services.cypher_generator_agent.app.lexical_layer.lexer import OntologyLexer
from services.cypher_generator_agent.app.lexical_layer.types import normalize_mention_type
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


def test_lexer_treats_enum_value_predicate_attribute_as_filter_not_projection() -> None:
    assets = OntologyAssets.from_default_resources()
    lexer_trace = OntologyLexer(assets, vector_retriever=None).run("查询所有服务质量等级为Bronze的服务")

    assert [(item.surface, item.mention_type) for item in lexer_trace.mentions] == [
        ("查询", "OPERATION"),
        ("所有", "QUANTIFIER"),
        ("服务质量等级", "ATTRIBUTE"),
        ("为", "COMPARISON_OPERATOR"),
        ("Bronze", "VALUE"),
        ("服务", "OBJECT"),
    ]
    assert any(
        signal.signal_type == "PREDICATE_GROUP"
        and signal.text == "服务质量等级为Bronze"
        and {"Service.quality_of_service", "OP_EQ", "ServiceQuality.Bronze"}.issubset(set(signal.supports))
        for signal in lexer_trace.context_signals
    )
    assert any(
        signal.signal_type == "NO_FILTER_CONDITION" and signal.supports == ("all_scope", "no_filter")
        for signal in lexer_trace.context_signals
    )
    assert not any(
        signal.text == "服务质量等级" and "answer_projection_region" in signal.supports
        for signal in lexer_trace.shape_signals
    )


def test_lexer_outputs_only_canonical_mention_types_for_runtime_mentions() -> None:
    assets = OntologyAssets.from_default_resources()
    lexer_trace = OntologyLexer(assets, vector_retriever=None).run("查询所有服务的名称和带宽")

    assert {item.mention_type for item in lexer_trace.mentions}.issubset(
        {
            "OPERATION",
            "VALUE",
            "OBJECT",
            "RELATION",
            "ATTRIBUTE",
            "LITERAL_VALUE",
            "COMPARISON_OPERATOR",
            "QUANTIFIER",
            "TIME_EXPRESSION",
        }
    )


def test_lexer_rejects_noncanonical_mention_type_names() -> None:
    for noncanonical_type in ("object", "value", "relation", "operation"):
        with pytest.raises(ValueError, match="unsupported mention_type"):
            normalize_mention_type(noncanonical_type)


def test_lexer_extracts_runtime_identifier_literal_for_attribute_predicate() -> None:
    assets = OntologyAssets.from_default_resources()
    lexer_trace = OntologyLexer(assets, vector_retriever=None).run(
        "查询名称为 Service_002 的服务的 ID、名称和服务质量"
    )

    mention_by_surface = {item.surface: item for item in lexer_trace.mentions}

    assert mention_by_surface["Service_002"].mention_type == "LITERAL_VALUE"
    assert mention_by_surface["Service_002"].metadata["value_type_hint"] == "identifier"
    assert "Service_002" not in [item["surface"] for item in lexer_trace.unmatched_fragments]
    assert any(
        signal.signal_type == "PREDICATE_GROUP"
        and signal.text == "名称为 Service_002"
        and {"Service.name", "OP_EQ", "Service_002", "LITERAL_IDENTIFIER"}.issubset(set(signal.supports))
        for signal in lexer_trace.context_signals
    )


def test_runtime_lexical_resources_keep_dictionary_categories_split() -> None:
    runtime_yaml_files = {path.name for path in resource_paths.LEXICAL_RESOURCE_DIR.glob("*.yaml")}
    dictionary_yaml_files = {path.name for path in resource_paths.lexical_dictionaries_dir().glob("*.yaml")}
    extractor_yaml_files = {path.name for path in resource_paths.lexical_structured_extractors_dir().glob("*.yaml")}

    assert runtime_yaml_files == set()
    assert dictionary_yaml_files == {
        "attribute_values.yaml",
        "attributes.yaml",
        "business_objects.yaml",
        "operation_cues.yaml",
        "relation_predicates.yaml",
        "synonyms.yaml",
    }
    assert extractor_yaml_files == {
        "literal_patterns.yaml",
        "operators.yaml",
        "quantifiers.yaml",
    }


def test_lexer_structured_extractor_paths_are_distinct_within_lexical_layer() -> None:
    paths = {
        resource_paths.lexer_operators_path(),
        resource_paths.lexer_quantifiers_path(),
        resource_paths.lexer_literal_patterns_path(),
    }

    assert len(paths) == 3
    assert all(path.parent == resource_paths.lexical_structured_extractors_dir() for path in paths)
    assert all(path.exists() for path in paths)
