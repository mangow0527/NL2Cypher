from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from services.cypher_generator_agent.app.literals.models import LiteralResolverResult
from services.cypher_generator_agent.app.retrieval.models import (
    CandidateRetrievalResult,
    SemanticCandidate,
)

from .models import GROUNDED_UNDERSTANDING_SCHEMA_VERSION, grounded_understanding_json_schema


def build_grounded_understanding_prompt(
    *,
    question_decomposition: Mapping[str, Any] | object,
    candidates: CandidateRetrievalResult | Sequence[SemanticCandidate] | Mapping[str, Any],
    literal_results: Sequence[LiteralResolverResult | Mapping[str, Any]],
) -> str:
    payload = {
        "question_decomposition": _dump_model(question_decomposition),
        "top_candidates": [_candidate_payload(candidate) for candidate in _coerce_candidates(candidates)],
        "literal_resolver_results": [_dump_model(result) for result in literal_results],
    }
    return "\n".join(
        [
            "You are the Grounded Understanding selector for a graph-native Cypher generation pipeline.",
            f"Return only structured output for schema {GROUNDED_UNDERSTANDING_SCHEMA_VERSION}.",
            "You must choose only from top_candidates by candidate_id.",
            "Every selected binding must copy semantic_type, semantic_id, semantic_name, and owner exactly from its candidate payload.",
            "If two or more candidates are close and you cannot safely choose, put their candidate_ids in ambiguities and do not invent a selected binding for that role.",
            "Do not generate Cypher, do not connect to a database, do not explain, and do not return markdown.",
            "Input JSON:",
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
        ]
    )


def build_grounded_understanding_schema() -> dict[str, Any]:
    return grounded_understanding_json_schema()


def candidate_id(candidate: SemanticCandidate) -> str:
    return f"{candidate.semantic_type}:{candidate.semantic_id}"


def _candidate_payload(candidate: SemanticCandidate) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id(candidate),
        "semantic_type": candidate.semantic_type,
        "semantic_id": candidate.semantic_id,
        "semantic_name": candidate.semantic_name,
        "owner": candidate.owner,
        "score": candidate.score,
        "match_type": candidate.match_type,
        "evidence": [evidence.model_dump() for evidence in candidate.evidence],
        "metadata": candidate.metadata,
    }


def _coerce_candidates(
    candidates: CandidateRetrievalResult | Sequence[SemanticCandidate] | Mapping[str, Any],
) -> list[SemanticCandidate]:
    if isinstance(candidates, CandidateRetrievalResult):
        return list(candidates.candidates)
    if isinstance(candidates, Mapping):
        return [
            candidate if isinstance(candidate, SemanticCandidate) else SemanticCandidate.model_validate(candidate)
            for candidate in candidates.get("candidates", [])
        ]
    return [
        candidate if isinstance(candidate, SemanticCandidate) else SemanticCandidate.model_validate(candidate)
        for candidate in candidates
    ]


def _dump_model(value: Any) -> dict[str, Any]:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, dict):
            return dumped
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"cannot serialize grounded understanding input: {value!r}")
