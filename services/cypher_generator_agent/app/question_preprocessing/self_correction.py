from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .common import TextSpan, clarification, load_yaml_mapping, mapping_items, resource_path, string_list
from .phrase_detection import PhraseSpan


DEFAULT_SELF_CORRECTION_CONFIG_PATH = resource_path("self_correction.yaml")


@dataclass(frozen=True)
class CorrectionEvidence:
    marker: TextSpan
    marker_group: str
    abandoned_span: TextSpan
    corrected_span: TextSpan
    confidence: str
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "marker": self.marker.to_dict(),
            "marker_group": self.marker_group,
            "abandoned_span": self.abandoned_span.to_dict(),
            "corrected_span": self.corrected_span.to_dict(),
            "confidence": self.confidence,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SelfCorrectionResult:
    status: str
    applied: bool
    input_question: str
    question_after_correction: str | None
    corrections: tuple[CorrectionEvidence, ...]
    clarification: dict[str, object] | None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "applied": self.applied,
            "input_question": self.input_question,
            "question_after_correction": self.question_after_correction,
            "corrections": [correction.to_dict() for correction in self.corrections],
            "clarification": self.clarification,
        }


def apply_self_correction(
    cleaned_question: str,
    phrase_spans: tuple[PhraseSpan, ...] | list[PhraseSpan | dict[str, Any]],
    scope_signals: dict[str, bool],
    *,
    config: dict[str, Any] | None = None,
) -> SelfCorrectionResult:
    """第 3 步：基于第 2 步 marker 的局部窗口做自我修正。"""

    if not isinstance(cleaned_question, str):
        raise TypeError("cleaned_question must be a string")

    correction_spans = [_coerce_phrase_span(span) for span in phrase_spans if _is_correction_span(span)]
    if not scope_signals.get("has_self_correction") or not correction_spans:
        return SelfCorrectionResult(
            status="no_correction",
            applied=False,
            input_question=cleaned_question,
            question_after_correction=cleaned_question,
            corrections=(),
            clarification=None,
        )

    if len(correction_spans) > 1:
        return _clarification_result(
            cleaned_question,
            "self_correction_multiple_markers",
            "我看到你多次修改了问题，但无法安全判断最终版本。请直接用一句话写出最终想查询的问题。",
        )

    correction_config = config if config is not None else load_self_correction_config()
    marker = correction_spans[0]
    marker_info = _marker_info(marker, correction_config)
    if marker_info is None:
        return _clarification_result(
            cleaned_question,
            "self_correction_unknown_marker",
            f"我看到了“{marker.text}”，但还不能确定它表示怎样的修改。请直接补充最终想查询的问题。",
        )

    if marker_info["group"] == "contrastive_correction":
        return _apply_contrastive_correction(cleaned_question, marker, marker_info, correction_config)

    if marker_info["group"] == "weak_or_ambiguous":
        return _clarification_result(
            cleaned_question,
            "self_correction_ambiguous_marker",
            f"我看到“{marker.text}”，但它可能只是普通否定，不一定是自我修正。请直接写出最终想查询的问题。",
        )

    abandoned = _extract_left_candidate(cleaned_question, marker.start, correction_config)
    corrected = _extract_right_candidate(cleaned_question, marker.end, correction_config)
    if abandoned is None:
        return _clarification_result(
            cleaned_question,
            "self_correction_missing_abandoned_text",
            f"我看到你提到了“{marker.text}”，但不确定前面哪一段需要被替换。请直接写出最终想查询的问题。",
        )
    if corrected is None:
        return _clarification_result(
            cleaned_question,
            "self_correction_missing_corrected_text",
            f"我看到你提到了“{marker.text}”，但没有找到你想改成什么。请直接补充最终想查询的对象。",
        )
    if corrected.text in _vague_corrected_texts(correction_config):
        return _clarification_result(
            cleaned_question,
            "self_correction_vague_corrected_text",
            f"我看到你想改成“{corrected.text}”，但这个表达不够明确。请直接写出最终想查询的问题。",
        )

    marker_span = _marker_to_text_span(marker)
    evidence = CorrectionEvidence(
        marker=marker_span,
        marker_group=str(marker_info["group"]),
        abandoned_span=abandoned,
        corrected_span=corrected,
        confidence=str(marker_info["confidence"]),
        reason="强修正 marker 左右候选唯一，且未跨越强边界。",
    )
    result_question = (
        cleaned_question[: abandoned.start]
        + corrected.text
        + cleaned_question[corrected.end :]
    )
    result_question = _apply_post_correction_restatement(result_question, correction_config)

    return SelfCorrectionResult(
        status="applied",
        applied=True,
        input_question=cleaned_question,
        question_after_correction=result_question,
        corrections=(evidence,),
        clarification=None,
    )


