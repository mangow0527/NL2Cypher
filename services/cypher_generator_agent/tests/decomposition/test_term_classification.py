from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from services.cypher_generator_agent.app.decomposition import QuestionDecomposer


class FakeStructuredLLMClient:
    provider = "fake-llm"

    def __init__(self, response: Mapping[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def generate_structured(
        self,
        *,
        prompt: str,
        schema_name: str,
        schema: Mapping[str, Any],
        attempt: int,
    ) -> Mapping[str, Any]:
        self.calls.append(
            {
                "prompt": prompt,
                "schema_name": schema_name,
                "schema": schema,
                "attempt": attempt,
            }
        )
        return self.response


def test_polite_words_are_classified_as_stopwords() -> None:
    question = "麻烦帮我查一下 Gold 服务"
    client = FakeStructuredLLMClient(
        _valid_payload(
            question,
            intent_type="list",
            substantive_terms=["Gold", "服务"],
            stopword_terms=["麻烦", "帮我", "查一下"],
            literal_candidates=[{"text": "Gold", "kind_hint": "enum_or_name", "attached_to": "服务"}],
            output_shape="rows",
        )
    )

    result = QuestionDecomposer(client).decompose(question)

    assert result.schema_version == "question_decomposition_v1"
    assert result.result_type == "decomposition"
    assert result.intent_type == "list"
    assert result.output_shape == "rows"
    assert "Gold" in result.substantive_terms
    assert "服务" in result.substantive_terms
    assert {"麻烦", "帮我", "查一下"} <= set(result.stopword_terms)
    assert result.literal_candidates[0].text == "Gold"
    assert result.literal_candidates[0].kind_hint == "enum_or_name"
    assert result.literal_candidates[0].attached_to == "服务"
    assert client.calls[0]["schema_name"] == "question_decomposition_v1"
    assert question in client.calls[0]["prompt"]
    assert '你是图原生 Cypher 生成流水线中的"问题结构化拆解器"' in client.calls[0]["prompt"]
    assert "只输出用户问题里的表层词语" in client.calls[0]["prompt"]
    assert "两条正交的分类轴" in client.calls[0]["prompt"]
    assert "示例 3：含时间、近似、聚合，中心名词不是 literal" in client.calls[0]["prompt"]
    assert "You are the Question Decomposer" not in client.calls[0]["prompt"]


def test_modality_word_is_classified_as_modality() -> None:
    question = "大概有多少防火墙"
    client = FakeStructuredLLMClient(
        _valid_payload(
            question,
            intent_type="count",
            substantive_terms=["多少", "防火墙"],
            modality_terms=["大概"],
            target_concepts=["防火墙"],
            output_shape="scalar",
        )
    )

    result = QuestionDecomposer(client).decompose(question)

    assert "大概" in result.modality_terms
    assert "防火墙" in result.substantive_terms
    assert "防火墙" in result.target_concepts
    assert result.literal_candidates == []


def test_prompt_example_1_accepts_attribute_query_without_literal() -> None:
    question = "查询服务及其使用的隧道的时延"
    client = FakeStructuredLLMClient(
        _valid_payload(
            question,
            intent_type="list",
            output_shape="rows",
            substantive_terms=["服务", "使用", "隧道", "时延"],
            stopword_terms=["查询", "及其", "的"],
            target_concepts=["服务", "隧道", "时延"],
            relation_phrases=["使用"],
            literal_candidates=[],
            slot_terms=[
                {"text": "服务", "slot": "projection"},
                {"text": "隧道", "slot": "projection"},
                {"text": "时延", "slot": "projection", "attached_to": "服务"},
                {"text": "使用", "slot": "path"},
            ],
        )
    )

    result = QuestionDecomposer(client).decompose(question)

    assert result.result_type == "decomposition"
    assert result.substantive_terms == ["服务", "使用", "隧道", "时延"]
    assert result.stopword_terms == ["查询", "及其", "的"]
    assert result.target_concepts == ["服务", "隧道", "时延"]
    assert result.relation_phrases == ["使用"]
    assert result.literal_candidates == []
    assert [item.model_dump(exclude_none=True) for item in result.slot_terms] == [
        {"text": "服务", "slot": "projection"},
        {"text": "隧道", "slot": "projection"},
        {"text": "时延", "slot": "projection", "attached_to": "服务"},
        {"text": "使用", "slot": "path"},
    ]
    assert "轴三：语义槽位" in client.calls[0]["prompt"]


def test_prompt_example_2_accepts_literal_filter() -> None:
    question = "Gold 级别的服务使用了哪些隧道"
    client = FakeStructuredLLMClient(
        _valid_payload(
            question,
            intent_type="list",
            output_shape="rows",
            substantive_terms=["Gold", "级别", "服务", "使用", "隧道"],
            stopword_terms=["的", "了", "哪些"],
            target_concepts=["服务", "隧道"],
            relation_phrases=["使用"],
            literal_candidates=[{"text": "Gold", "kind_hint": "enum_or_name", "attached_to": "服务"}],
        )
    )

    result = QuestionDecomposer(client).decompose(question)

    assert result.target_concepts == ["服务", "隧道"]
    assert result.relation_phrases == ["使用"]
    assert result.literal_candidates[0].text == "Gold"
    assert result.literal_candidates[0].kind_hint == "enum_or_name"
    assert "Gold" in result.substantive_terms


def test_prompt_example_3_treats_firewall_as_concept_not_literal() -> None:
    question = "最近大概有多少台防火墙"
    client = FakeStructuredLLMClient(
        _valid_payload(
            question,
            intent_type="count",
            output_shape="scalar",
            substantive_terms=["多少", "台", "防火墙"],
            stopword_terms=["有"],
            modality_terms=["大概"],
            time_terms=["最近"],
            target_concepts=["防火墙"],
            literal_candidates=[],
        )
    )

    result = QuestionDecomposer(client).decompose(question)

    assert result.target_concepts == ["防火墙"]
    assert result.literal_candidates == []
    assert result.time_terms == ["最近"]
    assert result.modality_terms == ["大概"]


def test_recent_is_classified_as_time() -> None:
    question = "最近 down 的端口"
    client = FakeStructuredLLMClient(
        _valid_payload(
            question,
            intent_type="lookup",
            substantive_terms=["down", "端口"],
            time_terms=["最近"],
        )
    )

    result = QuestionDecomposer(client).decompose(question)

    assert "最近" in result.time_terms
    assert {"down", "端口"} <= set(result.substantive_terms)


def test_growth_term_is_preserved_as_substantive() -> None:
    question = "收入增长情况"
    client = FakeStructuredLLMClient(
        _valid_payload(
            question,
            intent_type="compare",
            substantive_terms=["收入", "增长", "情况"],
            output_shape="unknown",
        )
    )

    result = QuestionDecomposer(client).decompose(question)

    assert "增长" in result.substantive_terms
    assert result.substantive_terms == ["收入", "增长", "情况"]


def test_unclassified_meaningful_terms_remain_unparsed() -> None:
    question = "异常高的带宽隧道"
    client = FakeStructuredLLMClient(
        _valid_payload(
            question,
            substantive_terms=["带宽", "隧道"],
            unparsed_terms=["异常高"],
        )
    )

    result = QuestionDecomposer(client).decompose(question)

    assert result.unparsed_terms == ["异常高"]


def test_decomposition_does_not_emit_graph_bound_literal_requests_or_coverage() -> None:
    question = "Gold 服务"
    client = FakeStructuredLLMClient(
        _valid_payload(
            question,
            intent_type="lookup",
            substantive_terms=["Gold", "服务"],
            literal_candidates=[{"text": "Gold", "kind_hint": "enum_or_name", "attached_to": "服务"}],
            output_shape="rows",
        )
    )

    result = QuestionDecomposer(client).decompose(question)
    serialized = result.model_dump()

    assert "literal_requests" not in serialized
    assert "coverage" not in serialized


def _valid_payload(
    question: str,
    *,
    intent_type: str = "unknown",
    substantive_terms: list[str],
    literal_candidates: list[dict[str, str]] | None = None,
    target_concepts: list[str] | None = None,
    relation_phrases: list[str] | None = None,
    stopword_terms: list[str] | None = None,
    modality_terms: list[str] | None = None,
    time_terms: list[str] | None = None,
    unparsed_terms: list[str] | None = None,
    slot_terms: list[dict[str, str]] | None = None,
    output_shape: str = "unknown",
) -> dict[str, Any]:
    return {
        "schema_version": "question_decomposition_v1",
        "result_type": "decomposition",
        "intent_type": intent_type,
        "original_question": question,
        "target_concepts": target_concepts or [],
        "relation_phrases": relation_phrases or [],
        "literal_candidates": literal_candidates or [],
        "substantive_terms": substantive_terms,
        "stopword_terms": stopword_terms or [],
        "modality_terms": modality_terms or [],
        "time_terms": time_terms or [],
        "unparsed_terms": unparsed_terms or [],
        "slot_terms": slot_terms or [],
        "output_shape": output_shape,
    }
