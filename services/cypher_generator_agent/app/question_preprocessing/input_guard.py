from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
import unicodedata

from .common import clarification, load_yaml_mapping, resource_path, string_list


DEFAULT_INPUT_GUARD_CONFIG_PATH = resource_path("input_guard.yaml")


@dataclass(frozen=True)
class InputGuardCheck:
    """第 0 步的单条检查结果，便于后续定位是哪条工程规则拦截了输入。"""

    rule: str
    accepted: bool
    details: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {"rule": self.rule, "accepted": self.accepted, **self.details}


@dataclass(frozen=True)
class InputGuardResult:
    accepted: bool
    original_question: object
    guarded_question: str | None
    checks: tuple[InputGuardCheck, ...]
    rejection: dict[str, object] | None

    def to_dict(self) -> dict[str, object | None]:
        return {
            "accepted": self.accepted,
            "original_question": self.original_question,
            "guarded_question": self.guarded_question,
            "checks": [check.to_dict() for check in self.checks],
            "rejection": self.rejection,
        }


def guard_input(
    original_question: object,
    *,
    config: dict[str, Any] | None = None,
) -> InputGuardResult:
    """第 0 步：只做工程安全准入，不清洗、不改写、不判断查询意图。"""

    guard_config = config if config is not None else load_input_guard_config()
    checks: list[InputGuardCheck] = []

    if not isinstance(original_question, str):
        checks.append(InputGuardCheck("type_is_string", False, {"actual_type": type(original_question).__name__}))
        return _rejected(original_question, checks, "invalid_input_type", guard_config)
    checks.append(InputGuardCheck("type_is_string", True, {}))

    limit = int(guard_config.get("max_original_question_chars", 512))
    actual_length = len(original_question)
    length_ok = actual_length <= limit
    checks.append(
        InputGuardCheck(
            "length_within_limit",
            length_ok,
            {"limit": limit, "actual": actual_length},
        )
    )
    if not length_ok:
        return _rejected(original_question, checks, "input_too_long", guard_config)

    invalid = _first_invalid_control_character(original_question, guard_config)
    if invalid is not None:
        index, char = invalid
        checks.append(
            InputGuardCheck(
                "control_characters_allowed",
                False,
                {"codepoint": f"U+{ord(char):04X}", "index": index},
            )
        )
        return _rejected(original_question, checks, "invalid_control_character", guard_config)

    checks.append(InputGuardCheck("control_characters_allowed", True, {}))
    return InputGuardResult(
        accepted=True,
        original_question=original_question,
        guarded_question=original_question,
        checks=tuple(checks),
        rejection=None,
    )


def load_input_guard_config(path: Path | None = None) -> dict[str, Any]:
    if path is None:
        return _load_default_input_guard_config()
    return load_yaml_mapping(path)


@lru_cache(maxsize=1)
def _load_default_input_guard_config() -> dict[str, Any]:
    return load_yaml_mapping(DEFAULT_INPUT_GUARD_CONFIG_PATH)


def _first_invalid_control_character(text: str, config: dict[str, Any]) -> tuple[int, str] | None:
    policy = config.get("control_char_policy", {})
    allowed = set(string_list(policy.get("allow") if isinstance(policy, dict) else None))
    reject_categories = set(string_list(policy.get("reject_categories") if isinstance(policy, dict) else None))
    explicit_reject = set(string_list(policy.get("explicit_reject") if isinstance(policy, dict) else None))

    for index, char in enumerate(text):
        if char in explicit_reject:
            return index, char
        if char in allowed:
            continue
        if unicodedata.category(char) in reject_categories:
            return index, char
    return None


def _rejected(
    original_question: object,
    checks: list[InputGuardCheck],
    reason_code: str,
    config: dict[str, Any],
) -> InputGuardResult:
    reason = config.get("rejection_reasons", {}).get(reason_code, {})
    if not isinstance(reason, dict):
        reason = {}

    return InputGuardResult(
        accepted=False,
        original_question=original_question,
        guarded_question=None,
        checks=tuple(checks),
        rejection=clarification(
            source_stage="input_guard",
            reason_code=reason_code,
            user_message=str(reason.get("user_message", "输入文本无法安全处理，请修改后重新输入。")),
            expected_answer_type="free_text",
            options=[],
            suggested_rewrites=[],
        ),
    )
