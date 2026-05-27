from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from services.cypher_generator_agent.app.retrieval.models import (
    CandidateRetrievalResult,
    SemanticCandidate,
)
from services.cypher_generator_agent.app.literals.models import LiteralResolverResult

from .llm_client import GroundedLLMClient
from .models import (
    GROUNDED_UNDERSTANDING_SCHEMA_VERSION,
    GroundedBinding,
    GroundedUnderstanding,
    GroundedUnderstandingAttemptError,
    GroundedUnderstandingFailure,
    GroundedUnderstandingOutcome,
    parse_grounded_understanding_response,
)
from .prompt import (
    build_grounded_understanding_prompt,
    build_grounded_understanding_schema,
    candidate_id,
)


class CandidateBoundaryError(ValueError):
    """Raised when LLM output references semantics outside the candidate set."""


class GroundedUnderstandingSelector:
    def __init__(self, llm_client: GroundedLLMClient, *, max_schema_retries: int = 2) -> None:
        if max_schema_retries < 0:
            raise ValueError("max_schema_retries must be non-negative")
        self._llm_client = llm_client
        self._max_schema_retries = max_schema_retries

    def select(
        self,
        *,
        question_decomposition: Mapping[str, Any] | object,
        candidates: CandidateRetrievalResult | Sequence[SemanticCandidate] | Mapping[str, Any],
        literal_results: Sequence[object],
    ) -> GroundedUnderstandingOutcome:
        prompt = build_grounded_understanding_prompt(
            question_decomposition=question_decomposition,
            candidates=candidates,
            literal_results=literal_results,
        )
        schema = build_grounded_understanding_schema()
        provider = _provider_name(self._llm_client)
        errors: list[GroundedUnderstandingAttemptError] = []

        for attempt in range(1, self._max_schema_retries + 2):
            try:
                payload = self._llm_client.generate_structured(
                    prompt=prompt,
                    schema_name=GROUNDED_UNDERSTANDING_SCHEMA_VERSION,
                    schema=schema,
                    attempt=attempt,
                )
            except Exception as exc:
                errors.append(_attempt_error(attempt, exc))
                return GroundedUnderstandingFailure(
                    status="service_failed",
                    reason="model_invocation_failed",
                    message=str(exc) or "LLM provider invocation failed.",
                    provider=provider,
                    error_type=exc.__class__.__name__,
                    attempts=attempt,
                    retry_count=attempt - 1,
                    errors=errors,
                )

            try:
                response = parse_grounded_understanding_response(payload)
            except ValidationError as exc:
                errors.append(_attempt_error(attempt, exc))
                if attempt <= self._max_schema_retries:
                    continue
                return GroundedUnderstandingFailure(
                    status="generation_failed",
                    reason="grounded_understanding_schema_invalid",
                    message="LLM output did not satisfy grounded_understanding_v1.",
                    provider=provider,
                    error_type=exc.__class__.__name__,
                    attempts=attempt,
                    retry_count=attempt - 1,
                    errors=errors,
                )

            try:
                validate_candidate_boundaries(response, candidates, literal_results=literal_results)
            except CandidateBoundaryError as exc:
                errors.append(_attempt_error(attempt, exc))
                return GroundedUnderstandingFailure(
                    status="generation_failed",
                    reason="semantic_match_rejected",
                    message=str(exc),
                    provider=provider,
                    error_type=exc.__class__.__name__,
                    attempts=attempt,
                    retry_count=attempt - 1,
                    errors=errors,
                )
            return response

        raise RuntimeError("unreachable grounded understanding retry state")


def validate_candidate_boundaries(
    understanding: GroundedUnderstanding,
    candidates: CandidateRetrievalResult | Sequence[SemanticCandidate] | Mapping[str, Any],
    *,
    literal_results: Sequence[object] = (),
) -> None:
    index = _CandidateBoundaryIndex(_coerce_candidates(candidates))
    for binding in understanding.selected_bindings:
        _validate_binding(binding, index)
    for ambiguity in understanding.ambiguities:
        for ambiguity_candidate_id in ambiguity.candidate_ids:
            index.require(ambiguity_candidate_id)

    _validate_filter_references(understanding.filters, index)
    _validate_projection_references(understanding.projection, index, field_name="projection")
    _validate_projection_references(understanding.sort, index, field_name="sort")
    _validate_group_by_references(understanding.group_by, index)
    _validate_literal_references(understanding, literal_results)


