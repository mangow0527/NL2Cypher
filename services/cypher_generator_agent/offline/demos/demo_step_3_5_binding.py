from __future__ import annotations

import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.cypher_generator_agent.app.ontology_layer.binding import OntologyBindingService
from services.cypher_generator_agent.app.intent_layer.models import Intent, IntentOutput, InitialShapeField
from services.cypher_generator_agent.app.ontology_layer.models import ContextSignal


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("services/cypher_generator_agent/examples/step_3_5_binding_input.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    intent_payload = payload["intent"]
    intent_output = IntentOutput(
        intent=Intent(
            primary=intent_payload["primary"],
            secondary=intent_payload["secondary"],
            source="example",
            decision="accept",
            confidence=1.0,
        ),
        planning_prompt_text=str(intent_payload.get("planning_prompt_text", "")),
        initial_shape={
            key: InitialShapeField(value, "example", "accept" if value is not None else "pending", 1.0)
            for key, value in intent_payload.get("shape", {}).items()
        },
        candidates=(),
        rule_signals_used=(),
        diagnostics={},
    )
    trace = OntologyBindingService().bind(
        ontology_mapping=payload["ontology_mapping"],
        merged_nodes=payload["merged_nodes"],
        candidate_family=payload.get("candidate_family", {}),
        context_signals=tuple(_signal(item) for item in payload.get("context_signals", [])),
        shape_signals=tuple(_signal(item) for item in payload.get("shape_signals", [])),
        intent_output=intent_output,
        question=payload["question"],
    )
    print(json.dumps({"bindings": trace.to_dict()}, ensure_ascii=False, indent=2))
    return 0


def _signal(payload: dict[str, object]) -> ContextSignal:
    span = payload.get("span", [0, 0])
    return ContextSignal(
        signal_id=str(payload["signal_id"]),
        signal_type=str(payload.get("type", "")),
        text=str(payload.get("text", "")),
        span_start=int(span[0]),
        span_end=int(span[1]),
        supports=tuple(str(item) for item in payload.get("supports", [])),
        strength=float(payload.get("strength", 1.0)),
    )


if __name__ == "__main__":
    raise SystemExit(main())
