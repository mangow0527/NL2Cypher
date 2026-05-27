from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from services.cypher_generator_agent.app.literals.models import LiteralResolverResult
from services.cypher_generator_agent.app.retrieval.models import (
    CandidateRetrievalResult,
    SemanticCandidate,
)
from services.cypher_generator_agent.app.semantic_model.registry import (
    GraphSemanticRegistry,
    RegistryLookupError,
)

from .models import (
    BindingPlan,
    CandidateBinding,
    EdgeBinding,
    FilterBinding,
    LiteralBinding,
    MetricBinding,
    PathPatternBinding,
    PropertyBinding,
    VertexBinding,
)


_QUERY_SHAPE_ALIASES = {
    "lookup": "vertex_lookup",
    "vertex": "vertex_lookup",
    "vertex_lookup": "vertex_lookup",
    "single_hop": "single_hop_traversal",
    "single_hop_traversal": "single_hop_traversal",
    "variable_path": "variable_path_traversal",
    "variable_path_traversal": "variable_path_traversal",
    "named_path": "named_path_pattern",
    "named_path_pattern": "named_path_pattern",
    "metric_aggregate": "metric_aggregate",
    "aggregate": "ad_hoc_aggregate",
    "ad_hoc_aggregate": "ad_hoc_aggregate",
    "top_n": "top_n",
    "two_step_aggregate": "two_step_aggregate",
}
_OPERATOR_ALIASES = {
    "=": "eq",
    "==": "eq",
    "eq": "eq",
    "!=": "neq",
    "<>": "neq",
    "neq": "neq",
    ">": "gt",
    "gt": "gt",
    ">=": "gte",
    "gte": "gte",
    "<": "lt",
    "lt": "lt",
    "<=": "lte",
    "lte": "lte",
    "in": "in",
    "contains": "contains",
}


class BindingValidationError(ValueError):
    """Raised when grounded understanding selects an unbindable semantic name."""