class _CandidateBoundaryIndex:
    def __init__(self, candidates: Sequence[SemanticCandidate]) -> None:
        self._by_candidate_id = {candidate_id(candidate): candidate for candidate in candidates}

    def require(self, selected_candidate_id: str) -> SemanticCandidate:
        try:
            return self._by_candidate_id[selected_candidate_id]
        except KeyError as exc:
            raise CandidateBoundaryError(
                f"candidate_id {selected_candidate_id} is not present in candidate set"
            ) from exc

    def require_semantic_reference(
        self,
        *,
        semantic_type: str,
        semantic_id: str,
        semantic_name: str | None = None,
        owner: str | None = None,
        field_name: str,
    ) -> None:
        selected_candidate_id = f"{semantic_type}:{semantic_id}"
        candidate = self.require(selected_candidate_id)
        if candidate.semantic_type != semantic_type:
            raise CandidateBoundaryError(
                f"{field_name} semantic_type mismatch for {selected_candidate_id}: "
                f"output={semantic_type}, candidate={candidate.semantic_type}"
            )
        if candidate.semantic_id != semantic_id:
            raise CandidateBoundaryError(
                f"{field_name} semantic_id mismatch for {selected_candidate_id}: "
                f"output={semantic_id}, candidate={candidate.semantic_id}"
            )
        if semantic_name is not None and candidate.semantic_name != semantic_name:
            raise CandidateBoundaryError(
                f"{field_name} semantic_name mismatch for {selected_candidate_id}: "
                f"output={semantic_name}, candidate={candidate.semantic_name}"
            )
        if owner != candidate.owner:
            raise CandidateBoundaryError(
                f"{field_name} owner mismatch for {selected_candidate_id}: "
                f"output={owner}, candidate={candidate.owner}"
            )


def _validate_binding(binding: GroundedBinding, index: _CandidateBoundaryIndex) -> None:
    candidate = index.require(binding.candidate_id)
    if binding.candidate_id != candidate_id(candidate):
        raise CandidateBoundaryError(
            f"candidate_id mismatch for {binding.candidate_id}: candidate payload is {candidate_id(candidate)}"
        )
    if binding.semantic_type != candidate.semantic_type:
        raise CandidateBoundaryError(
            f"semantic_type mismatch for {binding.candidate_id}: "
            f"output={binding.semantic_type}, candidate={candidate.semantic_type}"
        )
    if binding.semantic_id != candidate.semantic_id:
        raise CandidateBoundaryError(
            f"semantic_id mismatch for {binding.candidate_id}: "
            f"output={binding.semantic_id}, candidate={candidate.semantic_id}"
        )
    if binding.semantic_name != candidate.semantic_name:
        raise CandidateBoundaryError(
            f"semantic_name mismatch for {binding.candidate_id}: "
            f"output={binding.semantic_name}, candidate={candidate.semantic_name}"
        )
    if binding.owner != candidate.owner:
        raise CandidateBoundaryError(
            f"owner mismatch for {binding.candidate_id}: output={binding.owner}, candidate={candidate.owner}"
        )


def _validate_filter_references(filters: list[dict[str, Any]], index: _CandidateBoundaryIndex) -> None:
    for item in filters:
        owner = item.get("owner")
        property_name = item.get("property") or item.get("property_name")
        if owner is None or property_name is None:
            continue
        index.require_semantic_reference(
            semantic_type="property",
            semantic_id=f"{owner}.{property_name}",
            semantic_name=str(property_name),
            owner=str(owner),
            field_name="filters",
        )


