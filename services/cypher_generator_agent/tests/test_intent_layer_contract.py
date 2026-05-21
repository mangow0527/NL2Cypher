import re

from services.cypher_generator_agent.app.intent_layer.layer import IntentLayer
from services.cypher_generator_agent.app.intent_layer.recognition import (
    IntentRecognitionResult,
    IntentRule,
    RuleBasedIntentRecognizer,
)
from services.cypher_generator_agent.app.ontology_layer.models import ContextSignal
from services.cypher_generator_agent.app.intent_layer.models import Intent, IntentOutput, InitialShapeField
from services.cypher_generator_agent.app.infrastructure import resource_paths
from services.cypher_generator_agent.app.runtime_pipeline import OntologyGenerationPipeline
from services.cypher_generator_agent.app.ontology_layer.assets import OntologyAssets
from services.cypher_generator_agent.app.ontology_layer.object_role_selection import OntologyObjectRoleSelectionService
from services.cypher_generator_agent.app.ontology_layer.binding import OntologyBindingService
from services.cypher_generator_agent.app.ontology_layer.coreference import OntologyCoreferenceService
from services.cypher_generator_agent.app.ontology_layer.logical_planning import OntologyLogicalPlanningService

import yaml


def _shape_signal(signal_id: str, *supports: str) -> ContextSignal:
    return ContextSignal(
        signal_id=signal_id,
        signal_type="SHAPE_SIGNAL",
        text="/".join(supports),
        span_start=0,
        span_end=0,
        supports=tuple(supports),
    )


class _SameInstanceCoreferenceSelector:
    def select(self, prompt_name: str, variables: dict[str, object]):
        class Selection:
            raw_response = "选择 C1。理由：fixture"

        assert prompt_name == "coreference_selection"
        return Selection()


class _TunnelNameBindingSelector:
    def select(self, prompt_name: str, variables: dict[str, object]):
        candidate_lines = str(variables.get("binding_candidate_list_with_ids") or "")
        match = re.search(r"(bc_[A-Za-z0-9_]+):[^\n]*attribute=Tunnel\.name", candidate_lines)
        if match is None:
            match = re.search(r"(bc_[A-Za-z0-9_]+):", candidate_lines)
        if match is None:
            raise AssertionError("binding fixture did not receive candidates")

        class Selection:
            raw_response = f"选择 {match.group(1)}。理由：fixture"

        assert prompt_name == "binding_selection"
        return Selection()


def test_rule_shape_gate_uses_shape_signals_for_accept_and_reject() -> None:
    recognizer = RuleBasedIntentRecognizer(
        valid_intents={
            ("record_retrieval_query", "related_record_query"),
            ("relationship_path_query", "path_trace_query"),
        },
        rules=[
            IntentRule.from_mapping(
                {
                    "rule_id": "record_relation",
                    "primary_intent": "record_retrieval_query",
                    "secondary_intent": "related_record_query",
                    "confidence": 0.9,
                    "include_any": ["经过"],
                    "exclude_shape_any": ["path_answer_hint"],
                }
            ),
            IntentRule.from_mapping(
                {
                    "rule_id": "path_answer",
                    "primary_intent": "relationship_path_query",
                    "secondary_intent": "path_trace_query",
                    "confidence": 0.95,
                    "include_any": ["经过"],
                    "require_shape_any": ["path_answer_hint"],
                }
            ),
        ],
    )

    projection = (_shape_signal("S1", "answer_projection_region"),)
    path_answer = (_shape_signal("S2", "path_answer_hint"),)

    record_result = recognizer.recognize("查询服务经过的隧道，返回名称", shape_signals=projection)
    assert record_result.primary_intent == "record_retrieval_query"
    assert record_result.secondary_intent == "related_record_query"

    path_result = recognizer.recognize("查询服务经过的完整路径", shape_signals=path_answer)
    assert path_result.primary_intent == "relationship_path_query"
    assert path_result.secondary_intent == "path_trace_query"


