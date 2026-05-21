from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.cypher_generator_agent.app.ontology_layer.assets import OntologyAssets
from services.cypher_generator_agent.app.infrastructure.errors import OntologyGenerationError
from services.cypher_generator_agent.app.intent_layer.models import Intent, IntentOutput, InitialShapeField
from services.cypher_generator_agent.app.ontology_layer.shape_finalization import OntologyShapeFinalizer


DEFAULT_INPUT = Path("services/cypher_generator_agent/examples/step_3_6_shape_finalization_input.json")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Step 3.6 shape finalization and structure precheck.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Path to Step 3.6 input JSON.")
    args = parser.parse_args()

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    finalizer = OntologyShapeFinalizer(OntologyAssets.from_default_resources())
    try:
        result = finalizer.finalize(
            intent_output=_intent_output(payload),
            ontology_mapping=payload["ontology_mapping"],
            ontology_path_selection=payload.get("ontology_path_selection"),
            coreference=payload.get("coreference"),
            binding=payload.get("binding"),
            unresolved_items=payload.get("unresolved_items", []),
            warnings=payload.get("warnings", []),
        )
    except OntologyGenerationError as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": exc.__class__.__name__,
                    "stage": exc.stage,
                    "message": exc.message,
                    "payload": exc.payload,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(1) from exc
    print(json.dumps({"status": "ok", **result.to_dict()}, ensure_ascii=False, indent=2))


def _intent_output(payload: dict[str, Any]) -> IntentOutput:
    intent = payload.get("intent", {})
    if not isinstance(intent, dict):
        intent = {}
    initial_shape = payload.get("initial_shape", {})
    if not isinstance(initial_shape, dict):
        initial_shape = {}
    return IntentOutput(
        intent=Intent(
            primary=str(intent.get("primary") or "record_retrieval_query"),
            secondary=str(intent.get("secondary") or "related_record_query"),
            source=str(intent.get("source") or "demo"),
            decision=str(intent.get("decision") or "accept"),
            confidence=float(intent.get("confidence", 1.0)),
        ),
        planning_prompt_text=str(payload.get("planning_prompt_text", "")),
        initial_shape={key: _shape_field(value) for key, value in initial_shape.items()},
        candidates=(),
        rule_signals_used=(),
        diagnostics={},
    )


def _shape_field(value: Any) -> InitialShapeField:
    if not isinstance(value, dict):
        return InitialShapeField(value=value, source="demo", decision="accept", confidence=1.0)
    return InitialShapeField(
        value=value.get("value"),
        source=str(value.get("source") or "demo"),
        decision=str(value.get("decision") or "accept"),
        confidence=float(value.get("confidence", 1.0)),
        derived_from=tuple(value.get("derived_from", ())) if isinstance(value.get("derived_from"), list) else (),
        pending_until=str(value["pending_until"]) if value.get("pending_until") is not None else None,
    )


if __name__ == "__main__":
    main()
