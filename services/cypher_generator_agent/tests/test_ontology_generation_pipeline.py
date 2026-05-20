from __future__ import annotations

from services.cypher_generator_agent.app.runtime_pipeline import OntologyGenerationPipeline
from services.cypher_generator_agent.app.ontology_layer.assets import OntologyAssets
from services.cypher_generator_agent.app.ontology_layer.object_role_selection import OntologyObjectRoleSelectionService
from services.cypher_generator_agent.app.ontology_layer.models import ContextSignal, IntentIdentity, IntentTrace, ShapeField


class _FixtureIntentClassifier:
    def classify(self, *, core_question: str, shape_signals: tuple[ContextSignal, ...]) -> IntentTrace:
        return IntentTrace(
            intent=IntentIdentity(
                primary="record_retrieval_query",
                secondary="related_record_query",
                source="fixture",
                decision="accept",
                confidence=0.9,
            ),
            shape={
                "answer_type": ShapeField(
                    value="attribute_table",
                    source="taxonomy.secondary.default_answer_type",
                    decision="accept",
                    confidence=1.0,
                ),
                "projection_expected": ShapeField(
                    value=True,
                    source="taxonomy.secondary.shape_profile",
                    decision="accept",
                    confidence=1.0,
                ),
                "relation_resolution_expected": ShapeField(
                    value=True,
                    source="taxonomy.secondary.shape_profile",
                    decision="pending",
                    confidence=0.8,
                    pending_until="step_2_3",
                ),
                "path_answer_required": ShapeField(
                    value=False,
                    source="taxonomy.secondary.shape_profile",
                    decision="accept",
                    confidence=1.0,
                ),
            },
            candidates=({"id": "C1", "primary": "record_retrieval_query", "secondary": "related_record_query"},),
            rule_signals_used=tuple(signal.text for signal in shape_signals),
            diagnostics={
                "planning_prompt_text": "用户想查询相关记录，并返回某些字段。这个问题里既有过滤条件，也有对象之间的关系。"
            },
        )


class _FixtureObjectRoleSelectionSelector:
    def select(self, prompt_name: str, variables: dict[str, object]):
        class Selection:
            raw_response = (
                "选择 SM1：path_subject。理由：fixture\n"
                "选择 SM2：path_subject。理由：fixture"
            )

        assert prompt_name == "object_role_selection"
        assert "object_candidate_list" in variables
        assert "allowed_object_roles" in variables
        return Selection()


def _pipeline() -> OntologyGenerationPipeline:
    return OntologyGenerationPipeline(
        assets=OntologyAssets.from_default_resources(),
        intent_classifier=_FixtureIntentClassifier(),  # type: ignore[arg-type]
        object_role_selection_service=OntologyObjectRoleSelectionService(llm_selector=_FixtureObjectRoleSelectionSelector()),
    )


def test_ontology_generation_pipeline_generates_golden_service_tunnel_source_ne_query() -> None:
    pipeline = _pipeline()

    result = pipeline.generate(
        "查询金牌服务经过的隧道及其源网元，返回隧道的IETF标准和源网元的IP地址",
        trace_id="trace-golden",
    )

    assert result.status == "generated"
    assert result.cypher == (
        "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel)-[:TUNNEL_SRC]->(ne:NetworkElement)\n"
        "WHERE s.quality_of_service = 'Gold'\n"
        "RETURN t.ietf_standard AS tunnel_ietf_standard, ne.ip_address AS source_ne_ip_address"
    )
    assert result.trace.trace_id == "trace-golden"
    mention_ids = [mention.canonical_id for mention in result.trace.lexer.mentions]
    assert mention_ids == [
        "OP_QUERY",
        "ServiceQuality.Gold",
        "Service",
        "REL_PATH_THROUGH",
        "Tunnel",
        "REL_TUNNEL_SRC",
        "OP_RETURN_FIELD",
        "Tunnel",
        "Protocol.standard",
        "REL_TUNNEL_SRC",
        "NetworkElement.ip_address",
    ]
    ietf_mention = result.trace.lexer.mentions[8]
    assert set(ietf_mention.metadata["candidate_refs"]) == {"Protocol.standard", "Tunnel.ietf_standard"}
    assert result.trace.intent.intent.primary == "record_retrieval_query"
    assert result.trace.intent.intent.secondary == "related_record_query"
    assert result.trace.intent.shape["answer_type"].value == "attribute_table"
    assert result.trace.intent.shape["relation_resolution_expected"].value is True
    assert result.trace.intent.shape["relation_resolution_expected"].pending_until == "step_2_3"
    assert result.trace.intent.shape["path_answer_required"].value is False
    assert [edge.relation for edge in result.logical_plan.edges] == [
        "REL_SERVICE_USES_TUNNEL",
        "REL_TUNNEL_SRC",
    ]
    assert [projection.alias for projection in result.logical_plan.projections] == [
        "tunnel_ietf_standard",
        "source_ne_ip_address",
    ]


def test_ontology_generation_pipeline_exposes_replay_evidence_for_each_step() -> None:
    pipeline = _pipeline()

    result = pipeline.generate("查询金牌服务使用的隧道名称", trace_id="trace-replay")
    trace = result.trace.to_dict()

    assert set(trace) == {
        "trace_id",
        "preprocessing",
        "lexer",
        "intent",
        "object_role_selection",
        "ontology_mapping",
        "planner",
        "validator",
        "compiler",
    }
    assert trace["preprocessing"]["accepted"] is True
    assert trace["lexer"]["question"] == "查询金牌服务使用的隧道名称"
    assert trace["lexer"]["ac_matches"]
    assert trace["intent"]["rule_signals_used"]
    assert trace["object_role_selection"]["object_role_selection"]["selected_objects"]
    assert trace["planner"]["path_candidates"]
    assert trace["validator"]["checks"]
    assert trace["compiler"]["cypher"] == result.cypher


def test_ontology_generation_pipeline_uses_preprocessed_core_question_before_lexing() -> None:
    pipeline = _pipeline()

    result = pipeline.generate(
        "你好，现在就是我们遇到了一些咨询类的问题，所以需要查询一下金牌服务 "
        "哦不对是银牌服务所使用的隧道和他的源网元，然后你需要给我返回隧道的IETF标准和源网元的IP地址，谢谢啦！",
        trace_id="trace-preprocessed",
    )

    trace = result.trace.to_dict()
    assert trace["preprocessing"]["accepted"] is True
    assert trace["preprocessing"]["core_question"] == (
        "银牌服务所使用的隧道和其源网元，返回隧道的IETF标准和源网元的IP地址"
    )
    assert trace["lexer"]["question"] == trace["preprocessing"]["core_question"]
    assert "Gold" not in result.cypher
    assert "WHERE s.quality_of_service = 'Silver'" in result.cypher
    assert "ne.ip_address AS source_ne_ip_address" in result.cypher
