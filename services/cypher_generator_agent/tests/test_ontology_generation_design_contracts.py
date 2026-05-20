from __future__ import annotations

import re

import pytest

from services.cypher_generator_agent.app.runtime_pipeline import OntologyGenerationPipeline
from services.cypher_generator_agent.app.ontology_layer.assets import OntologyAssets
from services.cypher_generator_agent.app.clarification_layer.errors import ClarificationNeeded
from services.cypher_generator_agent.app.infrastructure.errors import EngineeringFailure
from services.cypher_generator_agent.app.ontology_layer.intent_classification.ontology import OntologyIntentClassifier
from services.cypher_generator_agent.app.lexical_layer.lexer import OntologyLexer
from services.cypher_generator_agent.app.lexical_layer.mention_vector_recall import MentionVectorCandidate
from services.cypher_generator_agent.app.ontology_layer.object_role_selection import OntologyObjectRoleSelectionService
from services.cypher_generator_agent.app.lexical_layer.overlap_resolver import DictionaryPriorities


class FakeMentionVectorRetriever:
    provider = "fake_mention_vector"

    def search(
        self,
        fragment: str,
        *,
        expected_mention_type: str | None,
        top_k: int,
    ) -> list[MentionVectorCandidate]:
        if fragment != "穿越" or expected_mention_type != "relation_predicate":
            return []
        return [
            MentionVectorCandidate(
                id="mention.REL_PATH_THROUGH.穿过",
                text="经过 途经 穿过 path through",
                canonical_id="REL_PATH_THROUGH",
                mention_type="relation_predicate",
                surface="穿过",
                score=0.91,
                metadata={"dictionary": "synonyms", "via_synonym_group": "SYN_PathThrough"},
            )
        ]


class FixtureObjectRoleSelector:
    def select(self, prompt_name: str, variables: dict[str, object]):
        assert prompt_name == "object_role_selection"
        candidate_ids = [str(item) for item in variables.get("allowed_candidate_ids", [])]

        class Selection:
            raw_response = "\n".join(
                f"选择 {candidate_id}：path_subject。理由：fixture"
                for candidate_id in candidate_ids
            )

        return Selection()


def _pipeline(*, assets: OntologyAssets | None = None, lexer: OntologyLexer | None = None) -> OntologyGenerationPipeline:
    assets = assets or OntologyAssets.from_default_resources()
    return OntologyGenerationPipeline(
        assets=assets,
        lexer=lexer,
        object_role_selection_service=OntologyObjectRoleSelectionService(llm_selector=FixtureObjectRoleSelector()),
    )


def test_lexer_uses_ac_automaton_and_vector_recall_for_unmatched_relation_synonym() -> None:
    assets = OntologyAssets.from_default_resources()
    pipeline = _pipeline(
        assets=assets,
        lexer=OntologyLexer(assets, vector_retriever=FakeMentionVectorRetriever()),
    )

    result = pipeline.generate("查询金牌服务穿越的隧道名称", trace_id="trace-vector")
    lexer = result.trace.to_dict()["lexer"]

    assert lexer["matcher"] == "ac"
    assert lexer["vector_recalls"]
    assert any(item["fragment"] == "穿越" for item in lexer["vector_recalls"])
    assert any(
        candidate["canonical_id"] == "REL_PATH_THROUGH"
        for item in lexer["vector_recalls"]
        for candidate in item["candidates"]
    )
    assert "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel)" in result.cypher


def test_lexer_scans_core_question_directly_without_matcher_preparation_trace() -> None:
    pipeline = _pipeline()

    result = pipeline.generate("查询金牌服务使用的隧道名称", trace_id="trace-direct-lexer")
    lexer = result.trace.to_dict()["lexer"]

    assert lexer["question"] == "查询金牌服务使用的隧道名称"
    assert "normalized_question" not in lexer
    assert "match_text" not in lexer
    assert "offset_map" not in lexer


def test_lexer_does_not_perform_literal_extraction() -> None:
    pipeline = _pipeline()

    lexer = pipeline.lexer.run("查询各服务的带宽，统计源网元为NetworkElement_003的数量").to_dict()

    all_hits = [*lexer["ac_matches"], *lexer["selected_hits"]]
    assert not any(hit["match_source"] == "literal_extract" for hit in all_hits)
    assert not any(hit["canonical_id"].startswith("LiteralValue.") for hit in all_hits)
    assert not any(
        mention["surface"] == "NetworkElement_003" and mention["mention_type"] == "VALUE"
        for mention in lexer["mentions"]
    )


def test_lexer_keeps_dictionary_canonical_ids_without_contextual_rewrite() -> None:
    pipeline = _pipeline()

    lexer = pipeline.lexer.run("查询隧道IETF标准").to_dict()

    assert any(
        hit["canonical_id"] == "Protocol.standard" and hit["surface"] == "IETF标准"
        for hit in lexer["ac_matches"]
    )


