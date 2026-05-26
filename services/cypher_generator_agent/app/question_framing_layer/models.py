from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class QuestionFramingRole(Enum):
    FIND_OBJECT = "FIND_OBJECT"
    FILTER_CONDITION = "FILTER_CONDITION"
    RELATION_PATH = "RELATION_PATH"
    RETURN_CONTENT = "RETURN_CONTENT"
    AGG_SORT_TIME = "AGG_SORT_TIME"
    UNKNOWN = "UNKNOWN"

    @property
    def label(self) -> str:
        return _ROLE_LABELS[self]


_ROLE_LABELS: dict[QuestionFramingRole, str] = {
    QuestionFramingRole.FIND_OBJECT: "找什么对象",
    QuestionFramingRole.FILTER_CONDITION: "用什么条件筛选",
    QuestionFramingRole.RELATION_PATH: "通过什么关系继续找",
    QuestionFramingRole.RETURN_CONTENT: "最后返回什么",
    QuestionFramingRole.AGG_SORT_TIME: "是否涉及统计、排序或时间",
    QuestionFramingRole.UNKNOWN: "不确定",
}

_ROLE_BY_LABEL = {label: role for role, label in _ROLE_LABELS.items()}


def normalize_question_framing_role(raw_role: str) -> QuestionFramingRole:
    normalized = str(raw_role or "").strip()
    if normalized in QuestionFramingRole.__members__:
        return QuestionFramingRole[normalized]
    for role in QuestionFramingRole:
        if normalized == role.value:
            return role
    for label, role in _ROLE_BY_LABEL.items():
        if label in normalized:
            return role
    return QuestionFramingRole.UNKNOWN


@dataclass(frozen=True)
class QuestionAtom:
    atom_id: str
    text: str
    roles: tuple[QuestionFramingRole, ...]
    span_start: int | None = None
    span_end: int | None = None
    confidence: float = 0.8
    raw_role_text: str = ""

    @property
    def span(self) -> tuple[int, int] | None:
        if self.span_start is None or self.span_end is None:
            return None
        return (self.span_start, self.span_end)

    def has_role(self, role: QuestionFramingRole) -> bool:
        return role in self.roles

    def overlaps(self, start: int, end: int) -> bool:
        if self.span_start is None or self.span_end is None:
            return False
        return start < self.span_end and end > self.span_start

    def contains(self, start: int, end: int) -> bool:
        if self.span_start is None or self.span_end is None:
            return False
        return self.span_start <= start and end <= self.span_end

    def to_dict(self) -> dict[str, Any]:
        return {
            "atom_id": self.atom_id,
            "text": self.text,
            "roles": [role.value for role in self.roles],
            "span": list(self.span) if self.span is not None else None,
            "confidence": self.confidence,
            "raw_role_text": self.raw_role_text,
        }


@dataclass(frozen=True)
class QuestionFramingTrace:
    question: str
    raw_response: str
    atoms: tuple[QuestionAtom, ...]
    retrieval_plan: dict[str, Any] = field(default_factory=dict)
    diagnostics: tuple[str, ...] = ()
    enabled: bool = True
    prompt: str = ""

    @classmethod
    def empty(cls, question: str, *, reason: str) -> "QuestionFramingTrace":
        return cls(
            question=question,
            raw_response="",
            atoms=(),
            diagnostics=(reason,),
            enabled=False,
        )

    def atoms_with_role(self, role: QuestionFramingRole) -> tuple[QuestionAtom, ...]:
        return tuple(atom for atom in self.atoms if atom.has_role(role))

    def roles_for_span(self, start: int, end: int) -> tuple[QuestionFramingRole, ...]:
        roles: list[QuestionFramingRole] = []
        for atom in self.atoms:
            if not atom.overlaps(start, end):
                continue
            for role in atom.roles:
                if role not in roles:
                    roles.append(role)
        return tuple(roles)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "question": self.question,
            "prompt": self.prompt,
            "raw_response": self.raw_response,
            "atoms": [atom.to_dict() for atom in self.atoms],
            "retrieval_plan": dict(self.retrieval_plan),
            "diagnostics": list(self.diagnostics),
        }