class SemanticBinder:
    def __init__(
        self,
        registry: GraphSemanticRegistry,
        *,
        fuzzy_assumption_threshold: float = 0.95,
    ) -> None:
        self.registry = registry
        self.fuzzy_assumption_threshold = fuzzy_assumption_threshold

    def bind(
        self,
        grounded_understanding: Mapping[str, Any],
        *,
        candidates: CandidateRetrievalResult | Sequence[SemanticCandidate] | Mapping[str, Any],
    ) -> BindingPlan:
        candidate_index = _CandidateIndex(_coerce_candidates(candidates))
        literal_bindings = self._bind_literals(grounded_understanding)
        filter_bindings = self._bind_filters(grounded_understanding, candidate_index, literal_bindings)

        property_bindings = self._bind_properties(grounded_understanding, candidate_index)
        for filter_binding in filter_bindings:
            property_binding = self._bind_property(
                {"owner": filter_binding.owner, "name": filter_binding.property},
                candidate_index,
            )
            property_bindings = _append_unique_property(property_bindings, property_binding)

        assumptions = _coerce_assumptions(grounded_understanding.get("assumptions", []))
        assumptions.extend(self._fuzzy_literal_assumptions(literal_bindings))
        projection = self._bind_projection(grounded_understanding, candidate_index)
        sort = self._bind_sort(grounded_understanding, candidate_index)

        return BindingPlan(
            query_shape=_normalize_query_shape(grounded_understanding.get("query_shape")),
            vertex_bindings=self._bind_vertices(grounded_understanding, candidate_index),
            edge_bindings=self._bind_edges(grounded_understanding, candidate_index),
            property_bindings=property_bindings,
            literal_bindings=literal_bindings,
            metric_bindings=self._bind_metrics(grounded_understanding, candidate_index),
            path_pattern_bindings=self._bind_path_patterns(grounded_understanding, candidate_index),
            filters=filter_bindings,
            projection=projection,
            sort=sort,
            limit=grounded_understanding.get("limit"),
            assumptions=assumptions,
        )

    def _bind_vertices(
        self,
        grounded: Mapping[str, Any],
        candidate_index: "_CandidateIndex",
    ) -> list[VertexBinding]:
        bindings: list[VertexBinding] = []
        for item in _selected_items(grounded, "selected_vertices", "vertices", "vertex_bindings"):
            name = _extract_name(item, "vertex")
            self._require_registry("vertex", name, self.registry.get_vertex)
            candidate = candidate_index.require("vertex", name)
            bindings = _append_unique_named(bindings, VertexBinding(name=name, candidate=candidate))
        return bindings

    def _bind_edges(
        self,
        grounded: Mapping[str, Any],
        candidate_index: "_CandidateIndex",
    ) -> list[EdgeBinding]:
        bindings: list[EdgeBinding] = []
        for item in _selected_items(grounded, "selected_edges", "edges", "edge_bindings"):
            name = _extract_name(item, "edge")
            self._require_registry("edge", name, self.registry.get_edge)
            candidate = candidate_index.require("edge", name)
            bindings = _append_unique_named(bindings, EdgeBinding(name=name, candidate=candidate))
        return bindings

    def _bind_properties(
        self,
        grounded: Mapping[str, Any],
        candidate_index: "_CandidateIndex",
    ) -> list[PropertyBinding]:
        bindings: list[PropertyBinding] = []
        for item in _selected_items(grounded, "selected_properties", "properties", "property_bindings"):
            binding = self._bind_property(item, candidate_index)
            bindings = _append_unique_property(bindings, binding)
        return bindings

    def _bind_property(
        self,
        item: Any,
        candidate_index: "_CandidateIndex",
    ) -> PropertyBinding:
        owner, name = _extract_owner_name(item)
        self._require_registry("property", f"{owner}.{name}", lambda _: self.registry.get_property(owner, name))
        candidate = candidate_index.require("property", f"{owner}.{name}")
        return PropertyBinding(owner=owner, name=name, candidate=candidate)

    def _bind_metrics(
        self,
        grounded: Mapping[str, Any],
        candidate_index: "_CandidateIndex",
    ) -> list[MetricBinding]:
        bindings: list[MetricBinding] = []
        for item in _selected_items(grounded, "selected_metrics", "metrics", "metric_bindings"):
            name = _extract_name(item, "metric")
            self._require_registry("metric", name, self.registry.get_metric)
            candidate = candidate_index.require("metric", name)
            bindings = _append_unique_named(bindings, MetricBinding(name=name, candidate=candidate))
        return bindings

    def _bind_path_patterns(
        self,
        grounded: Mapping[str, Any],
        candidate_index: "_CandidateIndex",
    ) -> list[PathPatternBinding]:
        bindings: list[PathPatternBinding] = []
        for item in _selected_items(
            grounded,
            "selected_path_patterns",
            "path_patterns",
            "path_pattern_bindings",
        ):
            name = _extract_name(item, "path_pattern")
            self._require_registry("path_pattern", name, self.registry.get_path_pattern)
            candidate = candidate_index.require("path_pattern", name)
            bindings = _append_unique_named(bindings, PathPatternBinding(name=name, candidate=candidate))
        return bindings

    def _bind_literals(self, grounded: Mapping[str, Any]) -> list[LiteralBinding]:
        bindings: list[LiteralBinding] = []
        for item in _selected_items(
            grounded,
            "selected_literals",
            "literal_resolver_results",
            "resolved_literals",
            "literal_bindings",
        ):
            result = _coerce_literal_result(item)
            owner = result.expected_vertex or result.expected_edge
            if owner is not None:
                self._require_registry(
                    "property",
                    f"{owner}.{result.expected_property}",
                    lambda _: self.registry.get_property(owner, result.expected_property),
                )
            bindings.append(
                LiteralBinding(
                    raw_literal=result.raw_literal,
                    resolved=result.resolved,
                    value=_resolved_literal_value(result),
                    normalized_value=result.normalized_value,
                    match_type=result.match_type,
                    confidence=result.confidence,
                    owner=owner,
                    property=result.expected_property,
                    evidence=result.evidence,
                    alternatives=result.alternatives,
                    requires_user_choice=result.requires_user_choice,
                    value_index_miss=result.value_index_miss,
                    error_code=result.error_code,
                )
            )
        return bindings

    def _bind_filters(
        self,
        grounded: Mapping[str, Any],
        candidate_index: "_CandidateIndex",
        literal_bindings: list[LiteralBinding],
    ) -> list[FilterBinding]:
        filters: list[FilterBinding] = []
        for item in _selected_items(grounded, "filters", "selected_filters"):
            if not isinstance(item, Mapping):
                raise BindingValidationError(f"filter binding must be a mapping, got {item!r}")
            owner, property_name = _extract_owner_name(item)
            self._bind_property({"owner": owner, "name": property_name}, candidate_index)

            inline_literal = _literal_from_filter(item)
            if inline_literal is not None:
                _validate_filter_literal_match(item, inline_literal)
                literal_bindings.append(inline_literal)
            raw_literal = _extract_raw_literal(item, inline_literal)
            literal = inline_literal or _find_literal_binding(literal_bindings, owner, property_name, raw_literal)
            if literal is None:
                raise BindingValidationError(
                    f"filter {owner}.{property_name} requires a matching literal resolver result"
                )
            filters.append(
                FilterBinding(
                    owner=owner,
                    property=property_name,
                    operator=_normalize_operator(item.get("operator") or item.get("op") or "="),
                    raw_literal=raw_literal,
                    value=literal.value if literal is not None else item.get("value"),
                    literal=literal,
                )
            )
        return filters

    def _bind_projection(
        self,
        grounded: Mapping[str, Any],
        candidate_index: "_CandidateIndex",
    ) -> list[dict[str, Any]]:
        projection = _coerce_dict_list(grounded.get("projection", []), "projection")
        for item in projection:
            self._validate_semantic_reference(item, candidate_index, field_name="projection")
        return projection

    def _bind_sort(
        self,
        grounded: Mapping[str, Any],
        candidate_index: "_CandidateIndex",
    ) -> list[dict[str, Any]]:
        sort = _coerce_dict_list(grounded.get("sort", []), "sort")
        for item in sort:
            self._validate_semantic_reference(item, candidate_index, field_name="sort")
        return sort

    def _validate_semantic_reference(
        self,
        item: Mapping[str, Any],
        candidate_index: "_CandidateIndex",
        *,
        field_name: str,
    ) -> None:
        semantic_type = item.get("semantic_type")
        if semantic_type is None:
            if _looks_like_property_reference(item):
                semantic_type = "property"
            elif "source" in item:
                _validate_source_reference(item, field_name=field_name)
                return
            else:
                raise BindingValidationError(
                    f"{field_name} item must declare semantic_type, property, or source: {item!r}"
                )

        try:
            if semantic_type == "property":
                owner, property_name = _extract_owner_name(item)
                self._require_registry(
                    "property",
                    f"{owner}.{property_name}",
                    lambda _: self.registry.get_property(owner, property_name),
                )
                candidate_index.require("property", f"{owner}.{property_name}")
                return
            name = _extract_name(item, str(semantic_type))
            if semantic_type == "vertex":
                self._require_registry("vertex", name, self.registry.get_vertex)
            elif semantic_type == "edge":
                self._require_registry("edge", name, self.registry.get_edge)
            elif semantic_type == "metric":
                self._require_registry("metric", name, self.registry.get_metric)
            elif semantic_type == "path_pattern":
                self._require_registry("path_pattern", name, self.registry.get_path_pattern)
            else:
                raise BindingValidationError(f"{field_name} has unsupported semantic_type {semantic_type}")
            candidate_index.require(str(semantic_type), name)
        except BindingValidationError as exc:
            raise BindingValidationError(f"{field_name} semantic reference rejected: {exc}") from exc

    def _fuzzy_literal_assumptions(self, literal_bindings: list[LiteralBinding]) -> list[dict[str, Any]]:
        assumptions: list[dict[str, Any]] = []
        for literal in literal_bindings:
            if (
                literal.resolved
                and literal.match_type == "fuzzy_text"
                and literal.confidence >= self.fuzzy_assumption_threshold
            ):
                assumptions.append(
                    {
                        "type": "literal_fuzzy_match",
                        "raw_literal": literal.raw_literal,
                        "owner": literal.owner,
                        "property": literal.property,
                        "value": literal.value,
                        "confidence": literal.confidence,
                    }
                )
        return assumptions

    def _require_registry(self, object_type: str, name: str, lookup: Any) -> None:
        try:
            lookup(name)
        except RegistryLookupError as exc:
            raise BindingValidationError(
                f"cannot bind {object_type} {name}: not found in semantic registry"
            ) from exc


