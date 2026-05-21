from __future__ import annotations

import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from services.cypher_generator_agent.app.ontology_layer.coreference import OntologyCoreferenceService


def main() -> int:
    if len(sys.argv) > 2:
        print("usage: python tools/demo_step_3_4_coreference.py [input_json]", file=sys.stderr)
        return 2
    input_path = (
        Path(sys.argv[1])
        if len(sys.argv) == 2
        else Path("services/cypher_generator_agent/examples/step_3_4_coreference_input.json")
    )
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    result = OntologyCoreferenceService().resolve(
        question=payload["question"],
        ontology_mapping=payload["ontology_mapping"],
        selected_paths=payload.get("selected_paths", []),
        shape_signals=payload.get("shape_signals", []),
        context_signals=payload.get("context_signals", []),
        explicit_distinction_signals=payload.get("explicit_distinction_signals", []),
        intent=payload.get("intent"),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