def load_self_correction_config(path: Path | None = None) -> dict[str, Any]:
    if path is None:
        return _load_default_self_correction_config()
    return load_yaml_mapping(path)


@lru_cache(maxsize=1)
def _load_default_self_correction_config() -> dict[str, Any]:
    return load_yaml_mapping(DEFAULT_SELF_CORRECTION_CONFIG_PATH)


def _is_correction_span(span: PhraseSpan | dict[str, Any]) -> bool:
    if isinstance(span, PhraseSpan):
        return span.kind == "self_correction_marker"
    return span.get("kind") == "self_correction_marker"


def _coerce_phrase_span(span: PhraseSpan | dict[str, Any]) -> PhraseSpan:
    if isinstance(span, PhraseSpan):
        return span
    return PhraseSpan(
        text=str(span["text"]),
        kind=str(span["kind"]),
        action=str(span.get("action", "correction_signal")),
        start=int(span["start"]),
        end=int(span["end"]),
        rule_id=str(span["rule_id"]),
    )


def _marker_info(marker: PhraseSpan, config: dict[str, Any]) -> dict[str, object] | None:
    for group_name, group in config.get("marker_groups", {}).items():
        if not isinstance(group, dict):
            continue
        for item in mapping_items(group.get("items")):
            if item.get("id") == marker.rule_id or item.get("text") == marker.text:
                return {
                    "group": group_name,
                    "confidence": group.get("confidence", "medium"),
                    "item": item,
                }
        for pattern in mapping_items(group.get("patterns")):
            if pattern.get("negative_cue") == marker.text:
                return {
                    "group": group_name,
                    "confidence": group.get("confidence", "medium"),
                    "item": pattern,
                }
    return None


def _extract_left_candidate(text: str, marker_start: int, config: dict[str, Any]) -> TextSpan | None:
    policy = config.get("window_policy", {})
    left_limit = max(0, marker_start - int(policy.get("max_left_chars", 24)))
    left = text[left_limit:marker_start].rstrip()
    left = left.rstrip("，、：。？！； ")
    if not left:
        return None

    local_start = left_limit
    boundaries = list(policy.get("hard_stop_punctuation", [])) + list(policy.get("soft_stop_punctuation", []))
    for boundary in string_list(policy.get("left_boundary_phrases")):
        boundaries.append(boundary)

    cut = -1
    cut_len = 0
    for boundary in boundaries:
        index = left.rfind(boundary)
        if index >= 0 and index + len(boundary) > cut + cut_len:
            cut = index
            cut_len = len(boundary)

    candidate_start = local_start + cut + cut_len if cut >= 0 else local_start
    candidate = text[candidate_start:marker_start].strip("，、：。？！； ")
    candidate_start += len(text[candidate_start:marker_start]) - len(text[candidate_start:marker_start].lstrip("，、：。？！； "))
    candidate_end = candidate_start + len(candidate)
    if not candidate:
        return None
    return TextSpan(
        text=candidate,
        kind="abandoned_text",
        start=candidate_start,
        end=candidate_end,
        offset_basis="cleaned_question",
        rule_id="left_nearest_candidate",
    )


def _extract_right_candidate(text: str, marker_end: int, config: dict[str, Any]) -> TextSpan | None:
    policy = config.get("window_policy", {})
    right_limit = min(len(text), marker_end + int(policy.get("max_right_chars", 36)))
    raw = text[marker_end:right_limit].lstrip("，、：。？！； ")
    skipped = len(text[marker_end:right_limit]) - len(raw)
    start = marker_end + skipped

    prefix = _first_prefix(raw, string_list(policy.get("right_candidate_prefixes")))
    if prefix:
        raw = raw[len(prefix) :].lstrip("，、：。？！； ")
        start += len(prefix)
        start += len(text[start:right_limit]) - len(text[start:right_limit].lstrip("，、：。？！； "))

    if not raw:
        return None

    stop_index = len(raw)
    stops = list(policy.get("hard_stop_punctuation", [])) + list(policy.get("soft_stop_punctuation", []))
    stops.extend(string_list(policy.get("right_candidate_stop_phrases")))
    for stop in sorted(stops, key=len, reverse=True):
        index = raw.find(stop)
        if index >= 0:
            stop_index = min(stop_index, index)

    candidate = raw[:stop_index].strip("，、：。？！； ")
    if not candidate:
        return None
    return TextSpan(
        text=candidate,
        kind="corrected_text",
        start=start,
        end=start + len(candidate),
        offset_basis="cleaned_question",
        rule_id="right_nearest_candidate",
    )


def _first_prefix(text: str, prefixes: list[str]) -> str | None:
    for prefix in sorted(prefixes, key=len, reverse=True):
        if text.startswith(prefix):
            return prefix
    return None


