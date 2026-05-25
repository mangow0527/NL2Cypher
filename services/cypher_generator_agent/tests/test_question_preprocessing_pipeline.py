from __future__ import annotations

from pathlib import Path

import yaml

from services.cypher_generator_agent.app.natural_language_preprocessing.background_strip import strip_background
from services.cypher_generator_agent.app.natural_language_preprocessing.clarity_gate import judge_clarity
from services.cypher_generator_agent.app.natural_language_preprocessing.compound_detection import detect_compound_query
from services.cypher_generator_agent.app.natural_language_preprocessing.input_guard import guard_input
from services.cypher_generator_agent.app.natural_language_preprocessing.noise_handling import handle_noise
from services.cypher_generator_agent.app.natural_language_preprocessing.phrase_detection import detect_phrase_signals
from services.cypher_generator_agent.app.natural_language_preprocessing.pipeline import preprocess_question
from services.cypher_generator_agent.app.natural_language_preprocessing.self_correction import apply_self_correction
from services.cypher_generator_agent.app.natural_language_preprocessing.text_cleaning import clean_text


RESOURCE_DIR = Path(__file__).resolve().parents[1] / "resources" / "runtime" / "natural_language_preprocessing"

RAW_SAMPLE = (
    "你好，，现在就是我们遇到了一些咨询类  的问题，所以需要查询一下金牌服务 "
    "哦不对是银牌服务所使用的隧道和他的源网元，然后你需要 给我返 回隧道的IETF标准和源网元的IP，谢谢啦！"
)


def test_input_guard_can_run_as_independent_step() -> None:
    accepted = guard_input("查询服务名称").to_dict()
    rejected = guard_input("查询\u0000服务名称").to_dict()

    assert accepted["accepted"] is True
    assert accepted["guarded_question"] == "查询服务名称"
    assert rejected["accepted"] is False
    assert rejected["guarded_question"] is None
    assert rejected["rejection"]["reason_code"] == "invalid_control_character"


def test_self_correction_applies_strong_restatement_from_phrase_detection() -> None:
    clean_result = clean_text(RAW_SAMPLE)
    phrase_result = detect_phrase_signals(clean_result)

    result = apply_self_correction(
        phrase_result.cleaned_question,
        phrase_result.phrase_spans,
        phrase_result.scope_signals,
    )
    data = result.to_dict()

    assert data["status"] == "applied"
    assert data["applied"] is True
    assert data["question_after_correction"] == (
        "你好，现在就是我们遇到了一些咨询类的问题，所以需要查询一下银牌服务所使用的隧道和他的源网元，"
        "然后你需要给我返回隧道的IETF标准和源网元的IP，谢谢啦！"
    )
    correction = data["corrections"][0]
    assert correction["marker_group"] == "strong_restatement"
    assert correction["abandoned_span"]["text"] == "金牌服务"
    assert correction["corrected_span"]["text"] == "银牌服务"
    assert correction["marker"]["offset_basis"] == "cleaned_question"


def test_self_correction_requires_clarification_when_corrected_text_missing() -> None:
    phrase_result = detect_phrase_signals("查询金牌服务，哦不对")

    result = apply_self_correction(
        phrase_result.cleaned_question,
        phrase_result.phrase_spans,
        phrase_result.scope_signals,
    ).to_dict()

    assert result["status"] == "clarification_required"
    assert result["question_after_correction"] is None
    assert result["clarification"]["reason_code"] == "self_correction_missing_corrected_text"


def test_background_strip_extracts_core_candidate_after_correction() -> None:
    result = strip_background(
        "你好，现在就是我们遇到了一些咨询类的问题，所以需要查询一下银牌服务所使用的隧道和他的源网元，"
        "然后你需要给我返回隧道的IETF标准和源网元的IP，谢谢啦！"
    ).to_dict()

    assert result["status"] == "applied"
    assert result["background_text"] == "你好，现在就是我们遇到了一些咨询类的问题"
    assert result["boundary_span"]["rule_id"] == "background_boundary_so_need_query"
    assert result["core_candidate"] == (
        "银牌服务所使用的隧道和他的源网元，然后你需要给我返回隧道的IETF标准和源网元的IP，谢谢啦！"
    )


