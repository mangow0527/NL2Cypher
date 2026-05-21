from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from services.cypher_generator_agent.app.ontology_layer.assets import OntologyAssets
from services.cypher_generator_agent.app.intent_layer.models import Intent, IntentOutput, InitialShapeField
from services.cypher_generator_agent.app.ontology_layer.ontology_path_selection import OntologyPathSelectionService


DEFAULT_INPUT = ROOT / "services/cypher_generator_agent/examples/step_3_3_ontology_path_selection_input.json"


class DemoSelector:
    def select(self, prompt_name: str, variables: dict[str, object]) -> object:
        raise AssertionError(f"unexpected LLM call for single-candidate demo: {prompt_name}")


def main() -> None:
    payload = json.loads(DEFAULT_INPUT.read_text(encoding="utf-8"))
    intent = payload["intent"]
    intent_output = IntentOutput(
        intent=Intent(
            primary=intent["primary"],
            secondary=intent["secondary"],
            source=intent["source"],
            decision=intent["decision"],
            confidence=float(intent["confidence"]),
        ),
        planning_prompt_text=str(payload.get("planning_prompt_text", "")),
        initial_shape={
            key: InitialShapeField(
                value=value["value"],
                source=value["source"],
                decision=value["decision"],
                confidence=float(value["confidence"]),
                pending_until=value.get("pending_until"),
            )
            for key, value in payload["initial_shape"].items()
        },
        candidates=(),
        rule_signals_used=(),
        diagnostics={},
    )
    trace = OntologyPathSelectionService(
        assets=OntologyAssets.from_default_resources(),
        llm_selector=DemoSelector(),
    ).fill(
        ontology_mapping=payload["ontology_mapping"],
        question=payload["question"],
    )
    print(json.dumps({"ontology_path_selection": trace.to_dict()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
