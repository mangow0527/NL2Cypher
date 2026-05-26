from __future__ import annotations

import re

import pytest

from services.cypher_generator_agent.app.runtime_pipeline import OntologyGenerationPipeline
from services.cypher_generator_agent.app.ontology_layer.assets import OntologyAssets
from services.cypher_generator_agent.app.clarification_layer.errors import ClarificationNeeded
from services.cypher_generator_agent.app.infrastructure.errors import EngineeringFailure
from services.cypher_generator_agent.app.intent_layer.layer import IntentLayer
from services.cypher_generator_agent.app.lexical_layer.lexer import OntologyLexer
from services.cypher_generator_agent.app.lexical_layer.mention_vector_recall import MentionVectorCandidate
from services.cypher_generator_agent.app.ontology_layer.object_role_selection import OntologyObjectRoleSelectionService
from services.cypher_generator_agent.app.ontology_layer.coreference import OntologyCoreferenceService
from services.cypher_generator_agent.app.ontology_layer.binding import OntologyBindingService
from services.cypher_generator_agent.app.ontology_layer.logical_planning import OntologyLogicalPlanningService
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
        if fragment != "穿越" or expected_mention_type != "RELATION":
            return []
        return [
            MentionVectorCandidate(
                id="mention.REL_PATH_THROUGH.穿过",
                text="经过 途经 穿过 path through",
                canonical_id="REL_PATH_THROUGH",
                mention_type="RELATION",
                surface="穿过",
                score=0.91,
                metadata={"dictionary": "synonyms", "via_synonym_group": "SYN_PathThrough"},
            )
        ]