def test_compound_detection_allows_return_connector_but_blocks_dependent_query() -> None:
    allowed = detect_compound_query(
        "银牌服务所使用的隧道和他的源网元，然后你需要给我返回隧道的IETF标准和源网元的IP，谢谢啦！"
    ).to_dict()
    blocked = detect_compound_query("先查询银牌服务使用的隧道，再根据这些隧道查询故障告警").to_dict()
    parallel = detect_compound_query("查询银牌服务使用的隧道，然后查询金牌服务使用的源网元").to_dict()

    assert allowed["status"] == "single_query"
    assert allowed["can_continue"] is True
    assert allowed["compound_type"] == "none"
    assert any(span["text"] == "然后" for span in allowed["evidence_spans"])
    assert blocked["status"] == "clarification_required"
    assert blocked["can_continue"] is False
    assert blocked["compound_type"] == "dependent_multi_step_query"
    assert blocked["clarification"]["reason_code"] == "dependent_multi_step_query"
    assert parallel["status"] == "clarification_required"
    assert parallel["compound_type"] == "parallel_compound_query"
    assert parallel["clarification"]["reason_code"] == "parallel_compound_query"


def test_noise_handling_removes_wrappers_and_keeps_core_and_retrieval_equal() -> None:
    result = handle_noise(
        "银牌服务所使用的隧道和他的源网元，然后你需要给我返回隧道的IETF标准和源网元的IP，谢谢啦！"
    ).to_dict()

    assert result["status"] == "applied"
    assert result["core_question"] == "银牌服务所使用的隧道和其源网元，返回隧道的IETF标准和源网元的IP"
    assert result["retrieval_question"] == result["core_question"]
    assert [span["kind"] for span in result["removed_spans"]] == ["expression_wrapper", "politeness"]
    assert result["text_normalizations"][0]["rule"] == "pronoun_style_normalization"


def test_noise_handling_pronoun_normalization_is_not_business_phrase_specific() -> None:
    result = handle_noise("查询他的端口名称，谢谢").to_dict()

    assert result["core_question"] == "查询其端口名称"
    assert result["text_normalizations"][0]["from"] == "他的"
    assert result["text_normalizations"][0]["to"] == "其"


def test_clarity_gate_accepts_clear_core_and_rejects_missing_query() -> None:
    accepted = judge_clarity(
        "银牌服务所使用的隧道和其源网元，返回隧道的IETF标准和源网元的IP",
        "银牌服务所使用的隧道和其源网元，返回隧道的IETF标准和源网元的IP",
        {
            "self_correction": {"status": "applied"},
            "compound_detection": {"can_continue": True},
            "phrase_detection": {"scope_signals": {"has_query_signal": True}},
        },
    ).to_dict()
    rejected = judge_clarity(
        None,
        None,
        {"phrase_detection": {"scope_signals": {"has_query_signal": False}}},
    ).to_dict()
    followup = judge_clarity(
        "查询一下刚才的那个服务",
        "查询一下刚才的那个服务",
        {"phrase_detection": {"scope_signals": {"has_query_signal": True, "has_cross_turn_reference": True}}},
    ).to_dict()

    assert accepted["accepted"] is True
    assert accepted["reason_code"] == "accepted"
    assert accepted["clarification"] is None
    assert rejected["accepted"] is False
    assert rejected["reason_code"] == "core_question_empty"
    assert rejected["clarification"]["source_stage"] == "clarity_gate"
    assert followup["accepted"] is False
    assert followup["reason_code"] == "followup_without_context"


