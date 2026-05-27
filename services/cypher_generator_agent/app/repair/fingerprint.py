from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


IGNORED_KEYS = frozenset(
    {
        "confidence",
        "score",
        "reason",
        "rationale",
        "raw_llm_output",
        "duration_ms",
        "token_usage",
        "stage_id",
        "candidate",
        "candidates",
        "evidence",
        "metadata",
        "message",
    }
)


def from_binding_plan(plan: Mapping[str, Any] | object) -> str:
    payload = _dump_mapping(plan)
    canonical = {
        "query_shape": payload.get("query_shape"),
        "vertices": [
            {"role": item.get("role") or f"vertex_{index}", "name": item.get("name")}
            for index, item in enumerate(_as_list(payload.get("vertex_bindings")))
            if isinstance(item, Mapping)
        ],
        "edges": [
            {
                "role": item.get("role") or f"edge_{index}",
                "name": item.get("name"),
                "direction": item.get("direction", "forward"),
            }
            for index, item in enumerate(_as_list(payload.get("edge_bindings")))
            if isinstance(item, Mapping)
        ],
        "properties": [
            {
                "owner": item.get("owner"),
                "name": item.get("name"),
                "role": item.get("role"),
            }
            for item in _as_list(payload.get("property_bindings"))
            if isinstance(item, Mapping)
        ],
        "filters": [
            {
                "target": item.get("target") or item.get("owner"),
                "property": item.get("property"),
                "operator": item.get("operator"),
                "value": _literal_value(item),
            }
            for item in _as_list(payload.get("filters"))
            if isinstance(item, Mapping)
        ],
        "literals": [
            _binding_literal_payload(index, item)
            for index, item in enumerate(_as_list(payload.get("literal_bindings")))
            if isinstance(item, Mapping)
        ],
        "path_patterns": [
            {"name": item.get("name")}
            for item in _as_list(payload.get("path_pattern_bindings"))
            if isinstance(item, Mapping)
        ],
        "projections": _with_positions(_as_list(payload.get("projection"))),
        "groups": _with_positions(_as_list(payload.get("group_by"))),
        "metrics": [
            {"name": item.get("name")}
            for item in _as_list(payload.get("metric_bindings"))
            if isinstance(item, Mapping)
        ],
        "measures": _with_positions(_as_list(payload.get("measures"))),
        "sorts": _with_positions(_as_list(payload.get("sort"))),
        "limits": [{"value": payload.get("limit")}] if payload.get("limit") is not None else [],
        "subqueries": payload.get("subqueries", []),
    }
    return canonicalize_state(canonical)


def from_dsl(dsl: Mapping[str, Any] | object) -> str:
    payload = _dump_mapping(dsl)
    canonical = _dsl_payload(payload)
    return canonicalize_state(canonical)


def canonicalize_state(payload: Mapping[str, Any] | object) -> str:
    canonical = _canonicalize(_dump_mapping(payload))
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def canonical_payload(payload: Mapping[str, Any] | object) -> dict[str, Any]:
    return _canonicalize(_dump_mapping(payload))


def _dsl_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    bindings = payload.get("bindings", {})
    operations = _as_list(payload.get("operations"))
    local_operations = [
        op
        for op in operations
        if isinstance(op, Mapping) and op.get("op") != "subquery"
    ]
    return {
        "query_shape": payload.get("query_shape"),
        "vertices": _dsl_vertices(bindings),
        "edges": _dsl_edges(bindings, local_operations),
        "properties": _dsl_properties(payload, local_operations),
        "filters": _dsl_filters(payload, local_operations),
        "path_patterns": [
            {
                "name": op.get("path_pattern_name") or op.get("pattern_id"),
                "bind_as": op.get("bind_as"),
                "parameters": op.get("parameters"),
            }
            for op in local_operations
            if isinstance(op, Mapping) and op.get("op") == "use_path_pattern"
        ],
        "projections": _with_positions(_projection_items(payload)),
        "groups": _with_positions(_as_list(payload.get("group_by")) + _collect_operation_values(local_operations, "group_by")),
        "metrics": [
            {"name": op.get("metric_name")}
            for op in local_operations
            if isinstance(op, Mapping) and op.get("op") == "metric_aggregate"
        ],
        "measures": _with_positions(_as_list(payload.get("measures")) + _collect_operation_values(local_operations, "measures")),
        "sorts": _with_positions(_as_list(payload.get("order_by")) + _collect_operation_values(local_operations, "by")),
        "limits": _dsl_limits(payload, local_operations),
        "subqueries": [
            {
                "bind_as": op.get("bind_as"),
                "fingerprint_payload": _dsl_payload(op),
            }
            for op in operations
            if isinstance(op, Mapping) and op.get("op") == "subquery"
        ],
    }


def _dsl_vertices(bindings: Any) -> list[dict[str, Any]]:
    if not isinstance(bindings, Mapping):
        return []
    return [
        {"role": role, "name": binding.get("vertex_name")}
        for role, binding in bindings.items()
        if isinstance(binding, Mapping) and binding.get("vertex_name")
    ]