def test_lexer_indexes_dictionary_surface_forms_without_hardcoded_skip() -> None:
    pipeline = _pipeline()

    lexer = pipeline.lexer.run("查询金牌服务").to_dict()

    assert any(
        hit["canonical_id"] == "ServiceQuality.Gold" and hit["surface"] == "金牌服务"
        for hit in lexer["ac_matches"]
    )


def test_lexer_selects_complete_exact_ip_address_surface_without_bare_ip_alias() -> None:
    pipeline = _pipeline()

    result = pipeline.generate(
        "查询金牌服务经过的隧道及其源网元，返回隧道的IETF标准和源网元的IP地址",
        trace_id="trace-overlap-resolution",
    )
    lexer = result.trace.to_dict()["lexer"]

    ip_mentions = [
        mention
        for mention in lexer["mentions"]
        if mention["canonical_id"] == "NetworkElement.ip_address"
    ]
    assert len(ip_mentions) == 1
    assert ip_mentions[0]["surface"] == "IP地址"
    assert ip_mentions[0]["span"] == [33, 37]
    assert ip_mentions[0]["metadata"]["parent_object"] == "NetworkElement"
    assert lexer["selected_hits"]
    assert not any(
        item["hit"]["canonical_id"] == "NetworkElement.ip_address"
        and item["hit"]["surface"] == "IP"
        for item in lexer["discarded_hits"]
    )


def test_dictionary_priority_table_covers_used_mention_types_and_limits_overrides() -> None:
    assets = OntologyAssets.from_default_resources()
    priorities = DictionaryPriorities.from_default_resources()

    used_types = {entry.mention_type for entry in assets.entries if entry.mention_type != "synonym_group"}
    role_relations = {
        entry.canonical_id
        for entry in assets.entries
        if re.match(r"^REL_.*_(SRC|DST|PRIMARY|BACKUP|IN|OUT|START|END)$", entry.canonical_id)
    }

    assert priorities.override_semantics == "replace"
    assert "literal_extract" not in priorities.match_source_priorities
    assert used_types <= set(priorities.by_type)
    assert "synonym_group" not in priorities.by_type
    assert "OP_RETURN_FIELD" not in priorities.by_canonical_id
    assert role_relations <= set(priorities.by_canonical_id)
    assert all(priorities.by_canonical_id[item] >= 105 for item in role_relations)
    assert len(priorities.by_canonical_id) <= priorities.max_overrides
    assert priorities.max_overrides == 10


def test_synonym_group_hits_are_normalized_before_overlap_resolution() -> None:
    pipeline = _pipeline()

    lexer = pipeline.lexer.run("查询网络服务使用的网络隧道名称").to_dict()

    assert not any(hit["canonical_id"].startswith("SYN_") for hit in lexer["ac_matches"])
    assert not any(hit["mention_type"] == "synonym_group" for hit in lexer["ac_matches"])


def test_return_projection_marker_is_selected_without_priority_override() -> None:
    pipeline = _pipeline()

    lexer = pipeline.lexer.run("查询金牌服务，返回隧道名称").to_dict()

    assert "OP_RETURN_FIELD" not in DictionaryPriorities.from_default_resources().by_canonical_id
    assert not any(
        hit["canonical_id"] == "OP_QUERY" and hit["surface"] == "返回"
        for hit in lexer["ac_matches"]
    )
    assert any(
        mention["canonical_id"] == "OP_RETURN_FIELD" and mention["surface"] == "返回"
        for mention in lexer["mentions"]
    )


def test_lexer_keeps_enum_values_out_of_attribute_name_matches() -> None:
    pipeline = _pipeline()

    gold = pipeline.lexer.run("查询Gold服务名称").to_dict()
    port_up = pipeline.lexer.run("查询端口状态为up的端口名称").to_dict()

    assert ("ServiceQuality.Gold", "Gold", "VALUE") in [
        (mention["canonical_id"], mention["surface"], mention["mention_type"])
        for mention in gold["mentions"]
    ]
    assert not any(
        mention["canonical_id"] == "Service.quality_of_service"
        and mention["surface"] == "Gold"
        for mention in gold["mentions"]
    )
    up_mentions = [
        mention
        for mention in port_up["mentions"]
        if mention["surface"] == "up" and mention["mention_type"] == "VALUE"
    ]
    assert up_mentions
    assert set(up_mentions[0]["metadata"]["candidate_refs"]) == {"LinkAdminStatus.up", "PortStatus.up"}
    assert not any(
        mention["mention_type"] == "ATTRIBUTE" and mention["surface"] == "up"
        for mention in port_up["mentions"]
    )