def _vague_corrected_texts(config: dict[str, Any]) -> set[str]:
    policy = config.get("decision_policy", {})
    return set(string_list(policy.get("vague_corrected_texts")))


def _apply_contrastive_correction(
    cleaned_question: str,
    marker: PhraseSpan,
    marker_info: dict[str, object],
    config: dict[str, Any],
) -> SelfCorrectionResult:
    pattern = marker_info.get("item")
    if not isinstance(pattern, dict):
        return _clarification_result(
            cleaned_question,
            "self_correction_ambiguous_marker",
            f"我看到“{marker.text}”，但无法确定修正结构。请直接写出最终想查询的问题。",
        )

    right = cleaned_question[marker.end :]
    cue_match = _find_first_cue(right, string_list(pattern.get("positive_cues")))
    if cue_match is None:
        return _clarification_result(
            cleaned_question,
            "self_correction_ambiguous_marker",
            f"我看到“{marker.text}”，但没有找到明确的肯定修正片段。请直接写出最终想查询的问题。",
        )

    cue, cue_index = cue_match
    abandoned_text = right[:cue_index].strip("，、：。？！； ")
    corrected_start = marker.end + cue_index + len(cue)
    corrected = _extract_right_candidate(cleaned_question, corrected_start, config)
    if not abandoned_text or corrected is None:
        return _clarification_result(
            cleaned_question,
            "self_correction_missing_corrected_text",
            f"我看到“{marker.text}”，但没有找到完整的 A 到 B 修正。请直接写出最终想查询的问题。",
        )

    abandoned_start = marker.end + len(right[:cue_index]) - len(right[:cue_index].lstrip("，、：。？！； "))
    abandoned = TextSpan(
        text=abandoned_text,
        kind="abandoned_text",
        start=abandoned_start,
        end=abandoned_start + len(abandoned_text),
        offset_basis="cleaned_question",
        rule_id="contrastive_left_candidate",
    )
    evidence = CorrectionEvidence(
        marker=_marker_to_text_span(marker),
        marker_group="contrastive_correction",
        abandoned_span=abandoned,
        corrected_span=corrected,
        confidence=str(marker_info["confidence"]),
        reason="否定 cue 和肯定 cue 成对出现，左右候选唯一。",
    )
    result_question = cleaned_question[: marker.start] + corrected.text + cleaned_question[corrected.end :]
    return SelfCorrectionResult(
        status="applied",
        applied=True,
        input_question=cleaned_question,
        question_after_correction=result_question,
        corrections=(evidence,),
        clarification=None,
    )


def _find_first_cue(text: str, cues: list[str]) -> tuple[str, int] | None:
    matches = [(cue, text.find(cue)) for cue in cues if text.find(cue) >= 0]
    if not matches:
        return None
    return min(matches, key=lambda item: item[1])


def _apply_post_correction_restatement(text: str, config: dict[str, Any]) -> str:
    """处理“先不看 A 了，还是 B”这类修正后的废弃话题包装。"""

    stripped = text.strip("，、：。？！； ")
    for pattern in mapping_items(config.get("post_correction_restatement_patterns")):
        prefixes = string_list(pattern.get("abandoned_prefixes"))
        cues = string_list(pattern.get("restatement_cues"))
        for prefix in prefixes:
            prefix_index = stripped.find(prefix)
            if prefix_index < 0:
                continue
            before_prefix = stripped[:prefix_index].strip("，、：。？！； ")
            if before_prefix:
                continue
            cue_match = _find_first_cue(stripped[prefix_index + len(prefix) :], cues)
            if cue_match is None:
                continue
            cue, cue_local_index = cue_match
            cue_start = prefix_index + len(prefix) + cue_local_index
            restated = stripped[cue_start + len(cue) :].lstrip("，、：。？！； ")
            if restated:
                return restated
    return text


def _marker_to_text_span(marker: PhraseSpan) -> TextSpan:
    return TextSpan(
        text=marker.text,
        kind=marker.kind,
        action=marker.action,
        start=marker.start,
        end=marker.end,
        offset_basis=getattr(marker, "offset_basis", "cleaned_question"),
        rule_id=marker.rule_id,
    )


def _clarification_result(
    input_question: str,
    reason_code: str,
    user_message: str,
) -> SelfCorrectionResult:
    return SelfCorrectionResult(
        status="clarification_required",
        applied=False,
        input_question=input_question,
        question_after_correction=None,
        corrections=(),
        clarification=clarification(
            source_stage="self_correction",
            reason_code=reason_code,
            user_message=user_message,
            suggested_rewrites=["查询某个对象的某个关系或属性"],
        ),
    )
