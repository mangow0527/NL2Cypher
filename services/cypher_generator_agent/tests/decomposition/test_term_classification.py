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


def test_modality_word_is_classified_as_modality() -> None:
    question = "大概有多少防火墙"
    client = FakeStructuredLLMClient(
        _valid_payload(
            question,
            intent_type="count",
            substantive_terms=["防火墙"],
            modality_terms=["大概"],
            output_shape="scalar",
        )
    )

    result = QuestionDecomposer(client).decompose(question)

    assert "大概" in result.modality_terms
    assert "防火墙" in result.substantive_terms


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
    stopword_terms: list[str] | None = None,
    modality_terms: list[str] | None = None,
    time_terms: list[str] | None = None,
    unparsed_terms: list[str] | None = None,
    output_shape: str = "unknown",
) -> dict[str, Any]:
    return {
        "schema_version": "question_decomposition_v1",
        "intent_type": intent_type,
        "original_question": question,
        "target_concepts": [],
        "relation_phrases": [],
        "literal_candidates": literal_candidates or [],
        "filter_phrases": [],
        "substantive_terms": substantive_terms,
        "stopword_terms": stopword_terms or [],
        "modality_terms": modality_terms or [],
        "time_terms": time_terms or [],
        "unparsed_terms": unparsed_terms or [],
        "output_shape": output_shape,
    }
