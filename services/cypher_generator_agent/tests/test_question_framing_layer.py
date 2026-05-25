from __future__ import annotations

import pytest

from services.cypher_generator_agent.app.clarification_layer.errors import ClarificationNeeded
from services.cypher_generator_agent.app.intent_layer.models import Intent, IntentOutput, InitialShapeField
from services.cypher_generator_agent.app.ontology_layer.assets import OntologyAssets
from services.cypher_generator_agent.app.ontology_layer.models import ContextSignal, LexerTrace
from services.cypher_generator_agent.app.runtime_pipeline import OntologyGenerationPipeline
from services.cypher_generator_agent.app.question_framing_layer.models import (
    QuestionAtom,
    QuestionFramingRole,
    QuestionFramingTrace,
)
from services.cypher_generator_agent.app.question_framing_layer.service import QuestionFramingService
from services.cypher_generator_agent.app.lexical_layer.lexer import OntologyLexer


class _FixtureCompletionClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


def test_question_framing_service_parses_atomic_questions_and_roles() -> None:
    client = _FixtureCompletionClient(
        "\n".join(
            [
                "原子问题：",
                "1. 名称为 Service_002 的服务 ｜ 找什么对象 + 用什么条件筛选",
                "2. ID、名称和服务质量 ｜ 最后返回什么",
            ]
        )
    )
    service = QuestionFramingService(client=client)

    trace = service.run("查询名称为 Service_002 的服务的 ID、名称和服务质量")

    assert "不要生成查询语句" in client.prompts[0]
    assert "连接/关系/关联/连接关系" in client.prompts[0]
    assert "查询名称为 Service_002 的服务的 ID、名称和服务质量" in client.prompts[0]
    assert [atom.text for atom in trace.atoms] == ["名称为 Service_002 的服务", "ID、名称和服务质量"]
    assert trace.atoms[0].roles == (
        QuestionFramingRole.FIND_OBJECT,
        QuestionFramingRole.FILTER_CONDITION,
    )
    assert trace.atoms[0].span == (2, 21)
    assert trace.atoms[1].roles == (QuestionFramingRole.RETURN_CONTENT,)
    assert trace.diagnostics == ()
    atom_payload = trace.to_dict()["atoms"][0]
    assert atom_payload["roles"] == ["FIND_OBJECT", "FILTER_CONDITION"]
    assert "role_labels" not in atom_payload
    assert atom_payload["raw_role_text"] == "找什么对象 + 用什么条件筛选"


def test_question_framing_service_keeps_statistics_sorting_time_role_as_single_label() -> None:
    client = _FixtureCompletionClient("1. 按服务质量等级统计服务数量 ｜ 是否涉及统计、排序或时间")
    service = QuestionFramingService(client=client)

    trace = service.run("按服务质量等级统计服务数量")

    assert trace.atoms[0].roles == (QuestionFramingRole.AGG_SORT_TIME,)


def test_question_framing_service_builds_trace_only_retrieval_plan_for_path_query() -> None:
    client = _FixtureCompletionClient(
        "\n".join(
            [
                "原子问题：",
                "1. 所有服务 ｜ 找什么对象",
                "2. 使用的隧道对应的源端网元 ｜ 通过什么关系继续找",
                "3. 源端网元 ｜ 最后返回什么",
            ]
        )
    )
    service = QuestionFramingService(client=client)

    trace = service.run("查询所有服务使用的隧道对应的源端网元")

    plan = trace.to_dict()["retrieval_plan"]
    assert plan["version"] == "question_framing_retrieval_plan_v1"
    assert plan["path_queries"] == [
        {
            "query_id": "PQ1",
            "atom_ids": ["QA1", "QA2"],
            "source_text": "所有服务",
            "path_text": "使用的隧道对应的源端网元",
            "retrieval_text": "所有服务 使用的隧道对应的源端网元",
            "roles": ["FIND_OBJECT", "RELATION_PATH"],
            "grounding_spans": [[2, 6], [6, 18]],
            "generic_connectors": ["对应"],
        }
    ]
    assert plan["return_targets"] == [
        {
            "atom_id": "QA3",
            "text": "源端网元",
            "retrieval_text": "源端网元",
            "span": [14, 18],
            "roles": ["RETURN_CONTENT"],
        }
    ]
    assert plan["diagnostics"] == []


