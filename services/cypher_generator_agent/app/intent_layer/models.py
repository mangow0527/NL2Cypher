from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _dict_without_none(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item is not None}


@dataclass(frozen=True)
class InitialShapeField:
    value: Any
    source: str
    decision: str
    confidence: float
    derived_from: tuple[str, ...] = ()
    pending_until: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _dict_without_none(
            {
                "value": self.value,
                "source": self.source,
                "decision": self.decision,
                "confidence": self.confidence,
                "derived_from": list(self.derived_from),
                "pending_until": self.pending_until,
            }
        )


@dataclass(frozen=True)
class Intent:
    primary: str
    secondary: str
    source: str
    decision: str
    confidence: float
    clarify_origin: str | None = None
    clarify_reason: str | None = None
    failed_fields: tuple[str, ...] = ()
    candidate_intents: tuple[dict[str, Any], ...] = ()
    evidence: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "primary": self.primary,
            "secondary": self.secondary,
            "source": self.source,
            "decision": self.decision,
            "confidence": self.confidence,
        }
        if self.clarify_origin is not None:
            payload["clarify_origin"] = self.clarify_origin
        if self.clarify_reason is not None:
            payload["clarify_reason"] = self.clarify_reason
        if self.failed_fields:
            payload["failed_fields"] = list(self.failed_fields)
        if self.candidate_intents:
            payload["candidate_intents"] = [dict(item) for item in self.candidate_intents]
        if self.evidence is not None:
            payload["evidence"] = dict(self.evidence)
        return payload


@dataclass(frozen=True)
class IntentOutput:
    intent: Intent
    planning_prompt_text: str
    initial_shape: dict[str, InitialShapeField]
    candidates: tuple[dict[str, Any], ...]
    rule_signals_used: tuple[str, ...]
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent.to_dict(),
            "planning_prompt_text": self.planning_prompt_text,
            "initial_shape": {key: value.to_dict() for key, value in self.initial_shape.items()},
            "candidates": [dict(item) for item in self.candidates],
            "rule_signals_used": list(self.rule_signals_used),
            "diagnostics": dict(self.diagnostics),
        }