class _CandidateIndex:
    def __init__(self, candidates: Iterable[SemanticCandidate]) -> None:
        self._by_key: dict[tuple[str, str], CandidateBinding] = {}
        for candidate in candidates:
            binding = _candidate_binding(candidate)
            self._by_key[(candidate.semantic_type, candidate.semantic_id)] = binding

    def require(self, semantic_type: str, semantic_id: str) -> CandidateBinding:
        try:
            return self._by_key[(semantic_type, semantic_id)]
        except KeyError as exc:
            raise BindingValidationError(
                f"cannot bind {semantic_type} {semantic_id}: not present in candidate set"
            ) from exc


def _coerce_candidates(
    candidates: CandidateRetrievalResult | Sequence[SemanticCandidate] | Mapping[str, Any],
) -> list[SemanticCandidate]:
    if isinstance(candidates, CandidateRetrievalResult):
        return list(candidates.candidates)
    if isinstance(candidates, Mapping):
        return [SemanticCandidate.model_validate(candidate) for candidate in candidates.get("candidates", [])]
    return [
        candidate if isinstance(candidate, SemanticCandidate) else SemanticCandidate.model_validate(candidate)
        for candidate in candidates
    ]


def _candidate_binding(candidate: SemanticCandidate) -> CandidateBinding:
    return CandidateBinding(
        semantic_type=candidate.semantic_type,
        semantic_id=candidate.semantic_id,
        semantic_name=candidate.semantic_name,
        score=candidate.score,
        match_type=candidate.match_type,
        owner=candidate.owner,
        evidence=[evidence.model_dump() for evidence in candidate.evidence],
        metadata=candidate.metadata,
    )