class FakeAttributePossessionRelationNoiseVectorRetriever:
    provider = "fake_attribute_possession_relation_noise_vector"

    def search(
        self,
        fragment: str,
        *,
        expected_mention_type: str | None,
        top_k: int,
    ) -> list[MentionVectorCandidate]:
        if fragment != "中拥有":
            return []
        return [
            MentionVectorCandidate(
                id="mention.REL_HAS_PORT.拥有端口",
                text="拥有端口 HAS_PORT",
                canonical_id="REL_HAS_PORT",
                mention_type="RELATION",
                surface="拥有端口",
                score=0.93,
                metadata={"dictionary": "relation_predicates"},
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


class FixtureCoreferenceSelector:
    def select(self, prompt_name: str, variables: dict[str, object]):
        assert prompt_name == "coreference_selection"

        class Selection:
            raw_response = "选择 C1。理由：fixture"

        return Selection()


class FixtureBindingSelector:
    def select(self, prompt_name: str, variables: dict[str, object]):
        assert prompt_name == "binding_selection"
        candidate_lines = str(variables.get("binding_candidate_list_with_ids") or "")
        signal_lines = str(variables.get("signal_list_with_ids") or "")
        question = str(variables.get("question") or "")
        candidate_id = _question_preferred_candidate(candidate_lines, question)
        if candidate_id is None:
            candidate_id = _first_supported_binding_candidate(signal_lines)
        if candidate_id is None:
            candidate_id = _first_binding_candidate(candidate_lines)

        class Selection:
            raw_response = f"选择 {candidate_id}。理由：fixture"

        return Selection()


class MetricAttributeBindingSelector:
    def select(self, prompt_name: str, variables: dict[str, object]):
        assert prompt_name == "binding_selection"
        candidate_lines = str(variables.get("binding_candidate_list_with_ids") or "")
        question = str(variables.get("question") or "")
        candidate_id = None
        for keyword, attribute in (
            ("延迟", "Service.latency"),
            ("服务质量", "Service.quality_of_service"),
            ("名称", "Service.name"),
        ):
            if keyword in question:
                candidate_id = _candidate_for_attribute(candidate_lines, attribute)
                if candidate_id is not None:
                    break
        if candidate_id is None:
            candidate_id = _first_binding_candidate(candidate_lines)

        class Selection:
            raw_response = f"选择 {candidate_id}。理由：fixture"

        return Selection()


def _first_supported_binding_candidate(signal_lines: str) -> str | None:
    match = re.search(r"supports=([^\\s]+)", signal_lines)
    if match is None:
        return None
    return match.group(1).split(",", 1)[0]


def _question_preferred_candidate(candidate_lines: str, question: str) -> str | None:
    for keyword, attribute in (
        ("源网元", "NetworkElement.ip_address"),
        ("IP", "NetworkElement.ip_address"),
        ("IETF", "Tunnel.ietf_standard"),
        ("隧道", "Tunnel.name"),
        ("端口", "Port.name"),
        ("带宽", "Service.bandwidth"),
    ):
        if keyword not in question:
            continue
        candidate_id = _candidate_for_attribute(candidate_lines, attribute)
        if candidate_id is not None:
            return candidate_id
    return None


def _candidate_for_attribute(candidate_lines: str, attribute: str) -> str | None:
    for line in candidate_lines.splitlines():
        if f"attribute={attribute}" not in line:
            continue
        match = re.match(r"(bc_[A-Za-z0-9_]+):", line)
        if match:
            return match.group(1)
    return None


def _first_binding_candidate(candidate_lines: str) -> str:
    match = re.search(r"(bc_[A-Za-z0-9_]+):", candidate_lines)
    if match:
        return match.group(1)
    raise AssertionError("binding fixture did not receive candidates")


def _pipeline(*, assets: OntologyAssets | None = None, lexer: OntologyLexer | None = None) -> OntologyGenerationPipeline:
    assets = assets or OntologyAssets.from_default_resources()
    return OntologyGenerationPipeline(
        assets=assets,
        lexer=lexer,
        object_role_selection_service=OntologyObjectRoleSelectionService(llm_selector=FixtureObjectRoleSelector()),
        logical_planning_service=OntologyLogicalPlanningService(
            assets=assets,
            coreference_service=OntologyCoreferenceService(llm_selector=FixtureCoreferenceSelector()),
            binding_service=OntologyBindingService(llm_selector=FixtureBindingSelector()),
        ),
    )


def _metric_attribute_pipeline(*, lexer: OntologyLexer | None = None) -> OntologyGenerationPipeline:
    assets = lexer.assets if lexer is not None else OntologyAssets.from_default_resources()
    return OntologyGenerationPipeline(
        assets=assets,
        lexer=lexer,
        object_role_selection_service=OntologyObjectRoleSelectionService(llm_selector=FixtureObjectRoleSelector()),
        logical_planning_service=OntologyLogicalPlanningService(
            assets=assets,
            coreference_service=OntologyCoreferenceService(llm_selector=FixtureCoreferenceSelector()),
            binding_service=OntologyBindingService(llm_selector=MetricAttributeBindingSelector()),
        ),
    )


def test_lexer_uses_ac_automaton_without_vector_recall_for_unmatched_relation_synonym() -> None:
    assets = OntologyAssets.from_default_resources()
    pipeline = _pipeline(
        assets=assets,
        lexer=OntologyLexer(assets, vector_retriever=FakeMentionVectorRetriever()),
    )

    result = pipeline.generate("查询金牌服务穿越的隧道名称", trace_id="trace-vector")
    lexer = result.trace.to_dict()["lexer"]

    assert lexer["matcher"] == "ac"
    assert lexer["vector_recalls"] == []
    assert any(item["surface"] == "穿越" for item in lexer["unmatched_fragments"])
    assert not any(item["canonical_id"] == "REL_PATH_THROUGH" for item in lexer["mentions"])
    assert "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel)" in result.cypher


def test_lexer_scans_core_question_directly_without_matcher_preparation_trace() -> None:
    pipeline = _pipeline()

    result = pipeline.generate("查询金牌服务使用的隧道名称", trace_id="trace-direct-lexer")
    lexer = result.trace.to_dict()["lexer"]

    assert lexer["question"] == "查询金牌服务使用的隧道名称"
    assert "normalized_question" not in lexer
    assert "match_text" not in lexer
    assert "offset_map" not in lexer


def test_lexer_extracts_runtime_identifier_as_literal_not_dictionary_value() -> None:
    pipeline = _pipeline()

    lexer = pipeline.lexer.run("查询各服务的带宽，统计源网元为NetworkElement_003的数量").to_dict()

    all_hits = [*lexer["ac_matches"], *lexer["selected_hits"]]
    assert not any(hit["canonical_id"].startswith("LiteralValue.") for hit in all_hits)
    assert not any(
        mention["surface"] == "NetworkElement_003" and mention["mention_type"] == "VALUE"
        for mention in lexer["mentions"]
    )
    assert any(
        hit["surface"] == "NetworkElement_003"
        and hit["canonical_id"] == "LITERAL_IDENTIFIER"
        and hit["match_source"] == "literal_extract"
        for hit in all_hits
    )
    assert not any(
        mention["surface"] == "NetworkElement" and mention["mention_type"] == "OBJECT"
        for mention in lexer["mentions"]
    )
    assert not any(item["surface"] == "NetworkElement_003" for item in lexer["unmatched_fragments"])


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


def test_overlap_resolution_uses_code_owned_generic_priorities_without_canonical_overrides() -> None:
    assets = OntologyAssets.from_default_resources()
    priorities = DictionaryPriorities.default()

    used_types = {entry.mention_type for entry in assets.entries if entry.mention_type != "SYNONYM_GROUP"}

    assert priorities.match_source_priorities["operator_extract"] == 108
    assert priorities.match_source_priorities["quantifier_extract"] == 105
    assert priorities.match_source_priorities["ac_exact"] == 100
    assert priorities.match_source_priorities["vector_recall"] == 50
    assert priorities.match_source_priorities["literal_extract"] == 40
    assert used_types <= set(priorities.by_type)
    assert "SYNONYM_GROUP" not in priorities.by_type
    assert priorities.by_canonical_id == {}


def test_synonym_group_entries_do_not_emit_runtime_mentions() -> None:
    pipeline = _pipeline()

    lexer = pipeline.lexer.run("查询网络服务使用的网络隧道名称").to_dict()

    assert not any(hit["canonical_id"].startswith("SYN_") for hit in lexer["ac_matches"])
    assert not any(hit["mention_type"] == "SYNONYM_GROUP" for hit in lexer["ac_matches"])


def test_return_projection_marker_is_selected_without_priority_override() -> None:
    pipeline = _pipeline()

    lexer = pipeline.lexer.run("查询金牌服务，返回隧道名称").to_dict()

    assert "OP_RETURN_FIELD" not in DictionaryPriorities.default().by_canonical_id
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


def test_generic_attribute_mentions_keep_candidate_refs_and_binding_uses_context() -> None:
    pipeline = _pipeline()

    lexer = pipeline.lexer.run("查询路由器名称").to_dict()

    name_mentions = [mention for mention in lexer["mentions"] if mention["surface"] == "名称"]
    assert name_mentions
    candidate_refs = name_mentions[0]["metadata"]["candidate_refs"]
    assert "NetworkElement.name" in candidate_refs
    assert "Service.name" in candidate_refs
    assert "Fiber.name" in candidate_refs
    result = pipeline.generate("查询路由器名称", trace_id="trace-router-name")

    assert result.cypher == "MATCH (ne:NetworkElement)\nWHERE ne.elem_type = 'router'\nRETURN ne.name AS source_ne_name"


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
    result = pipeline.generate("查询物理端口名称", trace_id="trace-physical-port-name")

    assert result.cypher == "MATCH (p:Port)\nWHERE p.elem_type = 'physical'\nRETURN p.name AS port_name"


def test_intent_classifier_uses_taxonomy_rules_and_embedding_not_hardcoded_pair() -> None:
    pipeline = _pipeline()

    result = pipeline.generate("统计服务使用的隧道数量", trace_id="trace-intent")
    intent = result.trace.intent.intent

    assert intent.primary == "metric_query"
    assert intent.secondary == "count_metric_query"
    assert intent.source in {"rule", "embedding"}
    assert "RETURN count(t) AS tunnel_count" in result.cypher
    assert result.trace.to_dict()["intent"]["diagnostics"]["taxonomy_version"] == 3


def test_pipeline_counts_service_attribute_quantity_instead_of_projecting_field() -> None:
    pipeline = _metric_attribute_pipeline()

    result = pipeline.generate("统计Service节点的名称数量", trace_id="trace-service-name-count")

    assert result.trace.intent.intent.primary == "metric_query"
    assert result.trace.intent.intent.secondary == "count_metric_query"
    assert result.cypher == "MATCH (s:Service)\nRETURN count(s.name) AS total"
    assert result.logical_plan.projections == ()
    assert [(item.function, item.node, item.attribute) for item in result.logical_plan.metrics] == [
        ("count", "s1", "name")
    ]


def test_pipeline_counts_non_null_service_latency_attribute_quantity() -> None:
    pipeline = _metric_attribute_pipeline()

    result = pipeline.generate(
        "统计所有服务中拥有延迟属性的数量",
        trace_id="trace-service-latency-attribute-count",
    )

    assert result.trace.intent.intent.primary == "metric_query"
    assert result.trace.intent.intent.secondary == "count_metric_query"
    assert result.cypher == "MATCH (s:Service)\nRETURN count(s.latency) AS total"
    assert result.logical_plan.projections == ()
    assert [(item.function, item.node, item.attribute) for item in result.logical_plan.metrics] == [
        ("count", "s1", "latency")
    ]


def test_pipeline_ignores_relation_vector_noise_for_attribute_possession_count() -> None:
    assets = OntologyAssets.from_default_resources()
    pipeline = _metric_attribute_pipeline(
        lexer=OntologyLexer(assets, vector_retriever=FakeAttributePossessionRelationNoiseVectorRetriever()),
    )

    result = pipeline.generate(
        "统计所有服务中拥有延迟属性的数量",
        trace_id="trace-service-latency-attribute-count-relation-noise",
    )

    trace = result.trace.to_dict()
    assert result.cypher == "MATCH (s:Service)\nRETURN count(s.latency) AS total"
    assert not any(
        mention["canonical_id"] == "REL_HAS_PORT"
        for mention in trace["lexer"]["mentions"]
    )


def test_logical_planning_fills_dynamic_multihop_path_from_relation_dictionary() -> None:
    pipeline = _pipeline()

    result = pipeline.generate("查询金牌服务使用的隧道所经过网元上的所有端口名称", trace_id="trace-multihop")

    assert [edge.relation for edge in result.logical_plan.edges] == [
        "SERVICE_USES_TUNNEL",
        "PATH_THROUGH",
        "HAS_PORT",
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
        and check["relation"] == "SERVICE_USES_TUNNEL"
        and check["confidence"] == "needs_review"
        for check in checks
    )


def test_grouped_service_bandwidth_query_keeps_runtime_literal_out_of_dictionary_values() -> None:
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
    assert [metric.alias for metric in result.logical_plan.metrics] == ["tunnel_count", "source_ne_tunnel_count"]
    assert result.logical_plan.metrics[1].function == "conditional_count"
    assert result.logical_plan.metrics[1].condition[0].to_dict() == {
        "node": "n1",
        "attr": "id",
        "operator": "=",
        "value": "NetworkElement_003",
    }
    assert result.cypher == (
        "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel)-[:TUNNEL_SRC]->(ne:NetworkElement)\n"
        "RETURN s.bandwidth AS service_bandwidth, count(t) AS tunnel_count, "
        "sum(CASE WHEN ne.id = 'NetworkElement_003' THEN 1 ELSE 0 END) AS source_ne_tunnel_count"
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
    classifier = IntentLayer(recognizer=UncertainRecognizer(), llm_selector=selector)

    intent_output = classifier.run(core_question=lexer_trace.question, shape_signals=lexer_trace.shape_signals)

    assert selector.called is True
    assert intent_output.intent.source == "llm"
    assert intent_output.intent.primary == "record_retrieval_query"
    assert intent_output.to_dict()["diagnostics"]["llm_prompt_name"] == "intent_selection"