def _dsl_edges(bindings: Any, operations: list[Any]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    if isinstance(bindings, Mapping):
        edges.extend(
            {"role": role, "name": binding.get("edge_name")}
            for role, binding in bindings.items()
            if isinstance(binding, Mapping) and binding.get("edge_name")
        )
    edges.extend(
        {
            "position": index,
            "role": op.get("edge"),
            "name": op.get("edge"),
            "from": op.get("from") or op.get("from_ref"),
            "to": op.get("to"),
            "direction": op.get("direction"),
        }
        for index, op in enumerate(operations)
        if isinstance(op, Mapping) and op.get("op") == "traverse_edge"
    )
    edges.extend(
        {
            "position": index,
            "role": "variable_path",
            "name": "variable_path",
            "bind_as": op.get("bind_as"),
            "start": op.get("start"),
            "through_vertex": op.get("through", {}).get("vertex_ref")
            if isinstance(op.get("through"), Mapping)
            else None,
            "allowed_edges": _as_list(op.get("allowed_edges")),
            "min_hops": op.get("min_hops"),
            "max_hops": op.get("max_hops"),
        }
        for index, op in enumerate(operations)
        if isinstance(op, Mapping) and op.get("op") == "variable_path"
    )
    return edges


def _dsl_properties(payload: Mapping[str, Any], operations: list[Any]) -> list[Any]:
    values: list[Any] = []
    values.extend(_properties_from_filters(payload.get("filters", [])))
    projection = payload.get("projection", {})
    if isinstance(projection, Mapping):
        values.extend(_properties_from_items(projection.get("items", [])))
    values.extend(_properties_from_items(_collect_operation_values(operations, "group_by")))
    values.extend(_properties_from_items(_collect_operation_values(operations, "measures")))
    for op in operations:
        if isinstance(op, Mapping) and op.get("op") == "filter_subquery":
            values.append({"source": op.get("source"), "predicate": op.get("predicate")})
    return values


def _dsl_filters(payload: Mapping[str, Any], operations: list[Any]) -> list[Any]:
    values = list(_as_list(payload.get("filters")))
    values.extend(_collect_operation_values(operations, "filters"))
    values.extend(
        {
            "source_op": "variable_path",
            "through_role": op.get("through", {}).get("role"),
            "through_vertex": op.get("through", {}).get("vertex_ref"),
            "filter": item,
        }
        for op in operations
        if isinstance(op, Mapping)
        and op.get("op") == "variable_path"
        and isinstance(op.get("through"), Mapping)
        for item in _as_list(op.get("through", {}).get("filters"))
    )
    values.extend(
        {"source": op.get("source"), "predicate": op.get("predicate")}
        for op in operations
        if isinstance(op, Mapping) and op.get("op") == "filter_subquery"
    )
    return values


def _dsl_limits(payload: Mapping[str, Any], operations: list[Any]) -> list[dict[str, Any]]:
    limits = [{"value": payload.get("limit")}] if payload.get("limit") is not None else []
    limits.extend(
        {"value": op.get("value")}
        for op in operations
        if isinstance(op, Mapping) and op.get("op") == "limit"
    )
    return limits


def _projection_items(payload: Mapping[str, Any]) -> list[Any]:
    projection = payload.get("projection", {})
    if isinstance(projection, Mapping):
        return _as_list(projection.get("items"))
    return _as_list(projection)


def _with_positions(items: list[Any]) -> list[Any]:
    positioned: list[Any] = []
    for index, item in enumerate(items):
        if isinstance(item, Mapping):
            positioned.append({"position": index, **dict(item)})
        else:
            positioned.append({"position": index, "value": item})
    return positioned


def _binding_literal_payload(index: int, item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "position": index,
        "raw_literal": item.get("raw_literal"),
        "owner": item.get("owner"),
        "property": item.get("property"),
        "resolved": item.get("resolved"),
        "value": item.get("normalized_value") if item.get("normalized_value") is not None else item.get("value"),
        "match_type": item.get("match_type"),
        "requires_user_choice": item.get("requires_user_choice"),
        "value_index_miss": item.get("value_index_miss"),
        "error_code": item.get("error_code"),
        "alternatives": [
            {
                "value": alternative.get("value"),
                "display": alternative.get("display"),
                "source": alternative.get("source"),
            }
            for alternative in _as_list(item.get("alternatives"))
            if isinstance(alternative, Mapping)
        ],
    }


def _collect_operation_values(operations: list[Any], key: str) -> list[Any]:
    values: list[Any] = []
    for op in operations:
        if not isinstance(op, Mapping):
            continue
        values.extend(_as_list(op.get(key)))
    return values


def _properties_from_filters(filters: Any) -> list[Any]:
    return [
        {"target": item.get("target"), "property": item.get("property")}
        for item in _as_list(filters)
        if isinstance(item, Mapping) and item.get("property")
    ]


def _properties_from_items(items: Any) -> list[Any]:
    return [
        item.get("property")
        for item in _as_list(items)
        if isinstance(item, Mapping) and item.get("property")
    ]


def _literal_value(item: Mapping[str, Any]) -> Any:
    literal = item.get("literal")
    if isinstance(literal, Mapping):
        return literal.get("normalized_value") or literal.get("value")
    return item.get("value")


def _canonicalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key in sorted(value):
            if key in IGNORED_KEYS:
                continue
            canonical = _canonicalize(value[key])
            if canonical in (None, {}, []):
                continue
            result[str(key)] = canonical
        return result
    if isinstance(value, list | tuple):
        canonical_items = [_canonicalize(item) for item in value]
        canonical_items = [item for item in canonical_items if item not in (None, {}, [])]
        return sorted(canonical_items, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
    return value


def _dump_mapping(value: Mapping[str, Any] | object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump(mode="json", by_alias=True)
        except TypeError:
            dumped = model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dumped
    raise TypeError(f"cannot canonicalize non-mapping state: {value!r}")


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]
