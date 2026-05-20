from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .common import TextSpan, clarification, load_yaml_mapping, mapping_items, resource_path, string_list


DEFAULT_COMPOUND_DETECTION_CONFIG_PATH = resource_path("compound_detection.yaml")


@dataclass(frozen=True)
class CompoundDetectionResult:
    status: str
    can_continue: bool
    is_compound: bool
    compound_type: str
    input_question: str
    reason: str
    evidence_spans: tuple[TextSpan, ...]
    clarification: dict[str, object] | None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "can_continue": self.can_continue,
            "is_compound": self.is_compound,
            "compound_type": self.compound_type,
            "input_question": self.input_question,
            "reason": self.reason,
            "evidence_spans": [span.to_dict() for span in self.evidence_spans],
            "clarification": self.clarification,
        }


def detect_compound_query(
    core_candidate: str,
    *,
    config: dict[str, Any] | None = None,
) -> CompoundDetectionResult:
    """第 5 步：识别明显超出一问一条 Cypher 的复合查询。"""

    if not isinstance(core_candidate, str):
        raise TypeError("core_candidate must be a string")

    compound_config = config if config is not None else load_compound_detection_config()
    dependent = _detect_dependent_multi_step(core_candidate, compound_config)
    if dependent:
        return CompoundDetectionResult(
            status="clarification_required",
            can_continue=False,
            is_compound=True,
            compound_type="dependent_multi_step_query",
            input_question=core_candidate,
            reason="检测到依赖式多步查询，可能不是一条 Cypher 可以安全完成的问题。",
            evidence_spans=tuple(dependent),
            clarification=clarification(
                source_stage="compound_detection",
                reason_code="dependent_multi_step_query",
                user_message="这个问题看起来包含依赖式多步查询。请先选择你要查询的第一件事，或把问题拆成两个独立问题。",
                suggested_rewrites=["查询第一个对象的目标关系", "查询指定对象的后续关联信息"],
            ),
        )

    parallel = _detect_parallel_compound(core_candidate, compound_config)
    if parallel:
        return CompoundDetectionResult(
            status="clarification_required",
            can_continue=False,
            is_compound=True,
            compound_type="parallel_compound_query",
            input_question=core_candidate,
            reason="检测到并列复合查询，需要拆成单个查询问题。",
            evidence_spans=tuple(parallel),
            clarification=clarification(
                source_stage="compound_detection",
                reason_code="parallel_compound_query",
                user_message="这个问题像是多个并列查询。请先选择其中一个查询目标。",
                suggested_rewrites=["查询其中一个对象的目标关系"],
            ),
        )

    evidence = tuple(_allowed_single_query_evidence(core_candidate, compound_config))
    return CompoundDetectionResult(
        status="single_query",
        can_continue=True,
        is_compound=False,
        compound_type="none",
        input_question=core_candidate,
        reason="连接词后是返回内容说明，不是新的独立查询目标。",
        evidence_spans=evidence,
        clarification=None,
    )


def load_compound_detection_config(path: Path | None = None) -> dict[str, Any]:
    if path is None:
        return _load_default_compound_detection_config()
    return load_yaml_mapping(path)


@lru_cache(maxsize=1)
def _load_default_compound_detection_config() -> dict[str, Any]:
    return load_yaml_mapping(DEFAULT_COMPOUND_DETECTION_CONFIG_PATH)


def _detect_dependent_multi_step(text: str, config: dict[str, Any]) -> list[TextSpan]:
    for item in mapping_items(config.get("dependent_multi_step_patterns")):
        first = item.get("first_cue")
        if not isinstance(first, str):
            continue
        first_index = text.find(first)
        if first_index < 0:
            continue
        for cue in string_list(item.get("dependency_cues")):
            cue_index = text.find(cue, first_index + len(first))
            if cue_index >= 0:
                return [
                    TextSpan(
                        text=first,
                        kind="multi_step_first",
                        start=first_index,
                        end=first_index + len(first),
                        offset_basis="core_candidate",
                        rule_id=str(item["id"]),
                    ),
                    TextSpan(
                        text=cue,
                        kind="multi_step_dependency",
                        start=cue_index,
                        end=cue_index + len(cue),
                        offset_basis="core_candidate",
                        rule_id=str(item["id"]),
                    ),
                ]
    return []