def test_pipeline_preprocesses_sample_without_main_cypher_flow() -> None:
    result = preprocess_question(RAW_SAMPLE).to_dict()

    assert result["accepted"] is True
    assert result["guarded_question"] == RAW_SAMPLE
    assert result["core_question"] == "银牌服务所使用的隧道和其源网元，返回隧道的IETF标准和源网元的IP"
    assert result["retrieval_question"] == result["core_question"]
    assert result["clarification"] is None
    assert result["diagnostics"]["input_guard"]["accepted"] is True
    assert result["diagnostics"]["self_correction"]["status"] == "applied"
    assert result["diagnostics"]["compound_detection"]["can_continue"] is True
    assert set(result["diagnostics"]) == {
        "input_guard",
        "text_cleaning",
        "phrase_detection",
        "self_correction",
        "background_strip",
        "compound_detection",
        "noise_handling",
        "clarity_gate",
    }


def test_pipeline_requires_explicit_query_signal() -> None:
    result = preprocess_question("Gold 服务最近有点慢，帮我看看").to_dict()

    assert result["accepted"] is False
    assert result["guarded_question"] == "Gold 服务最近有点慢，帮我看看"
    assert result["core_candidate"] is None
    assert result["core_question"] is None
    assert result["clarification"]["reason_code"] == "query_intent_missing"
    assert result["diagnostics"]["clarity_gate"]["accepted"] is False


def test_pipeline_rejects_invalid_control_characters_before_cleaning() -> None:
    result = preprocess_question("查询\u0000服务名称").to_dict()

    assert result["accepted"] is False
    assert result["guarded_question"] is None
    assert result["cleaned_question"] is None
    assert result["clarification"]["source_stage"] == "input_guard"
    assert result["clarification"]["reason_code"] == "invalid_control_character"
    assert result["diagnostics"]["input_guard"]["accepted"] is False
    assert result["diagnostics"]["text_cleaning"] is None


def test_pipeline_accepts_colloquial_statistics_query() -> None:
    result = preprocess_question("麻烦了哈，统计一下系统中服务的总数量，这个结果给我就可以。").to_dict()

    assert result["accepted"] is True
    assert result["core_question"] == "统计一下系统中服务的总数量"
    assert result["retrieval_question"] == result["core_question"]


def test_pipeline_accepts_query_action_variants_from_phrase_rules() -> None:
    examples = (
        "计算服务节点延迟属性的总数",
        "查找所有被服务使用的隧道的源网元",
        "服务节点总共有多少个",
    )

    for question in examples:
        result = preprocess_question(question).to_dict()
        assert result["accepted"] is True
        assert result["core_question"] == question


def test_pipeline_strips_colloquial_background_anchor() -> None:
    result = preprocess_question("现在要看一下这个数据，怎么说呢，主要还是查一下所有服务的ID和名称。").to_dict()

    assert result["accepted"] is True
    assert result["core_question"] == "查一下所有服务的ID和名称"


def test_pipeline_discards_abandoned_topic_after_oops_and_restatement() -> None:
    result = preprocess_question("我本来想看告警，哦不对，先不看告警了，还是查一下服务使用的隧道。").to_dict()

    assert result["accepted"] is True
    assert result["core_question"] == "查一下服务使用的隧道"
    assert "告警" not in result["core_question"]


def test_pipeline_removes_repeated_context_prefix() -> None:
    result = preprocess_question("我们现在看服务这块，嗯还是服务这块，麻烦统计一下服务节点的总数量。").to_dict()

    assert result["accepted"] is True
    assert result["core_question"] == "统计一下服务节点的总数量"


def test_clarity_gate_rechecks_query_signal_after_noise_handling() -> None:
    result = judge_clarity(
        "统计一下服务的总数量",
        "统计一下服务的总数量",
        {
            "self_correction": {"status": "no_correction"},
            "compound_detection": {"can_continue": True},
            "phrase_detection": {"scope_signals": {"has_query_signal": False}},
        },
    ).to_dict()

    assert result["accepted"] is True
    assert result["reason_code"] == "accepted"


def test_clarity_gate_rejects_statistical_consultation_texts() -> None:
    broken_report = preprocess_question("统计报表坏了怎么办").to_dict()
    word_meaning = preprocess_question("统计这个词是什么意思").to_dict()

    assert broken_report["accepted"] is False
    assert broken_report["clarification"]["reason_code"] == "query_intent_missing"
    assert word_meaning["accepted"] is False
    assert word_meaning["clarification"]["reason_code"] == "query_intent_missing"