def _validate_projection_references(
    items: list[dict[str, Any]],
    index: _CandidateBoundaryIndex,
    *,
    field_name: str,
) -> None:
    for item in items:
        if "source" in item and "semantic_type" not in item and "property" not in item:
            continue
        semantic_type = item.get("semantic_type")
        if semantic_type is None and _looks_like_property_reference(item):
            semantic_type = "property"
        if semantic_type is None:
            continue
        _validate_reference_item(item, str(semantic_type), index, field_name=field_name)


def _validate_group_by_references(group_by: list[dict[str, Any]], index: _CandidateBoundaryIndex) -> None:
    for item in group_by:
        property_ref = item.get("property")
        if not isinstance(property_ref, Mapping):
            continue
        owner = property_ref.get("owner")
        property_name = property_ref.get("name") or property_ref.get("property_name")
        if owner is None or property_name is None:
            continue
        index.require_semantic_reference(
            semantic_type="property",
            semantic_id=f"{owner}.{property_name}",
            semantic_name=str(property_name),
            owner=str(owner),
            field_name="group_by",
        )


def _validate_literal_references(
    understanding: GroundedUnderstanding,
    literal_results: Sequence[object],
) -> None:
    allowed = {_literal_fingerprint(literal_result) for literal_result in literal_results}
    for literal in understanding.selected_literals:
        fingerprint = _literal_fingerprint(literal)
        if fingerprint not in allowed:
            raise CandidateBoundaryError(
                "selected literal resolver result is not present in input literal_results: "
                f"{literal.raw_literal} -> {literal.expected_vertex or literal.expected_edge}."
                f"{literal.expected_property}"
            )


def _literal_fingerprint(item: object) -> tuple[Any, ...]:
    result = item if isinstance(item, LiteralResolverResult) else LiteralResolverResult.model_validate(item)
    return (json.dumps(result.model_dump(mode="json"), ensure_ascii=False, sort_keys=True),)


def _validate_reference_item(
    item: Mapping[str, Any],
    semantic_type: str,
    index: _CandidateBoundaryIndex,
    *,
    field_name: str,
) -> None:
    if semantic_type == "property":
        owner, property_name = _owner_property(item)
        index.require_semantic_reference(
            semantic_type="property",
            semantic_id=f"{owner}.{property_name}",
            semantic_name=property_name,
            owner=owner,
            field_name=field_name,
        )
        return

    semantic_id = str(item.get("semantic_id") or item.get("name") or item.get(semantic_type) or "")
    if not semantic_id:
        return
    semantic_name = item.get("semantic_name") or item.get("name")
    index.require_semantic_reference(
        semantic_type=semantic_type,
        semantic_id=semantic_id,
        semantic_name=str(semantic_name) if semantic_name is not None else None,
        owner=str(item["owner"]) if item.get("owner") is not None else None,
        field_name=field_name,
    )


def _owner_property(item: Mapping[str, Any]) -> tuple[str, str]:
    nested = item.get("property")
    if isinstance(nested, Mapping):
        owner = nested.get("owner")
        property_name = nested.get("name") or nested.get("property_name")
        if owner is not None and property_name is not None:
            return str(owner), str(property_name)

    owner = item.get("owner")
    property_name = item.get("property") or item.get("property_name")
    semantic_id = item.get("semantic_id")
    if (owner is None or property_name is None) and isinstance(semantic_id, str) and "." in semantic_id:
        owner, property_name = semantic_id.split(".", 1)
    if owner is None or property_name is None:
        raise CandidateBoundaryError(f"property reference is missing owner/name: {item!r}")
    return str(owner), str(property_name)


def _looks_like_property_reference(item: Mapping[str, Any]) -> bool:
    return any(key in item for key in ("owner", "property", "property_name")) or (
        isinstance(item.get("semantic_id"), str) and "." in item["semantic_id"]
    )


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


def _provider_name(llm_client: GroundedLLMClient) -> str:
    return str(getattr(llm_client, "provider", "unknown"))


def _attempt_error(attempt: int, exc: Exception) -> GroundedUnderstandingAttemptError:
    return GroundedUnderstandingAttemptError(
        attempt=attempt,
        error_type=exc.__class__.__name__,
        message=str(exc),
    )