def test_lexer_does_not_treat_conjunctions_as_projection_markers() -> None:
    pipeline = _pipeline()

    lexer = pipeline.lexer.run("查询服务和隧道").to_dict()

    assert not any(
        mention["canonical_id"] == "OP_RETURN_FIELD"
        for mention in lexer["mentions"]
    )


def test_bare_ip_does_not_shadow_protocol_context_but_ip_address_still_matches() -> None:
    pipeline = _pipeline()

    protocol = pipeline.lexer.run("查询IP协议名称").to_dict()
    ip_address = pipeline.lexer.run("查询IP地址").to_dict()

    assert not any(
        mention["canonical_id"] == "NetworkElement.ip_address"
        and mention["surface"] == "IP"
        for mention in protocol["mentions"]
    )
    assert any(
        mention["canonical_id"] == "NetworkElement.ip_address"
        and mention["surface"] == "IP地址"
        for mention in ip_address["mentions"]
    )


def test_object_type_words_are_values_not_business_object_aliases() -> None:
    pipeline = _pipeline()

    router = pipeline.lexer.run("查询路由器名称").to_dict()
    assert ("NetworkElementType.router", "路由器", "VALUE") in [
        (mention["canonical_id"], mention["surface"], mention["mention_type"])
        for mention in router["mentions"]
    ]
    assert not any(
        mention["canonical_id"] == "NetworkElement"
        and mention["surface"] == "路由器"
        for mention in router["mentions"]
    )


def test_generic_attribute_mentions_keep_candidate_refs_and_planner_binds_by_context() -> None:
    pipeline = _pipeline()

    lexer = pipeline.lexer.run("查询路由器名称").to_dict()

    name_mentions = [mention for mention in lexer["mentions"] if mention["surface"] == "名称"]
    assert name_mentions
    candidate_refs = name_mentions[0]["metadata"]["candidate_refs"]
    assert "NetworkElement.name" in candidate_refs
    assert "Service.name" in candidate_refs
    assert "Fiber.name" in candidate_refs
    with pytest.raises(ClarificationNeeded) as exc_info:
        pipeline.generate("查询路由器名称", trace_id="trace-router-name")
    assert exc_info.value.stage == "step_2_1"


def test_multi_target_synonym_mentions_keep_candidate_family() -> None:
    pipeline = _pipeline()

    lexer = pipeline.lexer.run("查询IETF标准").to_dict()

    standard_mentions = [mention for mention in lexer["mentions"] if mention["surface"] == "IETF标准"]
    assert standard_mentions
    candidate_refs = standard_mentions[0]["metadata"]["candidate_refs"]
    assert candidate_refs == ["Protocol.standard", "Tunnel.ietf_standard"]
    assert standard_mentions[0]["metadata"]["via_synonym_groups"]


def test_type_value_and_object_attribute_composition_survives_overlap_resolution() -> None:
    pipeline = _pipeline()

    lexer = pipeline.lexer.run("查询物理端口名称").to_dict()

    assert ("PortType.physical", "物理", "VALUE") in [
        (mention["canonical_id"], mention["surface"], mention["mention_type"])
        for mention in lexer["mentions"]
    ]
    assert ("Port.name", "端口名称", "ATTRIBUTE") in [
        (mention["canonical_id"], mention["surface"], mention["mention_type"])
        for mention in lexer["mentions"]
    ]
    with pytest.raises(ClarificationNeeded) as exc_info:
        pipeline.generate("查询物理端口名称", trace_id="trace-physical-port-name")
    assert exc_info.value.stage == "step_2_1"


def test_intent_classifier_uses_taxonomy_rules_and_embedding_not_hardcoded_pair() -> None:
    pipeline = _pipeline()

    result = pipeline.generate("统计服务使用的隧道数量", trace_id="trace-intent")
    intent = result.trace.intent.intent

    assert intent.primary == "metric_query"
    assert intent.secondary == "count_metric_query"
    assert intent.source in {"rule", "embedding"}
    assert "RETURN count(t) AS tunnel_count" in result.cypher
    assert result.trace.to_dict()["intent"]["diagnostics"]["taxonomy_version"] == 3


def test_planner_fills_dynamic_multihop_path_from_relation_dictionary() -> None:
    pipeline = _pipeline()

    result = pipeline.generate("查询金牌服务使用的隧道所经过网元上的所有端口名称", trace_id="trace-multihop")

    assert [edge.relation for edge in result.logical_plan.edges] == [
        "REL_SERVICE_USES_TUNNEL",
        "REL_PATH_THROUGH",
        "REL_HAS_PORT",
    ]
    assert result.cypher.startswith(
        "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel)-[:PATH_THROUGH]->(ne:NetworkElement)-[:HAS_PORT]->(p:Port)"
    )
    assert "p.name AS port_name" in result.cypher


