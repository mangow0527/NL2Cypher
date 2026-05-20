from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .common import TextSpan, load_yaml_mapping, mapping_items, resource_path


DEFAULT_BACKGROUND_STRIP_CONFIG_PATH = resource_path("background_strip.yaml")


@dataclass(frozen=True)
class BackgroundStripResult:
    status: str
    input_question: str
    core_candidate: str
    background_text: str | None
    boundary_span: TextSpan | None
    removed_spans: tuple[TextSpan, ...]
    clarification: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "input_question": self.input_question,
            "core_candidate": self.core_candidate,
            "background_text": self.background_text,
            "boundary_span": self.boundary_span.to_dict() if self.boundary_span else None,
            "removed_spans": [span.to_dict() for span in self.removed_spans],
            "clarification": self.clarification,
        }


def strip_background(
    question_after_correction: str,
    *,
    config: dict[str, Any] | None = None,
) -> BackgroundStripResult:
    """第 4 步：按通用边界短语剥离查询前背景。"""

    if not isinstance(question_after_correction, str):
        raise TypeError("question_after_correction must be a string")

    background_config = config if config is not None else load_background_strip_config()
    match = _find_boundary(question_after_correction, background_config)
    if match is None:
        return BackgroundStripResult(
            status="no_background",
            input_question=question_after_correction,
            core_candidate=question_after_correction,
            background_text=None,
            boundary_span=None,
            removed_spans=(),
        )

    item, start = match
    text = str(item["text"])
    end = start + len(text)
    background = question_after_correction[:start].strip("，、：。？！； ")
    # 第 4 步只移除边界前后的连接标点，不处理尾部礼貌语或句末标点。
    # 尾部噪声属于第 6 步 noise_handling 的职责。
    core_candidate = question_after_correction[end:].lstrip("，、：。？！； ")

    boundary_span = TextSpan(
        text=text,
        kind="background_query_boundary",
        start=start,
        end=end,
        offset_basis="question_after_correction",
        rule_id=str(item["id"]),
    )
    removed_spans = list(_safe_prefix_spans(question_after_correction, background_config))
    if background:
        background_start, background_span_text = _background_span_after_prefixes(
            question_after_correction,
            background,
            removed_spans,
        )
        removed_spans.append(
            TextSpan(
                text=background_span_text,
                kind="background",
                start=background_start,
                end=background_start + len(background_span_text),
                offset_basis="question_after_correction",
                rule_id="background_before_query_boundary",
            )
        )
    removed_spans.append(
        TextSpan(
            text=text,
            kind="query_intro_wrapper",
            start=start,
            end=end,
            offset_basis="question_after_correction",
            rule_id=str(item["id"]),
        )
    )

    return BackgroundStripResult(
        status="applied",
        input_question=question_after_correction,
        core_candidate=core_candidate,
        background_text=background or None,
        boundary_span=boundary_span,
        removed_spans=tuple(_dedupe_spans(removed_spans)),
    )


def load_background_strip_config(path: Path | None = None) -> dict[str, Any]:
    if path is None:
        return _load_default_background_strip_config()
    return load_yaml_mapping(path)


@lru_cache(maxsize=1)
def _load_default_background_strip_config() -> dict[str, Any]:
    return load_yaml_mapping(DEFAULT_BACKGROUND_STRIP_CONFIG_PATH)


def _find_boundary(text: str, config: dict[str, Any]) -> tuple[dict[str, Any], int] | None:
    matches: list[tuple[dict[str, Any], int]] = []
    for item in mapping_items(config.get("boundary_phrases")):
        phrase = item.get("text")
        if not isinstance(phrase, str) or not phrase:
            continue
        index = text.find(phrase)
        if index >= 0:
            matches.append((item, index))
    if not matches:
        return None
    return min(matches, key=lambda pair: (pair[1], -len(str(pair[0].get("text", "")))))


def _safe_prefix_spans(text: str, config: dict[str, Any]) -> list[TextSpan]:
    spans: list[TextSpan] = []
    for item in mapping_items(config.get("safe_prefix_spans")):
        phrase = item.get("text")
        if not isinstance(phrase, str) or not text.startswith(phrase):
            continue
        spans.append(
            TextSpan(
                text=phrase,
                kind=str(item.get("kind", "safe_prefix")),
                start=0,
                end=len(phrase),
                offset_basis="question_after_correction",
                rule_id=str(item["id"]),
            )
        )
    return spans


def _dedupe_spans(spans: list[TextSpan]) -> list[TextSpan]:
    seen: set[tuple[int, int, str]] = set()
    result: list[TextSpan] = []
    for span in spans:
        key = (span.start, span.end, span.kind)
        if key in seen:
            continue
        seen.add(key)
        result.append(span)
    return result


def _background_span_after_prefixes(
    text: str,
    background: str,
    prefix_spans: list[TextSpan],
) -> tuple[int, str]:
    start = text.find(background)
    if start < 0:
        return 0, background
    if not prefix_spans:
        return start, background

    prefix_end = max(span.end for span in prefix_spans)
    local_start = prefix_end
    while local_start < len(text) and text[local_start] in "，、：。？！； ":
        local_start += 1
    if local_start >= start + len(background):
        return start, background
    return local_start, text[local_start : start + len(background)]
