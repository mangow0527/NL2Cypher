from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.cypher_generator_agent.app.ontology_generation.assets import OntologyAssets
from services.cypher_generator_agent.app.ontology_generation.object_role_selection import (
    ObjectRoleSelection,
    SelectedObjectRole,
)
from services.cypher_generator_agent.app.ontology_generation.models import LexerTrace, Mention
from services.cypher_generator_agent.app.ontology_generation.ontology_mapping import OntologyMappingService


def main() -> None:
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "services/cypher_generator_agent/examples/step_2_2_ontology_mapping_input.json"
    )
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    lexer_trace = _lexer_trace(payload["lexer_output"])
    object_role_selection = _object_role_selection(payload["object_role_selection"])
    mapping = OntologyMappingService(OntologyAssets.from_default_resources()).map(
        lexer_trace=lexer_trace,
        object_role_selection=object_role_selection,
    )
    print(json.dumps({"ontology_mapping": mapping.to_dict()}, ensure_ascii=False, indent=2))


def _lexer_trace(payload: dict[str, object]) -> LexerTrace:
    return LexerTrace(
        question=str(payload["question"]),
        matcher="example_json",
        ac_matches=(),
        selected_hits=(),
        discarded_hits=(),
        resolution_summary={},
        unmatched_fragments=(),
        vector_recalls=(),
        mentions=tuple(_mention(item) for item in payload["mentions"]),
        unmatched_spans=(),
        context_signals=(),
        shape_signals=(),
    )


def _mention(payload: dict[str, object]) -> Mention:
    span = payload["span"]
    if not isinstance(span, list) or len(span) != 2:
        raise ValueError("mention span must be [start, end]")
    metadata = payload.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise ValueError("mention metadata must be an object")
    return Mention(
        canonical_id=str(payload["canonical_id"]),
        mention_type=str(payload["mention_type"]),
        surface=str(payload["surface"]),
        span_start=int(span[0]),
        span_end=int(span[1]),
        metadata=metadata,
    )


def _object_role_selection(payload: dict[str, object]) -> ObjectRoleSelection:
    selected_objects = payload.get("selected_objects") or []
    if not isinstance(selected_objects, list):
        raise ValueError("selected_objects must be a list")
    return ObjectRoleSelection(
        selected_objects=tuple(
            SelectedObjectRole(
                candidate_id=str(item["candidate_id"]),
                mention_id=str(item["mention_id"]),
                roles=tuple(str(role) for role in item["roles"]),
                evidence_ids=tuple(str(evidence_id) for evidence_id in item.get("evidence_ids", [])),
                selected_by=str(item.get("selected_by") or "example"),
                reason=str(item.get("reason") or ""),
            )
            for item in selected_objects
        )
    )


if __name__ == "__main__":
    main()