def test_compiler_uses_cypher_mapping_and_physical_schema_assets() -> None:
    pipeline = _pipeline()

    result = pipeline.generate("查询金牌服务使用的隧道名称", trace_id="trace-mapping")
    compiler = result.trace.to_dict()["compiler"]

    assert compiler["mapping_version"] == 1
    assert compiler["physical_schema_version"] == 1
    assert compiler["physical_bindings"]["s1"] == "s:Service"
    assert compiler["physical_bindings"]["t1"] == "t:Tunnel"
    assert "Tunnel.name" in compiler["attribute_bindings"]


def test_validator_uses_constraints_and_cardinality_assets() -> None:
    pipeline = _pipeline()

    result = pipeline.generate("查询金牌服务使用的隧道名称", trace_id="trace-validator")
    checks = result.trace.to_dict()["validator"]["checks"]

    assert any(check["check"] == "constraint_rule" and check["constraint_id"] == "return_items_required" for check in checks)
    assert any(
        check["check"] == "relation_cardinality_policy"
        and check["relation"] == "REL_SERVICE_USES_TUNNEL"
        and check["confidence"] == "needs_review"
        for check in checks
    )


def test_grouped_service_bandwidth_query_no_longer_extracts_runtime_literal_in_lexer() -> None:
    pipeline = _pipeline()

    result = pipeline.generate(
        "查询各服务的带宽，统计它们使用的隧道总数，以及这些隧道中源网元为NetworkElement_003的数量。",
        trace_id="trace-service-bandwidth-tunnel-count-source-ne",
    )

    assert result.trace.intent.intent.primary == "breakdown_query"
    assert result.trace.intent.intent.secondary == "multi_metric_breakdown_query"
    assert not any(
        mention.surface == "NetworkElement_003" and mention.mention_type == "VALUE"
        for mention in result.trace.lexer.mentions
    )
    assert result.logical_plan.shape["group_by_required"].value is True
    assert [projection.alias for projection in result.logical_plan.projections] == ["service_bandwidth"]
    assert [metric.alias for metric in result.logical_plan.metrics] == ["tunnel_count"]
    assert result.cypher == (
        "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel)-[:TUNNEL_SRC]->(ne:NetworkElement)\n"
        "RETURN s.bandwidth AS service_bandwidth, count(t) AS tunnel_count"
    )


def test_pipeline_raises_clarification_needed_for_preprocessing_rejection() -> None:
    pipeline = _pipeline()

    with pytest.raises(ClarificationNeeded) as exc_info:
        pipeline.generate("Gold 服务最近有点慢，帮我看看", trace_id="trace-clarify")

    assert exc_info.value.stage == "preprocessing"
    assert exc_info.value.clarification["reason_code"] == "query_intent_missing"


def test_compiler_raises_engineering_failure_for_missing_mapping() -> None:
    pipeline = _pipeline()
    result = pipeline.generate("查询金牌服务使用的隧道名称", trace_id="trace-base")
    broken_compiler = pipeline.compiler.without_attribute_mapping("Tunnel.name")

    with pytest.raises(EngineeringFailure) as exc_info:
        broken_compiler.compile(result.logical_plan)

    assert exc_info.value.stage == "compiler"
    assert "Tunnel.name" in exc_info.value.message


def test_intent_classifier_can_call_bounded_llm_fallback_when_rules_are_uncertain() -> None:
    pipeline = _pipeline()
    lexer_trace = pipeline.lexer.run("查询服务经过的隧道，返回名称")

    class UncertainRecognizer:
        def recognize(self, question: str):
            class Result:
                primary_intent = None
                secondary_intent = None
                confidence = 0.0
                source = "rule"
                decision = "fallback_llm"

            return Result()

    class FakeSelector:
        def __init__(self) -> None:
            self.called = False

        def select(self, prompt_name: str, variables: dict[str, object]):
            self.called = True
            assert prompt_name == "intent_selection"
            assert "C1:" in str(variables["intent_candidate_list_with_ids"])

            class Selection:
                parsed = {
                    "decision": "accept",
                    "candidate_id": "C1",
                    "signal_ids": ["S1"],
                    "reason": "返回名称是属性表",
                }
                prompt_name = "intent_selection"
                prompt_version = "v1.0.0"
                prompt_hash = "hash"
                rendered_prompt_hash = "rendered"
                raw_response = '{"decision":"accept","candidate_id":"C1","signal_ids":["S1"],"reason":"返回名称是属性表"}'

            return Selection()

    selector = FakeSelector()
    classifier = OntologyIntentClassifier(recognizer=UncertainRecognizer(), llm_selector=selector)

    intent_trace = classifier.classify(lexer_trace)

    assert selector.called is True
    assert intent_trace.intent.source == "llm"
    assert intent_trace.intent.primary == "record_retrieval_query"
    assert intent_trace.to_dict()["diagnostics"]["llm_prompt_name"] == "intent_selection"