def test_classifier_consumes_core_question_and_shape_signals_without_mention_driven_shape() -> None:
    class Recognizer:
        def __init__(self) -> None:
            self.seen_question = None
            self.seen_shape_signals = None

        def recognize(self, question: str, *, shape_signals=()):
            self.seen_question = question
            self.seen_shape_signals = tuple(shape_signals)
            return IntentRecognitionResult(
                primary_intent="record_retrieval_query",
                secondary_intent="related_record_query",
                confidence=0.91,
                source="rule",
                decision="accept",
            )

    recognizer = Recognizer()
    shape_signals = (_shape_signal("S1", "answer_projection_region"),)
    classifier = IntentLayer(recognizer=recognizer)

    trace = classifier.run(
        core_question="查询服务经过的隧道，返回名称",
        shape_signals=shape_signals,
    )

    assert recognizer.seen_question == "查询服务经过的隧道，返回名称"
    assert recognizer.seen_shape_signals == shape_signals
    assert trace.intent.primary == "record_retrieval_query"
    assert trace.intent.secondary == "related_record_query"
    assert "requires_path" not in trace.initial_shape
    assert trace.initial_shape["answer_type"].value == "attribute_table"
    assert trace.initial_shape["projection_expected"].value is True
    assert trace.initial_shape["relation_resolution_expected"].value is True
    assert trace.initial_shape["relation_resolution_expected"].pending_until == "step_3_3"
    assert trace.initial_shape["path_answer_required"].value is False
    assert "查询相关记录" in trace.planning_prompt_text


def test_classifier_consumes_quantifier_shape_signal_without_changing_all_scope_intent() -> None:
    class Recognizer:
        def recognize(self, question: str, *, shape_signals=()):
            return IntentRecognitionResult(
                primary_intent="record_retrieval_query",
                secondary_intent="attribute_projection_query",
                confidence=0.91,
                source="rule",
                decision="accept",
            )

    quantifier_signal = _shape_signal("S2", "quantifier", "QUANT_ALL", "no_implicit_filter", "explicit_only_no_implicit")
    classifier = IntentLayer(recognizer=Recognizer())

    trace = classifier.run(
        core_question="查询所有金牌服务的ID",
        shape_signals=(quantifier_signal,),
    )

    assert trace.intent.primary == "record_retrieval_query"
    assert trace.intent.secondary == "attribute_projection_query"
    assert trace.initial_shape["filter_level_hint"].value == "explicit_only_no_implicit"
    assert trace.initial_shape["filter_level_hint"].derived_from == ("S2",)
    assert trace.initial_shape["quantifier_effects"].value == [
        {
            "mention_id": "S2",
            "canonical_id": "QUANT_ALL",
            "semantic": "no_implicit_filter",
            "affects_intent": False,
        }
    ]


def test_classifier_unknown_intent_outputs_machine_readable_clarify_fields() -> None:
    class UncertainRecognizer:
        def recognize(self, question: str, *, shape_signals=()) -> IntentRecognitionResult:
            return IntentRecognitionResult(
                primary_intent=None,
                secondary_intent=None,
                confidence=0.0,
                source="embedding",
                decision="fallback_llm",
            )

    classifier = IntentLayer(recognizer=UncertainRecognizer())

    trace = classifier.run(core_question="帮我看看这个业务是不是正常")
    payload = trace.to_dict()

    assert payload["intent"]["primary"] == "unknown"
    assert payload["intent"]["secondary"] == "unknown"
    assert payload["intent"]["clarify_origin"] == "intent_recognition"
    assert payload["intent"]["clarify_reason"] == "intent_not_identified"
    assert payload["intent"]["failed_fields"] == ["primary_intent", "secondary_intent"]
    assert payload["intent"]["candidate_intents"]


def test_taxonomy_embeds_shape_profiles_for_intents() -> None:
    taxonomy = yaml.safe_load(resource_paths.intent_taxonomy_path().read_text(encoding="utf-8"))
    record = next(item for item in taxonomy["intents"] if item["primary_intent"] == "record_retrieval_query")
    related = next(item for item in record["secondary_intents"] if item["secondary_intent"] == "related_record_query")

    assert record["shape_profile"]["path_answer_required"] is False
    assert related["default_answer_type"] == "attribute_table"
    assert related["shape_profile"]["relation_resolution_expected"] is True


def test_taxonomy_embeds_planning_prompt_text_for_every_secondary_intent() -> None:
    taxonomy = yaml.safe_load(resource_paths.intent_taxonomy_path().read_text(encoding="utf-8"))

    missing = [
        f"{primary['primary_intent']}.{secondary['secondary_intent']}"
        for primary in taxonomy["intents"]
        for secondary in primary["secondary_intents"]
        if not str(secondary.get("planning_prompt_text") or "").strip()
    ]

    assert missing == []


