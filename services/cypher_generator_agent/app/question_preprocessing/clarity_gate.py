from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .common import clarification, load_yaml_mapping, mapping_items, resource_path, string_list


DEFAULT_CLARITY_GATE_CONFIG_PATH = resource_path("clarity_gate.yaml")


@dataclass(frozen=True)
class ClarityGateResult:
    accepted: bool
    reason_code: str
    reason: str
    clarification: dict[str, object] | None

    def to_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "clarification": self.clarification,
        }


def judge_clarity(
    core_question: str | None,
    retrieval_question: str | None,
    diagnostics: dict[str, object],
    *,
    config: dict[str, Any] | None = None,
) -> ClarityGateResult:
    """第 7 步：判断预处理后的问题是否可进入后续生成链路。"""

    clarity_config = config if config is not None else load_clarity_gate_config()
    if not core_question or not retrieval_question:
        return _clarification_result("core_question_empty", clarity_config)

    if _diagnostic_value(diagnostics, ("self_correction", "status")) == "clarification_required":
        return _clarification_result("self_correction_unresolved", clarity_config)
    if _diagnostic_value(diagnostics, ("compound_detection", "can_continue")) is False:
        return _clarification_result("compound_query_unresolved", clarity_config)

    if not _has_query_signal(core_question, retrieval_question, diagnostics, clarity_config):
        return _clarification_result("query_intent_missing", clarity_config)
    if _diagnostic_value(diagnostics, ("phrase_detection", "scope_signals", "has_cross_turn_reference")) is True:
        return _clarification_result("followup_without_context", clarity_config)
    if _is_vague_reference_only(core_question):
        return _clarification_result("followup_without_context", clarity_config)

    accepted = clarity_config.get("accepted_reason", {})
    return ClarityGateResult(
        accepted=True,
        reason_code=str(accepted.get("reason_code", "accepted")),
        reason=str(accepted.get("reason", "accepted")),
        clarification=None,
    )


def load_clarity_gate_config(path: Path | None = None) -> dict[str, Any]:
    if path is None:
        return _load_default_clarity_gate_config()
    return load_yaml_mapping(path)


@lru_cache(maxsize=1)
def _load_default_clarity_gate_config() -> dict[str, Any]:
    return load_yaml_mapping(DEFAULT_CLARITY_GATE_CONFIG_PATH)


def _clarification_result(reason_code: str, config: dict[str, Any]) -> ClarityGateResult:
    reasons = config.get("clarification_reasons", {})
    reason = reasons.get(reason_code) if isinstance(reasons, dict) else None
    if not isinstance(reason, dict):
        reason = next(iter(mapping_items(reasons)), {}) if isinstance(reasons, list) else {}

    message = str(reason.get("user_message", "请补充你想查询的具体对象、指标或关系。"))
    return ClarityGateResult(
        accepted=False,
        reason_code=reason_code,
        reason=str(reason.get("reason", "输入缺少明确查询目标。")),
        clarification=clarification(
            source_stage="clarity_gate",
            reason_code=reason_code,
            user_message=message,
            expected_answer_type=str(reason.get("expected_answer_type", "free_text")),
            options=list(reason.get("options", [])) if isinstance(reason.get("options"), list) else [],
            suggested_rewrites=list(reason.get("suggested_rewrites", []))
            if isinstance(reason.get("suggested_rewrites"), list)
            else [],
        ),
    )


def _diagnostic_value(data: dict[str, object], path: tuple[str, ...]) -> object:
    value: object = data
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _has_query_signal(
    core_question: str,
    retrieval_question: str,
    diagnostics: dict[str, object],
    config: dict[str, Any],
) -> bool:
    """优先信任第 2 步信号；漏识别时基于清理后的问题做轻量复核。"""

    has_query_signal = _diagnostic_value(
        diagnostics,
        ("phrase_detection", "scope_signals", "has_query_signal"),
    )
    if has_query_signal is True:
        return True

    fallback_phrases = string_list(config.get("query_signal_fallback_phrases"))
    if not fallback_phrases:
        return False
    texts = (core_question.strip(), retrieval_question.strip())
    return any(phrase in text for text in texts for phrase in fallback_phrases)


def _is_vague_reference_only(core_question: str) -> bool:
    text = core_question.strip("，。？！；:： ")
    for prefix in ("查询一下", "查询", "查一下", "帮我查", "看一下", "统计一下", "统计", "帮我统计"):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip("，。？！；:： ")
            break
    return text in {"这个", "那个", "刚才那个", "刚才的那个", "刚才的"}
