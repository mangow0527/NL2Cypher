from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.cypher_generator_agent.app.ontology_layer.object_role_selection import (
    ALLOWED_OBJECT_ROLES,
    ObjectRoleSelectionValidationError,
    OntologyObjectRoleSelectionService,
)
from services.cypher_generator_agent.app.intent_layer.models import Intent, IntentOutput, InitialShapeField
from services.cypher_generator_agent.app.ontology_layer.models import (
    ContextSignal,
    LexerTrace,
    Mention,
)
from services.cypher_generator_agent.app.runtime_pipeline import OntologyGenerationPipeline
from services.cypher_generator_agent.app.ontology_layer.assets import OntologyAssets
from services.cypher_generator_agent.app.clarification_layer.errors import ClarificationNeeded


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


def _signal(signal_id: str, signal_type: str, text: str, span: tuple[int, int], supports: tuple[str, ...]) -> ContextSignal:
    return ContextSignal(
        signal_id=signal_id,
        signal_type=signal_type,
        text=text,
        span_start=span[0],
        span_end=span[1],
        supports=supports,
        strength=1.0,
    )


def _lexer_trace() -> LexerTrace:
    question = "查询金牌服务经过的隧道及其源网元，返回隧道的IETF标准和源网元的IP地址"
    mentions = (
        _mention("OP_QUERY", "OPERATION", "查询", (0, 2)),
        _mention("ServiceQuality.Gold", "VALUE", "金牌", (2, 4), {"constrains_field": "Service.quality_of_service"}),
        _mention("Service", "OBJECT", "服务", (4, 6)),
        _mention("REL_PATH_THROUGH", "RELATION", "经过", (6, 8), {"domain": "Service", "range": "Tunnel"}),
        _mention("Tunnel", "OBJECT", "隧道", (9, 11)),
        _mention("REL_TUNNEL_SRC", "RELATION", "源网元", (13, 16), {"domain": "Tunnel", "range": "NetworkElement", "role": "source"}),
        _mention("OP_RETURN_FIELD", "OPERATION", "返回", (17, 19)),
        _mention("Tunnel", "OBJECT", "隧道", (19, 21)),
        _mention(
            "Protocol.standard",
            "ATTRIBUTE",
            "IETF标准",
            (22, 28),
            {"candidate_refs": ["Protocol.standard", "Tunnel.ietf_standard"]},
        ),
        _mention("REL_TUNNEL_SRC", "RELATION", "源网元", (29, 32), {"domain": "Tunnel", "range": "NetworkElement", "role": "source"}),
        _mention("NetworkElement.ip_address", "ATTRIBUTE", "IP地址", (33, 37)),
    )
    return LexerTrace(
        question=question,
        matcher="test",
        ac_matches=(),
        selected_hits=(),
        discarded_hits=(),
        resolution_summary={},
        unmatched_fragments=(),
        vector_recalls=(),
        mentions=mentions,
        unmatched_spans=(),
        context_signals=(
            _signal("S1", "PROXIMAL_MODIFIER", "金牌服务", (2, 6), ("ServiceQuality.Gold", "Service")),
            _signal("S2", "PROXIMAL_MODIFIER", "隧道的IETF标准", (19, 28), ("Protocol.standard", "Tunnel")),
            _signal("S3", "PROXIMAL_MODIFIER", "源网元的IP地址", (29, 37), ("NetworkElement.ip_address", "REL_TUNNEL_SRC")),
        ),
        shape_signals=(
            _signal("S4", "SHAPE_SIGNAL", "返回", (17, 19), ("answer_projection_region", "project_marker")),
        ),
    )


def _intent_output() -> IntentOutput:
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
            "answer_type": InitialShapeField("attribute_table", "taxonomy.secondary.default_answer_type", "accept", 1.0),
            "projection_expected": InitialShapeField(True, "taxonomy.secondary.shape_profile", "accept", 1.0),
            "relation_resolution_expected": InitialShapeField(
                True,
                "taxonomy.secondary.shape_profile",
                "pending",
                0.8,
                pending_until="step_3_3",
            ),
            "path_answer_required": InitialShapeField(False, "taxonomy.secondary.shape_profile", "accept", 1.0),
        },
        candidates=({"id": "C1", "primary": "record_retrieval_query", "secondary": "related_record_query"},),
        rule_signals_used=("返回",),
        diagnostics={},
    )


class AcceptingSelector:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def select(self, prompt_name: str, variables: dict[str, object]):
        self.calls.append({"prompt_name": prompt_name, **variables})
        return SimpleNamespace(
            raw_response=(
                "选择 SM1：filter_subject、path_subject。理由：金牌修饰服务。\n"
                "选择 SM2：path_subject。理由：隧道参与关系。\n"
                "选择 SM3：path_subject。理由：源网元是角色化对象。"
            )
        )