def test_pipeline_passes_only_core_question_and_shape_signals_to_intent_classifier() -> None:
    class SpyClassifier:
        def __init__(self) -> None:
            self.core_question = None
            self.shape_signal_supports = ()

        def run(self, *, core_question: str, shape_signals: tuple[ContextSignal, ...]) -> IntentOutput:
            self.core_question = core_question
            self.shape_signal_supports = tuple(signal.supports for signal in shape_signals)
            return IntentOutput(
                intent=Intent(
                    primary="record_retrieval_query",
                    secondary="related_record_query",
                    source="rule",
                    decision="accept",
                    confidence=0.9,
                ),
                planning_prompt_text="用户想查询相关记录，并返回某些字段。这个问题里既有过滤条件，也有对象之间的关系。",
                initial_shape={
                    "answer_type": InitialShapeField(
                        value="attribute_table",
                        source="taxonomy.secondary.default_answer_type",
                        decision="accept",
                        confidence=1.0,
                    ),
                    "projection_expected": InitialShapeField(
                        value=True,
                        source="taxonomy.secondary.shape_profile",
                        decision="accept",
                        confidence=1.0,
                    ),
                    "relation_resolution_expected": InitialShapeField(
                        value=True,
                        source="taxonomy.secondary.shape_profile",
                        decision="pending",
                        confidence=0.8,
                        pending_until="step_3_3",
                    ),
                    "path_answer_required": InitialShapeField(
                        value=False,
                        source="taxonomy.primary.shape_profile",
                        decision="accept",
                        confidence=1.0,
                    ),
                },
                candidates=(),
                rule_signals_used=(),
                diagnostics={},
            )

    classifier = SpyClassifier()

    class ObjectRoleSelector:
        def select(self, prompt_name: str, variables: dict[str, object]):
            class Selection:
                raw_response = (
                    "选择 SM1：path_subject。理由：fixture\n"
                    "选择 SM2：path_subject。理由：fixture"
                )

            assert prompt_name == "object_role_selection"
            return Selection()

    assets = OntologyAssets.from_default_resources()
    pipeline = OntologyGenerationPipeline(
        assets=assets,
        intent_layer=classifier,  # type: ignore[arg-type]
        object_role_selection_service=OntologyObjectRoleSelectionService(llm_selector=ObjectRoleSelector()),
        logical_planning_service=OntologyLogicalPlanningService(
            assets=assets,
            coreference_service=OntologyCoreferenceService(llm_selector=_SameInstanceCoreferenceSelector()),
            binding_service=OntologyBindingService(llm_selector=_TunnelNameBindingSelector()),
        ),
    )

    result = pipeline.generate("查询金牌服务使用的隧道名称", trace_id="trace-intent-input")

    assert result.status == "generated"
    assert classifier.core_question == "查询金牌服务使用的隧道名称"
    assert any("answer_projection_region" in supports for supports in classifier.shape_signal_supports)


def test_llm_fallback_selects_primary_then_secondary_intent() -> None:
    class UncertainRecognizer:
        def recognize(self, question: str, *, shape_signals=()) -> IntentRecognitionResult:
            return IntentRecognitionResult(
                primary_intent=None,
                secondary_intent=None,
                confidence=0.0,
                source="rule",
                decision="fallback_llm",
            )

    class LayeredSelector:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def select(self, prompt_name: str, variables: dict[str, object]):
            self.calls.append(variables)
            candidate_list = str(variables["intent_candidate_list_with_ids"])
            candidate_id = "C1" if len(self.calls) == 1 else "C4"

            class Selection:
                parsed = {
                    "decision": "accept",
                    "candidate_id": candidate_id,
                    "signal_ids": ["S1"],
                    "reason": "分层选择",
                }
                prompt_name = "intent_selection"
                prompt_version = "v1.0.0"
                prompt_hash = "hash"
                rendered_prompt_hash = f"rendered-{candidate_id}"
                raw_response = '{"decision":"accept","candidate_id":"' + candidate_id + '","signal_ids":["S1"],"reason":"分层选择"}'

            assert prompt_name == "intent_selection"
            if len(self.calls) == 1:
                assert "record_retrieval_query" in candidate_list
                assert "related_record_query" not in candidate_list
            else:
                assert "record_retrieval_query.related_record_query" in candidate_list
            return Selection()

    selector = LayeredSelector()
    classifier = IntentLayer(recognizer=UncertainRecognizer(), llm_selector=selector)

    trace = classifier.run(
        core_question="查询服务经过的隧道，返回名称",
        shape_signals=(_shape_signal("S1", "answer_projection_region"),),
    )

    assert len(selector.calls) == 2
    assert trace.intent.source == "llm"
    assert trace.intent.primary == "record_retrieval_query"
    assert trace.intent.secondary == "related_record_query"
    assert trace.diagnostics["llm_stage_count"] == 2