def test_lexer_keeps_question_framing_trace_and_uses_filter_atoms_as_projection_hint() -> None:
    assets = OntologyAssets.from_default_resources()
    question = "查询名称为 Service_002 的服务的 ID、名称和服务质量"
    framing = QuestionFramingTrace(
        question=question,
        raw_response="fixture",
        atoms=(
            QuestionAtom(
                atom_id="QA1",
                text="名称为 Service_002 的服务",
                roles=(QuestionFramingRole.FIND_OBJECT, QuestionFramingRole.FILTER_CONDITION),
                span_start=2,
                span_end=21,
            ),
            QuestionAtom(
                atom_id="QA2",
                text="ID、名称和服务质量",
                roles=(QuestionFramingRole.RETURN_CONTENT,),
                span_start=23,
                span_end=33,
            ),
        ),
    )

    lexer_trace = OntologyLexer(assets, vector_retriever=None).run(question, question_framing=framing)
    trace_dict = lexer_trace.to_dict()

    assert trace_dict["question_framing"]["atoms"][0]["roles"] == ["FIND_OBJECT", "FILTER_CONDITION"]
    assert any(
        signal.signal_type == "QUESTION_FRAMING_ATOM"
        and signal.text == "名称为 Service_002 的服务"
        and {"FIND_OBJECT", "FILTER_CONDITION"}.issubset(set(signal.supports))
        for signal in lexer_trace.context_signals
    )
    projection_mentions = [
        signal.text
        for signal in lexer_trace.shape_signals
        if "answer_projection_region" in signal.supports
    ]
    assert projection_mentions == ["ID", "名称", "服务质量"]


class _RecordingQuestionFramingService:
    def __init__(self, trace: QuestionFramingTrace) -> None:
        self.trace = trace
        self.calls: list[str] = []

    def run(self, question: str) -> QuestionFramingTrace:
        self.calls.append(question)
        return self.trace


class _RecordingLexer:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(self, question: str, *, question_framing: QuestionFramingTrace | None = None) -> LexerTrace:
        self.calls.append({"question": question, "question_framing": question_framing})
        return LexerTrace(
            question=question,
            matcher="fixture",
            ac_matches=(),
            selected_hits=(),
            discarded_hits=(),
            resolution_summary={},
            unmatched_fragments=(),
            vector_recalls=(),
            mentions=(),
            unmatched_spans=(),
            context_signals=(),
            shape_signals=(),
            question_framing=question_framing.to_dict() if question_framing is not None else None,
        )


class _AcceptingIntentLayer:
    def run(self, *, core_question: str, shape_signals: tuple[ContextSignal, ...]) -> IntentOutput:
        return IntentOutput(
            intent=Intent(
                primary="record_retrieval_query",
                secondary="attribute_projection_query",
                source="fixture",
                decision="accept",
                confidence=0.9,
            ),
            planning_prompt_text="fixture",
            initial_shape={
                "answer_type": InitialShapeField(
                    value="attribute_table",
                    source="fixture",
                    decision="accept",
                    confidence=1.0,
                ),
                "projection_expected": InitialShapeField(
                    value=True,
                    source="fixture",
                    decision="accept",
                    confidence=1.0,
                ),
            },
            candidates=(),
            rule_signals_used=(),
            diagnostics={},
        )


def test_runtime_pipeline_runs_question_framing_between_preprocessing_and_lexer() -> None:
    question = "查询所有服务的名称"
    framing_trace = QuestionFramingTrace(
        question=question,
        raw_response="fixture",
        atoms=(
            QuestionAtom(
                atom_id="QA1",
                text="所有服务",
                roles=(QuestionFramingRole.FIND_OBJECT,),
                span_start=2,
                span_end=6,
            ),
        ),
    )
    framing_service = _RecordingQuestionFramingService(framing_trace)
    lexer = _RecordingLexer()
    pipeline = OntologyGenerationPipeline(
        assets=OntologyAssets.from_default_resources(),
        lexer=lexer,  # type: ignore[arg-type]
        question_framing_service=framing_service,  # type: ignore[arg-type]
        intent_layer=_AcceptingIntentLayer(),  # type: ignore[arg-type]
        object_role_selection_service=None,
    )

    with pytest.raises(ClarificationNeeded) as exc_info:
        pipeline.generate(question, trace_id="trace-question-framing")

    assert exc_info.value.stage == "step_3_1"
    assert framing_service.calls == [question]
    assert lexer.calls == [{"question": question, "question_framing": framing_trace}]