def _selected_items(grounded: Mapping[str, Any], *keys: str) -> list[Any]:
    items: list[Any] = []
    for key in keys:
        value = grounded.get(key, [])
        if value is None:
            continue
        if isinstance(value, list | tuple):
            items.extend(value)
        else:
            items.append(value)
    return items


def _extract_name(item: Any, object_type: str) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, SemanticCandidate):
        return item.semantic_id
    if isinstance(item, Mapping):
        for key in ("name", "semantic_id", "semantic_name", object_type):
            value = item.get(key)
            if value:
                return str(value)
    raise BindingValidationError(f"cannot extract {object_type} name from {item!r}")


def _extract_owner_name(item: Any) -> tuple[str, str]:
    if isinstance(item, str):
        if "." not in item:
            raise BindingValidationError(f"property binding must be qualified as owner.name: {item}")
        owner, name = item.split(".", 1)
        return owner, name
    if isinstance(item, SemanticCandidate):
        if item.owner is None:
            raise BindingValidationError(f"property candidate is missing owner: {item.semantic_id}")
        return item.owner, item.semantic_name
    if isinstance(item, Mapping):
        nested_property = item.get("property")
        if isinstance(nested_property, Mapping):
            owner = nested_property.get("owner")
            name = nested_property.get("name") or nested_property.get("property_name")
            if owner and name:
                return str(owner), str(name)
        owner = item.get("owner") or item.get("expected_vertex") or item.get("expected_edge")
        name = item.get("name") or item.get("property") or item.get("property_name")
        semantic_id = item.get("semantic_id")
        if (owner is None or name is None) and isinstance(semantic_id, str) and "." in semantic_id:
            owner, name = semantic_id.split(".", 1)
        if owner and name:
            return str(owner), str(name)
    raise BindingValidationError(f"cannot extract property owner/name from {item!r}")


def _coerce_literal_result(item: Any) -> LiteralResolverResult:
    if isinstance(item, LiteralResolverResult):
        return item
    return LiteralResolverResult.model_validate(item)


def _resolved_literal_value(result: LiteralResolverResult) -> Any | None:
    if not result.resolved:
        return None
    if result.normalized_value is not None:
        return result.normalized_value
    return result.resolved_value