def test_builds_candidates_from_lexer_mentions_and_step_2_intent_context() -> None:
    selector = AcceptingSelector()
    service = OntologyObjectRoleSelectionService(llm_selector=selector)

    trace = service.select(lexer_trace=_lexer_trace(), intent_output=_intent_output())

    assert trace.allowed_object_roles == ALLOWED_OBJECT_ROLES
    candidate_surfaces = [(item.candidate_id, item.mention_type, item.surface) for item in trace.object_candidates]
    assert candidate_surfaces == [
        ("SM1", "OBJECT", "服务"),
        ("SM2", "OBJECT", "隧道"),
        ("SM3", "RELATION", "源网元"),
        ("SM4", "OBJECT", "隧道"),
        ("SM5", "RELATION", "源网元"),
    ]
    assert [item.candidate_id for item in trace.object_role_selection.selected_objects] == ["SM1", "SM2", "SM3"]
    assert trace.llm_raw_output.startswith("选择 SM1")
    prompt_variables = selector.calls[0]
    assert prompt_variables["prompt_name"] == "object_role_selection"
    assert "查询相关记录" in str(prompt_variables["planning_prompt_text"])
    assert "源网元" in str(prompt_variables["object_candidate_list"])
    first_candidate_evidence = trace.object_candidates[0].evidence
    assert any(item.source_id == "S1" and item.text == "金牌服务" for item in first_candidate_evidence)
    assert "initial_shape" not in prompt_variables
    assert "shape_signals" not in prompt_variables

    trace_payload = trace.to_dict()
    assert set(trace_payload) == {
        "object_candidates",
        "allowed_object_roles",
        "llm_raw_output",
        "object_role_selection",
        "clarification",
        "input_context",
    }
    assert trace_payload["object_role_selection"]["selected_objects"][0]["candidate_id"] == "SM1"
    assert trace_payload["input_context"]["intent"]["primary"] == "record_retrieval_query"
    assert trace_payload["input_context"]["initial_shape"]["answer_type"] == "attribute_table"
    assert trace_payload["input_context"]["context_signals"][0]["signal_id"] == "S1"
    assert trace_payload["input_context"]["shape_signals"][0]["signal_id"] == "S4"


def test_path_through_relation_is_evidence_not_object_candidate() -> None:
    class Selector:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def select(self, prompt_name: str, variables: dict[str, object]):
            self.calls.append({"prompt_name": prompt_name, **variables})
            return SimpleNamespace(raw_response="选择 SM1：path_subject。理由：service")

    lexer_trace = _lexer_trace()
    mentions = tuple(
        Mention(
            canonical_id=mention.canonical_id,
            mention_type=mention.mention_type,
            surface=mention.surface,
            span_start=mention.span_start,
            span_end=mention.span_end,
            metadata={**mention.metadata, "role": "path_through"} if mention.canonical_id == "REL_PATH_THROUGH" else mention.metadata,
        )
        for mention in lexer_trace.mentions
    )
    lexer_trace = LexerTrace(
        question=lexer_trace.question,
        matcher=lexer_trace.matcher,
        ac_matches=lexer_trace.ac_matches,
        selected_hits=lexer_trace.selected_hits,
        discarded_hits=lexer_trace.discarded_hits,
        resolution_summary=lexer_trace.resolution_summary,
        unmatched_fragments=lexer_trace.unmatched_fragments,
        vector_recalls=lexer_trace.vector_recalls,
        mentions=mentions,
        unmatched_spans=lexer_trace.unmatched_spans,
        context_signals=lexer_trace.context_signals,
        shape_signals=lexer_trace.shape_signals,
    )
    selector = Selector()
    service = OntologyObjectRoleSelectionService(llm_selector=selector)

    trace = service.select(lexer_trace=lexer_trace, intent_output=_intent_output())

    assert [(item.mention_type, item.surface) for item in trace.object_candidates] == [
        ("OBJECT", "服务"),
        ("OBJECT", "隧道"),
        ("RELATION", "源网元"),
        ("OBJECT", "隧道"),
        ("RELATION", "源网元"),
    ]
    assert all(item.surface != "经过" for item in trace.object_candidates)


@pytest.mark.parametrize(
    "raw,error_part",
    [
        ("选择 SM999：path_subject。理由：bad", "unknown candidate_id"),
        ("选择 SM1：owner。理由：bad", "unknown role"),
        ('{"decision":"maybe","selected_objects":[],"clarification":null}', "unrecognized object role selection line"),
    ],
)
def test_rejects_llm_output_outside_service_boundaries(raw: str, error_part: str) -> None:
    class BadSelector:
        def select(self, prompt_name: str, variables: dict[str, object]):
            return SimpleNamespace(raw_response=raw)

    service = OntologyObjectRoleSelectionService(llm_selector=BadSelector())

    with pytest.raises(ObjectRoleSelectionValidationError, match=error_part):
        service.select(lexer_trace=_lexer_trace(), intent_output=_intent_output())


