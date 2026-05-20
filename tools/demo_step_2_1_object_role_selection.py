from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from services.cypher_generator_agent.app.ontology_generation.object_role_selection import OntologyObjectRoleSelectionService
from services.cypher_generator_agent.app.ontology_generation.models import (
    ContextSignal,
    IntentIdentity,
    IntentTrace,
    LexerTrace,
    Mention,
    ShapeField,
)


class FixtureSelector:
    def __init__(self, raw_response: str) -> None:
        self.raw_response = raw_response

    def select(self, prompt_name: str, variables: dict[str, object]) -> object:
        if prompt_name != "object_role_selection":
            raise ValueError(f"unexpected prompt: {prompt_name}")
        return SimpleNamespace(raw_response=self.raw_response)


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay Step 2.1 object role selection from a JSON fixture.")
    parser.add_argument(
        "fixture",
        nargs="?",
        default="services/cypher_generator_agent/examples/step_2_1_object_role_selection_input.json",
    )
    args = parser.parse_args()
    payload = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    service = OntologyObjectRoleSelectionService(llm_selector=FixtureSelector(str(payload["llm_raw_output"])))
    trace = service.select(
        lexer_trace=_lexer_trace(payload["lexer_output"]),
        intent_trace=_intent_trace(payload["step_2_0"]),
    )
    print(json.dumps(trace.to_dict(), ensure_ascii=False, indent=2))


def _lexer_trace(payload: dict[str, Any]) -> LexerTrace:
    return LexerTrace(
        question=str(payload["question"]),
        matcher="fixture",
        ac_matches=(),
        selected_hits=(),
        discarded_hits=(),
        resolution_summary={},
        unmatched_fragments=(),
        vector_recalls=(),
        mentions=tuple(_mention(item) for item in payload["mentions"]),
        unmatched_spans=(),
        context_signals=tuple(_signal(item) for item in payload.get("context_signals", [])),
        shape_signals=tuple(_signal(item) for item in payload.get("shape_signals", [])),
    )


def _mention(payload: dict[str, Any]) -> Mention:
    metadata = dict(payload.get("metadata") or {})
    metadata.setdefault("mention_id", payload.get("mention_id"))
    candidate_refs = payload.get("candidate_refs")
    if candidate_refs and "candidate_refs" not in metadata:
        metadata["candidate_refs"] = list(candidate_refs)
    span = payload["span"]
    return Mention(
        canonical_id=str(payload["canonical_id"]),
        mention_type=str(payload["mention_type"]),
        surface=str(payload["surface"]),
        span_start=int(span[0]),
        span_end=int(span[1]),
        metadata=metadata,
    )


def _signal(payload: dict[str, Any]) -> ContextSignal:
    span = payload["span"]
    return ContextSignal(
        signal_id=str(payload["signal_id"]),
        signal_type=str(payload["signal_type"]),
        text=str(payload["text"]),
        span_start=int(span[0]),
        span_end=int(span[1]),
        supports=tuple(str(item) for item in payload.get("supports", [])),
        strength=float(payload.get("strength", 1.0)),
    )


def _intent_trace(payload: dict[str, Any]) -> IntentTrace:
    intent = payload["intent"]
    return IntentTrace(
        intent=IntentIdentity(
            primary=str(intent["primary"]),
            secondary=str(intent["secondary"]),
            source=str(intent.get("source", "fixture")),
            decision=str(intent.get("decision", "accept")),
            confidence=float(intent.get("confidence", 1.0)),
        ),
        shape={key: _shape_field(value) for key, value in payload.get("initial_shape", {}).items()},
        candidates=tuple(dict(item) for item in payload.get("trace", {}).get("candidates", [])),
        rule_signals_used=tuple(str(item) for item in payload.get("trace", {}).get("rule_signals_used", [])),
        diagnostics={
            "fixture": True,
            "planning_prompt_text": str(payload["planning_prompt_text"]),
        },
    )


def _shape_field(payload: dict[str, Any]) -> ShapeField:
    return ShapeField(
        value=payload.get("value"),
        source=str(payload.get("source", "fixture")),
        decision=str(payload.get("decision", "accept")),
        confidence=float(payload.get("confidence", 1.0)),
        derived_from=tuple(str(item) for item in payload.get("derived_from", [])),
        pending_until=payload.get("pending_until"),
    )


if __name__ == "__main__":
    main()