def _literal_from_filter(item: Mapping[str, Any]) -> LiteralBinding | None:
    literal_payload = item.get("literal") or item.get("literal_result")
    if literal_payload is None:
        return None
    result = _coerce_literal_result(literal_payload)
    owner = result.expected_vertex or result.expected_edge
    return LiteralBinding(
        raw_literal=result.raw_literal,
        resolved=result.resolved,
        value=_resolved_literal_value(result),
        normalized_value=result.normalized_value,
        match_type=result.match_type,
        confidence=result.confidence,
        owner=owner,
        property=result.expected_property,
        evidence=result.evidence,
        alternatives=result.alternatives,
        requires_user_choice=result.requires_user_choice,
        value_index_miss=result.value_index_miss,
        error_code=result.error_code,
    )


def _validate_filter_literal_match(item: Mapping[str, Any], literal: LiteralBinding) -> None:
    owner, property_name = _extract_owner_name(item)
    raw_literal = _extract_raw_literal(item, literal)
    if literal.owner != owner or literal.property != property_name:
        raise BindingValidationError(
            f"literal result {literal.owner}.{literal.property} does not match filter {owner}.{property_name}"
        )
    if raw_literal is not None and literal.raw_literal != raw_literal:
        raise BindingValidationError(
            f"literal result raw_literal {literal.raw_literal!r} does not match filter raw_literal {raw_literal!r}"
        )


def _extract_raw_literal(item: Mapping[str, Any], inline_literal: LiteralBinding | None) -> str | None:
    raw_literal = item.get("raw_literal") or item.get("literal_text")
    if raw_literal is not None:
        return str(raw_literal)
    if inline_literal is not None:
        return inline_literal.raw_literal
    return None


def _find_literal_binding(
    literal_bindings: list[LiteralBinding],
    owner: str,
    property_name: str,
    raw_literal: str | None,
) -> LiteralBinding | None:
    for literal in literal_bindings:
        if literal.owner == owner and literal.property == property_name:
            if raw_literal is None or literal.raw_literal == raw_literal:
                return literal
    return None


def _looks_like_property_reference(item: Mapping[str, Any]) -> bool:
    return any(key in item for key in ("owner", "property", "property_name")) or (
        isinstance(item.get("semantic_id"), str) and "." in item["semantic_id"]
    )


def _validate_source_reference(item: Mapping[str, Any], *, field_name: str) -> None:
    value = item.get("source")
    if not isinstance(value, str) or "." not in value or value.startswith(".") or value.endswith("."):
        raise BindingValidationError(f"{field_name} source must be a namespaced reference, got {value!r}")
    disallowed = {"name", "semantic_name", "semantic_id", "semantic_type", "owner", "property", "property_name"}
    extras = sorted(disallowed.intersection(item))
    if extras:
        raise BindingValidationError(f"{field_name} source reference must not include {extras}")


def _coerce_dict_list(value: Any, field_name: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list | tuple):
        raise BindingValidationError(f"{field_name} must be a list")
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise BindingValidationError(f"{field_name} item must be a mapping, got {item!r}")
        result.append(dict(item))
    return result


def _coerce_assumptions(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list | tuple):
        value = [value]
    assumptions: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, Mapping):
            assumptions.append(dict(item))
        else:
            assumptions.append({"type": "upstream_assumption", "message": str(item)})
    return assumptions


def _normalize_query_shape(value: Any) -> str:
    raw = "vertex_lookup" if value is None else str(value)
    normalized = _QUERY_SHAPE_ALIASES.get(raw)
    if normalized is None:
        raise BindingValidationError(f"unsupported query_shape {raw}")
    return normalized


def _normalize_operator(value: Any) -> str:
    raw = str(value)
    normalized = _OPERATOR_ALIASES.get(raw)
    if normalized is None:
        raise BindingValidationError(f"unsupported filter operator {raw}")
    return normalized


def _append_unique_named(bindings: list[Any], binding: Any) -> list[Any]:
    if any(existing.name == binding.name for existing in bindings):
        return bindings
    return [*bindings, binding]


def _append_unique_property(
    bindings: list[PropertyBinding],
    binding: PropertyBinding,
) -> list[PropertyBinding]:
    if any(existing.owner == binding.owner and existing.name == binding.name for existing in bindings):
        return bindings
    return [*bindings, binding]