def _detect_parallel_compound(text: str, config: dict[str, Any]) -> list[TextSpan]:
    spans: list[TextSpan] = []
    for item in mapping_items(config.get("parallel_compound_cues")):
        phrase = item.get("text")
        if not isinstance(phrase, str):
            continue
        index = text.find(phrase)
        if index >= 0:
            spans.append(
                TextSpan(
                    text=phrase,
                    kind="parallel_compound_cue",
                    start=index,
                    end=index + len(phrase),
                    offset_basis="core_candidate",
                    rule_id=str(item["id"]),
                )
            )
    spans.extend(_detect_query_after_connector(text, config))
    return _resolve_overlapping_evidence(spans)


def _detect_query_after_connector(text: str, config: dict[str, Any]) -> list[TextSpan]:
    spans: list[TextSpan] = []
    for item in mapping_items(config.get("parallel_query_after_connector_patterns")):
        connector = item.get("connector")
        if not isinstance(connector, str) or not connector:
            continue
        connector_index = text.find(connector)
        if connector_index < 0:
            continue
        right = text[connector_index + len(connector) :]
        for cue in sorted(string_list(item.get("query_cues")), key=len, reverse=True):
            cue_index = right.find(cue)
            if cue_index < 0:
                continue
            absolute_cue_index = connector_index + len(connector) + cue_index
            spans.append(
                TextSpan(
                    text=connector,
                    kind="parallel_query_connector",
                    start=connector_index,
                    end=connector_index + len(connector),
                    offset_basis="core_candidate",
                    rule_id=str(item["id"]),
                )
            )
            spans.append(
                TextSpan(
                    text=cue,
                    kind="parallel_query_intro",
                    start=absolute_cue_index,
                    end=absolute_cue_index + len(cue),
                    offset_basis="core_candidate",
                    rule_id=str(item["id"]),
                )
            )
            break
    return spans


def _allowed_single_query_evidence(text: str, config: dict[str, Any]) -> list[TextSpan]:
    allowed = config.get("allowed_single_query_cues", {})
    spans: list[TextSpan] = []
    for item in mapping_items(allowed.get("sequence_connectors") if isinstance(allowed, dict) else None):
        spans.extend(_find_phrase_spans(text, item, "sequence_connector"))
    for item in mapping_items(allowed.get("return_intros") if isinstance(allowed, dict) else None):
        spans.extend(_find_phrase_spans(text, item, "return_intro"))
    return _resolve_overlapping_evidence(spans)


def _find_phrase_spans(text: str, item: dict[str, Any], kind: str) -> list[TextSpan]:
    phrase = item.get("text")
    if not isinstance(phrase, str) or not phrase:
        return []
    spans: list[TextSpan] = []
    start = 0
    while True:
        index = text.find(phrase, start)
        if index < 0:
            return spans
        spans.append(
            TextSpan(
                text=phrase,
                kind=kind,
                start=index,
                end=index + len(phrase),
                offset_basis="core_candidate",
                rule_id=str(item["id"]),
            )
        )
        start = index + 1


def _resolve_overlapping_evidence(spans: list[TextSpan]) -> list[TextSpan]:
    ranked = sorted(spans, key=lambda span: (span.start, -(span.end - span.start), span.rule_id))
    selected: list[TextSpan] = []
    occupied: list[tuple[int, int]] = []
    for span in ranked:
        if any(span.start < end and span.end > start for start, end in occupied):
            continue
        selected.append(span)
        occupied.append((span.start, span.end))
    return sorted(selected, key=lambda span: (span.start, span.end))