def test_parses_selection_text_and_preserves_raw_output() -> None:
    class Selector:
        def select(self, prompt_name: str, variables: dict[str, object]):
            return SimpleNamespace(
                raw_response=(
                    "选择 SM1：path_subject。理由：first\n"
                    "选择 SM2：path_subject。理由：second"
                )
            )

    service = OntologyObjectRoleSelectionService(llm_selector=Selector())

    trace = service.select(lexer_trace=_lexer_trace(), intent_output=_intent_output())

    assert trace.llm_raw_output.startswith("选择 SM1")
    assert [item.candidate_id for item in trace.object_role_selection.selected_objects] == ["SM1", "SM2"]
    assert trace.object_role_selection.selected_objects[0].evidence_ids == ("E1", "E2", "E3", "E4")


def test_rejects_json_selection_output() -> None:
    class Selector:
        def select(self, prompt_name: str, variables: dict[str, object]):
            return SimpleNamespace(
                raw_response=(
                    '{"decision":"accept","selected_objects":['
                    '{"candidate_id":"SM1","roles":["path_subject"],"evidence_ids":["E999","E4"],"reason":"json"}'
                    '],"clarification":null}'
                )
            )

    service = OntologyObjectRoleSelectionService(llm_selector=Selector())

    with pytest.raises(ObjectRoleSelectionValidationError, match="unrecognized object role selection line"):
        service.select(lexer_trace=_lexer_trace(), intent_output=_intent_output())


def test_missing_object_candidates_clarifies_without_llm_call() -> None:
    class Selector:
        def select(self, prompt_name: str, variables: dict[str, object]):
            raise AssertionError("LLM should not be called when no object candidates exist")

    lexer_trace = LexerTrace(
        question="查询路由器名称",
        matcher="test",
        ac_matches=(),
        selected_hits=(),
        discarded_hits=(),
        resolution_summary={},
        unmatched_fragments=(),
        vector_recalls=(),
        mentions=(
            _mention("NetworkElementType.router", "VALUE", "路由器", (2, 5)),
            _mention("NetworkElement.name", "ATTRIBUTE", "名称", (5, 7)),
        ),
        unmatched_spans=(),
        context_signals=(),
        shape_signals=(),
    )
    service = OntologyObjectRoleSelectionService(llm_selector=Selector())

    trace = service.select(lexer_trace=lexer_trace, intent_output=_intent_output())

    assert trace.object_candidates == ()
    assert trace.object_role_selection.selected_objects == ()
    assert trace.clarification["reason_code"] == "missing_object_candidate"
    assert trace.llm_raw_output == ""


def test_pipeline_stops_when_step_3_1_needs_clarification() -> None:
    class ClarifyingSelector:
        def select(self, prompt_name: str, variables: dict[str, object]):
            return SimpleNamespace(raw_response="需要澄清：候选片段不足以判断后续需要重点关注什么。")

    class MappingSpy:
        def __init__(self) -> None:
            self.called = False

        def map(self, **kwargs):
            self.called = True
            raise AssertionError("step 3.2 should not run after step 3.1 clarification")

    mapping_spy = MappingSpy()
    pipeline = OntologyGenerationPipeline(
        assets=OntologyAssets.from_default_resources(),
        object_role_selection_service=OntologyObjectRoleSelectionService(llm_selector=ClarifyingSelector()),
        ontology_mapping_service=mapping_spy,
    )

    with pytest.raises(ClarificationNeeded) as exc_info:
        pipeline.generate(
            "查询金牌服务经过的隧道及其源网元，返回隧道的IETF标准和源网元的IP地址",
            trace_id="trace-step-2-1-clarify",
        )

    assert exc_info.value.stage == "step_3_1"
    assert "候选片段不足以判断" in exc_info.value.clarification["reason"]
    assert mapping_spy.called is False


def test_pipeline_runs_step_3_1_between_intent_and_logical_planning() -> None:
    selector = AcceptingSelector()
    pipeline = OntologyGenerationPipeline(
        assets=OntologyAssets.from_default_resources(),
        object_role_selection_service=OntologyObjectRoleSelectionService(llm_selector=selector),
    )

    result = pipeline.generate(
        "查询金牌服务经过的隧道及其源网元，返回隧道的IETF标准和源网元的IP地址",
        trace_id="trace-step-2-1",
    )

    trace = result.trace.to_dict()
    assert "object_role_selection" in trace
    assert trace["object_role_selection"]["object_role_selection"]["selected_objects"][0]["candidate_id"] == "SM1"
    assert selector.calls
