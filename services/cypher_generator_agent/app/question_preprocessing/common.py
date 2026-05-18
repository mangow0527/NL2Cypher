from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


QUESTION_PREPROCESSING_RESOURCE_DIR = (
    Path(__file__).resolve().parents[2] / "resources" / "question_preprocessing"
)


@dataclass(frozen=True)
class TextSpan:
    """预处理阶段统一使用的文本片段坐标，end 为 exclusive。"""

    text: str
    kind: str
    start: int
    end: int
    offset_basis: str
    rule_id: str
    action: str | None = None

    def to_dict(self) -> dict[str, str | int]:
        result: dict[str, str | int] = {
            "text": self.text,
            "kind": self.kind,
            "start": self.start,
            "end": self.end,
            "offset_basis": self.offset_basis,
            "rule_id": self.rule_id,
        }
        if self.action is not None:
            result["action"] = self.action
        return result


def resource_path(filename: str) -> Path:
    return QUESTION_PREPROCESSING_RESOURCE_DIR / filename


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"question preprocessing config must be a mapping: {path}")
    return value


def mapping_items(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def clarification(
    *,
    source_stage: str,
    reason_code: str,
    user_message: str,
    suggested_rewrites: list[str],
    expected_answer_type: str = "free_text",
    options: list[str] | None = None,
) -> dict[str, object]:
    return {
        "source_stage": source_stage,
        "reason_code": reason_code,
        "user_message": user_message,
        "expected_answer_type": expected_answer_type,
        "options": options or [],
        "suggested_rewrites": suggested_rewrites,
    }
