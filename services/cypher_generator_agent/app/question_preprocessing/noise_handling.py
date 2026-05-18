from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .common import TextSpan, load_yaml_mapping, mapping_items, resource_path, string_list


DEFAULT_NOISE_HANDLING_CONFIG_PATH = resource_path("noise_handling.yaml")


@dataclass(frozen=True)
class TextNormalization:
    rule: str
    from_text: str
    to_text: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "rule": self.rule,
            "from": self.from_text,
            "to": self.to_text,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class NoiseHandlingResult:
    status: str
    input_question: str
    core_question: str
    retrieval_question: str
    removed_spans: tuple[TextSpan, ...]
    text_normalizations: tuple[TextNormalization, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "input_question": self.input_question,
            "core_question": self.core_question,
            "retrieval_question": self.retrieval_question,
            "removed_spans": [span.to_dict() for span in self.removed_spans],
            "text_normalizations": [normalization.to_dict() for normalization in self.text_normalizations],
        }


def handle_noise(
    core_candidate: str,
    *,
    config: dict[str, Any] | None = None,
) -> NoiseHandlingResult:
    """第 6 步：删除表达包装和礼貌语，保留用户原始查询含义。"""

    if not isinstance(core_candidate, str):
        raise TypeError("core_candidate must be a string")

    noise_config = config if config is not None else load_noise_handling_config()
    text = core_candidate
    removed_spans = _collect_removed_spans(core_candidate, noise_config)
    for span in sorted(removed_spans, key=lambda item: item.start, reverse=True):
        text = text[: span.start] + text[span.end :]

    normalizations: list[TextNormalization] = []
    for item in mapping_items(noise_config.get("pronoun_prefix_normalizations")):
        source = item.get("from_prefix")
        target = item.get("to_prefix")
        if not isinstance(source, str) or not isinstance(target, str) or source not in text:
            continue
        text = text.replace(source, target)
        normalizations.append(
            TextNormalization(
                rule=str(item.get("rule", item.get("id", "style_normalization"))),
                from_text=source,
                to_text=target,
                reason=str(item.get("reason", "style_normalization")),
            )
        )

    text = _tidy_after_removal(text, noise_config)
    status = "applied" if removed_spans or normalizations or text != core_candidate else "no_noise"
    return NoiseHandlingResult(
        status=status,
        input_question=core_candidate,
        core_question=text,
        retrieval_question=text,
        removed_spans=tuple(sorted(removed_spans, key=lambda span: span.start)),
        text_normalizations=tuple(normalizations),
    )


def load_noise_handling_config(path: Path | None = None) -> dict[str, Any]:
    if path is None:
        return _load_default_noise_handling_config()
    return load_yaml_mapping(path)


@lru_cache(maxsize=1)
def _load_default_noise_handling_config() -> dict[str, Any]:
    return load_yaml_mapping(DEFAULT_NOISE_HANDLING_CONFIG_PATH)


def _collect_removed_spans(text: str, config: dict[str, Any]) -> list[TextSpan]:
    spans: list[TextSpan] = []
    occupied: list[tuple[int, int]] = []
    items = sorted(mapping_items(config.get("remove_phrases")), key=lambda item: len(str(item.get("text", ""))), reverse=True)
    for item in items:
        phrase = item.get("text")
        if not isinstance(phrase, str) or not phrase:
            continue
        start = 0
        while True:
            index = text.find(phrase, start)
            if index < 0:
                break
            end = index + len(phrase)
            if not _overlaps(index, end, occupied):
                spans.append(
                    TextSpan(
                        text=phrase,
                        kind=str(item.get("kind", "noise")),
                        start=index,
                        end=end,
                        offset_basis="core_candidate",
                        rule_id=str(item["id"]),
                    )
                )
                occupied.append((index, end))
            start = index + 1
    return spans


def _tidy_after_removal(text: str, config: dict[str, Any]) -> str:
    while "，，" in text:
        text = text.replace("，，", "，")
    while "  " in text:
        text = text.replace("  ", " ")
    text = text.strip()
    punctuation = set(string_list(config.get("strip_trailing_punctuation")))
    punctuation.update({"，", "、", "。", "！", "？", "；", ";", ":", "："})
    text = _strip_edge_punctuation(text, punctuation)
    text = _strip_trailing_particles(text, string_list(config.get("strip_trailing_particles")))
    text = _strip_edge_punctuation(text, punctuation)
    return text


def _strip_edge_punctuation(text: str, punctuation: set[str]) -> str:
    while text and text[-1] in punctuation:
        text = text[:-1].rstrip()
    while text and text[0] in punctuation:
        text = text[1:].lstrip()
    return text


def _strip_trailing_particles(text: str, particles: list[str]) -> str:
    changed = True
    while changed and text:
        changed = False
        for particle in sorted(particles, key=len, reverse=True):
            if particle and text.endswith(particle):
                text = text[: -len(particle)].rstrip()
                changed = True
                break
    return text


def _overlaps(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start < used_end and end > used_start for used_start, used_end in ranges)