def test_pipeline_strips_statistics_background_boundary() -> None:
    result = preprocess_question("我们这边要核对，所以需要统计服务数量").to_dict()

    assert result["accepted"] is True
    assert result["core_candidate"] == "统计服务数量"
    assert result["core_question"] == "统计服务数量"
    assert result["diagnostics"]["background_strip"]["boundary_span"]["rule_id"] == "background_boundary_so_need"


def test_self_correction_contrastive_keeps_query_action() -> None:
    result = preprocess_question("不是要查询服务，是查询隧道").to_dict()

    assert result["accepted"] is True
    assert result["core_question"] == "查询隧道"
    assert result["diagnostics"]["self_correction"]["corrections"][0]["marker_group"] == "contrastive_correction"


def test_noise_handling_yaml_does_not_contain_business_terms_in_remove_phrases() -> None:
    with (RESOURCE_DIR / "noise_handling.yaml").open(encoding="utf-8") as handle:
        noise_handling = yaml.safe_load(handle)

    remove_phrases = [item["text"] for item in noise_handling["remove_phrases"]]
    assert all("服务" not in phrase for phrase in remove_phrases)


def test_noise_handling_removes_generic_repeated_context_prefix() -> None:
    result = preprocess_question("我们现在看端口这块，嗯还是端口这块，麻烦查询端口名称。").to_dict()

    assert result["accepted"] is True
    assert result["core_question"] == "查询端口名称"


def test_self_correction_applies_contrastive_do_not_pattern() -> None:
    phrase_result = detect_phrase_signals("查询不要金牌服务，要银牌服务使用的隧道")

    result = apply_self_correction(
        phrase_result.cleaned_question,
        phrase_result.phrase_spans,
        phrase_result.scope_signals,
    ).to_dict()

    assert result["status"] == "applied"
    assert result["question_after_correction"] == "查询银牌服务使用的隧道"
    assert result["corrections"][0]["marker_group"] == "contrastive_correction"


def test_clarification_suggestions_do_not_embed_business_examples() -> None:
    correction = apply_self_correction(
        "查询金牌服务，哦不对",
        detect_phrase_signals("查询金牌服务，哦不对").phrase_spans,
        {"has_self_correction": True},
    ).to_dict()
    compound = detect_compound_query("先查询银牌服务使用的隧道，再根据这些隧道查询故障告警").to_dict()
    clarity = judge_clarity(
        None,
        None,
        {"phrase_detection": {"scope_signals": {"has_query_signal": False}}},
    ).to_dict()

    suggestions = []
    suggestions.extend(correction["clarification"]["suggested_rewrites"])
    suggestions.extend(compound["clarification"]["suggested_rewrites"])
    suggestions.extend(clarity["clarification"]["suggested_rewrites"])

    business_terms = {"Gold", "银牌服务", "金牌服务", "隧道", "故障告警", "时延"}
    assert all(not any(term in suggestion for term in business_terms) for suggestion in suggestions)


def test_self_correction_yaml_markers_are_discoverable_by_phrase_detection() -> None:
    with (RESOURCE_DIR / "self_correction.yaml").open(encoding="utf-8") as handle:
        self_correction = yaml.safe_load(handle)
    with (RESOURCE_DIR / "phrase_signals.yaml").open(encoding="utf-8") as handle:
        phrase_signals = yaml.safe_load(handle)

    phrase_items = phrase_signals["phrase_groups"]["self_correction_markers"]["items"]
    phrase_marker_pairs = {(item["id"], item["text"]) for item in phrase_items}
    yaml_marker_pairs = set()
    yaml_pattern_texts = set()
    for group in self_correction["marker_groups"].values():
        for item in group.get("items", []):
            yaml_marker_pairs.add((item["id"], item["text"]))
        for item in group.get("patterns", []):
            yaml_pattern_texts.add(item["negative_cue"])

    assert yaml_marker_pairs <= phrase_marker_pairs
    assert yaml_pattern_texts <= {text for _, text in phrase_marker_pairs}
