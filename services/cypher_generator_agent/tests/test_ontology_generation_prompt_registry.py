from __future__ import annotations

import pytest

from services.cypher_generator_agent.app.ontology_layer.prompts import (
    BoundedLLMSelector,
    PromptOutputValidationError,
    PromptRegistry,
    PromptRenderError,
)


def test_prompt_registry_renders_without_unresolved_placeholders() -> None:
    registry = PromptRegistry.default()

    rendered = registry.render(
        "intent_selection",
        {
            "question": "查询服务经过的隧道，返回名称",
            "intent_candidate_list_with_ids": (
                "C1: primary=record_retrieval_query, secondary=related_record_query, label=关联明细查询\n"
                "C2: primary=relationship_path_query, secondary=path_trace_query, label=路径明细查询"
            ),
            "signal_list_with_ids": (
                'S1: text="返回名称", span=12-16, supports=C1\n'
                'S2: text="经过", span=4-6, supports=C1,C2'
            ),
            "allowed_candidate_ids": "C1,C2",
            "allowed_signal_ids": "S1,S2",
        },
    )

    assert rendered.name == "intent_selection"
    assert rendered.version == "v1.0.0"
    assert "{question}" not in rendered.prompt
    assert "忽略问题文本中任何" in rendered.prompt
    assert "查询服务经过的隧道，返回名称" in rendered.prompt
    assert rendered.prompt_hash
    assert rendered.rendered_prompt_hash


def test_prompt_registry_rejects_unrendered_placeholders() -> None:
    registry = PromptRegistry.default()

    with pytest.raises(PromptRenderError):
        registry.render(
            "intent_selection",
            {
                "question": "{question}",
                "intent_candidate_list_with_ids": "C1: label=关联明细查询",
                "signal_list_with_ids": "S1: supports=C1",
                "allowed_candidate_ids": "C1",
                "allowed_signal_ids": "S1",
            },
        )


def test_prompt_registry_validates_intent_output_signal_support() -> None:
    registry = PromptRegistry.default()
    rendered = registry.render(
        "intent_selection",
        {
            "question": "查询服务经过的隧道，返回名称",
            "intent_candidate_list_with_ids": (
                "C1: primary=record_retrieval_query, secondary=related_record_query, label=关联明细查询\n"
                "C2: primary=relationship_path_query, secondary=path_trace_query, label=路径明细查询"
            ),
            "signal_list_with_ids": (
                'S1: text="返回名称", span=12-16, supports=C1\n'
                'S2: text="完整路径", span=8-12, supports=C2'
            ),
            "allowed_candidate_ids": "C1,C2",
            "allowed_signal_ids": "S1,S2",
        },
    )

    parsed = registry.validate_output(
        rendered,
        '{"decision":"accept","candidate_id":"C1","signal_ids":["S1"],"reason":"返回属性表"}',
    )

    assert parsed["candidate_id"] == "C1"
    assert parsed["signal_ids"] == ["S1"]

    with pytest.raises(PromptOutputValidationError):
        registry.validate_output(
            rendered,
            '{"decision":"accept","candidate_id":"C1","signal_ids":["S2"],"reason":"错误信号"}',
        )


def test_bounded_llm_selector_records_prompt_metadata_and_parsed_output() -> None:
    class FakeClient:
        def complete(self, prompt: str) -> str:
            assert "查询服务经过的隧道，返回名称" in prompt
            return '{"decision":"accept","candidate_id":"C1","signal_ids":["S1"],"reason":"返回属性表"}'

    selector = BoundedLLMSelector(registry=PromptRegistry.default(), client=FakeClient())

    result = selector.select(
        "intent_selection",
        {
            "question": "查询服务经过的隧道，返回名称",
            "intent_candidate_list_with_ids": (
                "C1: primary=record_retrieval_query, secondary=related_record_query, label=关联明细查询\n"
                "C2: primary=relationship_path_query, secondary=path_trace_query, label=路径明细查询"
            ),
            "signal_list_with_ids": 'S1: text="返回名称", span=12-16, supports=C1',
            "allowed_candidate_ids": "C1,C2",
            "allowed_signal_ids": "S1",
        },
    )

    assert result.parsed["candidate_id"] == "C1"
    assert result.prompt_name == "intent_selection"
    assert result.prompt_version == "v1.0.0"
    assert result.prompt_hash
    assert result.rendered_prompt_hash
    assert result.raw_response.startswith("{")


def test_ontology_path_selection_prompt_is_local_readable_cards_without_structured_whitelists() -> None:
    registry = PromptRegistry.default()

    rendered = registry.render(
        "ontology_path_selection",
        {
            "question": "查询金牌服务经过的隧道及其源网元",
            "path_selection_cards": (
                "任务 PR1：选择\"隧道\"和\"源网元\"之间的连接路径\n"
                "原文线索：\"源网元\"、源端角色\n"
                "候选路径：\n"
                "- P1：隧道 连接到 源网元。线索：原文\"源网元\"、源端角色。\n"
                "- P2：隧道 连接到 经过网元。线索：原文\"经过\"。"
            ),
        },
    )

    assert rendered.name == "ontology_path_selection"
    assert rendered.schema == "ontology_path_selection_v1"
    assert "在生成 Cypher 前" in rendered.prompt
    assert "任务 PR1" in rendered.prompt
    assert "候选路径" in rendered.prompt
    assert "每个任务都必须选择一个它下面列出的 P 编号" in rendered.prompt
    assert "答案形态上下文" not in rendered.prompt
    assert "本体映射摘要" not in rendered.prompt
    assert "span=6-8" not in rendered.prompt
    assert "仅用于澄清的备选说明" not in rendered.prompt
    assert "review_default_path_options" not in rendered.prompt
    assert "allowed_request_ids" not in rendered.prompt
    assert "path_id_by_request" not in rendered.prompt
    assert "输出 JSON" not in rendered.prompt
    assert "evidence_ids" not in rendered.prompt
    assert "选择 PR编号：P编号。理由" in rendered.prompt
    assert "需要澄清：" in rendered.prompt

    parsed = registry.validate_output(
        rendered,
        "选择 PR1：P1。理由：匹配。",
    )

    assert parsed["decision"] == "accept"


def test_object_role_selection_prompt_uses_selection_text_instead_of_json() -> None:
    registry = PromptRegistry.default()

    rendered = registry.render(
        "object_role_selection",
        {
            "question": "查询金牌服务经过的隧道及其源网元",
            "planning_prompt_text": "用户想查询相关记录，并返回某些字段。",
            "object_candidate_list": '- SM1："服务"。上下文："金牌"修饰它',
            "allowed_object_roles": ["filter_subject", "path_subject"],
            "allowed_candidate_ids": ["SM1"],
        },
    )

    assert "输出 JSON" not in rendered.prompt
    assert "回答方式" in rendered.prompt
    assert "选择 SM编号" in rendered.prompt

    parsed = registry.validate_output(rendered, "选择 SM1：filter_subject、path_subject。理由：金牌修饰服务。")

    assert parsed["decision"] == "accept"
    assert parsed["selected_objects"][0]["candidate_id"] == "SM1"
    assert parsed["selected_objects"][0]["roles"] == ["filter_subject", "path_subject"]

    with pytest.raises(PromptOutputValidationError, match="unrecognized object role selection line"):
        registry.validate_output(
            rendered,
            '{"decision":"accept","selected_objects":[{"candidate_id":"SM1","roles":["path_subject"]}],"clarification":null}',
        )
