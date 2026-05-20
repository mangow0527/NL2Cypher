from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .assets import OntologyAssets
from .errors import ClarificationNeeded, EngineeringFailure, ResourceMissing
from .models import (
    OntologyLogicalPlan,
    PlanEdge,
    PlanFilter,
    PlanNode,
    PlanProjection,
    ShapeField,
)


@dataclass(frozen=True)
class ShapeFinalizationResult:
    logical_plan: OntologyLogicalPlan
    precheck_result: dict[str, Any]
    warnings: tuple[dict[str, Any], ...]
    trace: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "logical_plan": _logical_plan_output(self.logical_plan),
            "precheck_result": dict(self.precheck_result),
            "warnings": [dict(item) for item in self.warnings],
            "trace": dict(self.trace),
        }


class OntologyShapeFinalizer:
    def __init__(self, assets: OntologyAssets) -> None:
        self.assets = assets
        self.classes = _classes(assets)
        self.relations = _relations(assets)
        self.attributes = _attributes(assets)

    def finalize(
        self,
        *,
        intent_trace: Any,
        ontology_mapping: Any,
        ontology_path_selection: Any | None = None,
        path_filling: Any | None = None,
        coreference: Any | None = None,
        binding: Any | None = None,
        unresolved_items: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
        warnings: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    ) -> ShapeFinalizationResult:
        intent_trace_dict = _to_dict(intent_trace)
        mapping_dict = _to_dict(ontology_mapping)
        path_dict = _to_dict(ontology_path_selection if ontology_path_selection is not None else path_filling)
        coref_dict = _to_dict(coreference)
        binding_dict = _to_dict(binding)
        all_unresolved = self._collect_unresolved(
            unresolved_items,
            path_dict.get("unresolved_items", ()),
            coref_dict.get("unresolved_items", ()),
            binding_dict.get("unresolved_items", ()),
        )
        nonblocking_warnings = tuple(dict(item) for item in (*warnings, *all_unresolved) if not bool(item.get("blocking")))
        blocking_failures = [self._failure_from_unresolved(item) for item in all_unresolved if bool(item.get("blocking"))]
        if blocking_failures:
            self._raise_precheck_failure(blocking_failures, nonblocking_warnings)

        shape = self._final_shape(intent_trace, intent_trace_dict, path_dict, binding_dict)
        nodes = self._nodes(coref_dict, mapping_dict)
        node_by_id = {node.id: node for node in nodes}
        edges = self._edges(path_dict, mapping_dict, node_by_id)
        filters = self._filters(binding_dict, node_by_id)
        nodes = tuple(
            PlanNode(id=node.id, type=node.type, alias=node.alias, filters=tuple(filters.get(node.id, ()))) for node in nodes
        )
        projections = self._projections(binding_dict, node_by_id)
        plan = OntologyLogicalPlan(
            root_operation="SELECT",
            intent=intent_trace.intent if hasattr(intent_trace, "intent") else _intent_identity(intent_trace_dict),
            shape=shape,
            nodes=nodes,
            edges=edges,
            projections=projections,
            metrics=(),
        )
        failures = self._precheck(plan, mapping_dict)
        if failures:
            self._raise_precheck_failure(failures, nonblocking_warnings, plan=plan)
        precheck_result = {"passed": True, "failures": []}
        return ShapeFinalizationResult(
            logical_plan=plan,
            precheck_result=precheck_result,
            warnings=nonblocking_warnings,
            trace={
                "stage": "step_2_6",
                "shape_backfilled": {key: value.to_dict() for key, value in shape.items()},
                "warnings": [dict(item) for item in nonblocking_warnings],
                "precheck_result": precheck_result,
            },
        )

    def _collect_unresolved(self, *groups: Any) -> tuple[dict[str, Any], ...]:
        items: list[dict[str, Any]] = []
        for group in groups:
            if not isinstance(group, (list, tuple)):
                continue
            for item in group:
                if isinstance(item, dict):
                    items.append(_normalize_unresolved(item))
        return tuple(items)

    def _failure_from_unresolved(self, item: dict[str, Any]) -> dict[str, Any]:
        error_type = item.get("suggested_error_type")
        if error_type not in {"ClarificationNeeded", "ResourceMissing", "EngineeringFailure"}:
            error_type = "EngineeringFailure"
        failure = {
            "check": "blocking_unresolved_empty",
            "accepted": False,
            "error_type": error_type,
            "reason_code": item.get("reason_code") or str(item.get("type") or "UNCLASSIFIED").upper(),
            "message": item.get("message") or item.get("reason") or "blocking unresolved item",
            "source_unresolved_id": item.get("id"),
        }
        if error_type == "ClarificationNeeded":
            failure["clarification_options"] = _clarification_options(item.get("candidates") or item.get("options"))
        return failure

    def _final_shape(
        self,
        intent_trace: Any,
        intent_trace_dict: dict[str, Any],
        path_dict: dict[str, Any],
        binding_dict: dict[str, Any],
    ) -> dict[str, ShapeField]:
        shape = dict(getattr(intent_trace, "shape", {}) or {})
        if not shape:
            shape = {key: _shape_field(value) for key, value in intent_trace_dict.get("shape", {}).items()}
        for payload in (path_dict.get("shape_updates", {}), binding_dict.get("shape_updates", {})):
            if not isinstance(payload, dict):
                continue
            for key, value in payload.items():
                shape[str(key)] = _shape_field(value)
        for key, value in _default_confirmed_shape_fields().items():
            shape.setdefault(key, value)
        if "hop_count" in shape and "relation_resolution_expected" in shape:
            current = shape["relation_resolution_expected"]
            if current.decision == "pending":
                shape["relation_resolution_expected"] = ShapeField(
                    value=current.value,
                    source="shape_finalization",
                    decision="accept",
                    confidence=current.confidence,
                    derived_from=current.derived_from,
                )
        return shape

    def _nodes(self, coref_dict: dict[str, Any], mapping_dict: dict[str, Any]) -> tuple[PlanNode, ...]:
        nodes: list[PlanNode] = []
        used_ids: set[str] = set()
        merged_nodes = coref_dict.get("merged_nodes")
        if isinstance(merged_nodes, dict):
            merged_nodes = merged_nodes.get("nodes")
        if isinstance(merged_nodes, (list, tuple)):
            for item in merged_nodes:
                if not isinstance(item, dict):
                    continue
                class_id = str(item.get("class_id") or item.get("class") or item.get("type") or item.get("ontology_id") or "")
                node_id = str(item.get("node_id") or item.get("id") or "")
                if not class_id or not node_id or node_id in used_ids:
                    continue
                nodes.append(PlanNode(id=node_id, type=class_id, alias=_alias(class_id, len(nodes) + 1)))
                used_ids.add(node_id)
        for item in mapping_dict.get("mapped_mentions", []):
            if not isinstance(item, dict):
                continue
            class_id = _class_for_mapping(item)
            if class_id is None or any(node.type == class_id for node in nodes):
                continue
            node_id = _node_id(class_id, len(nodes) + 1)
            nodes.append(PlanNode(id=node_id, type=class_id, alias=_alias(class_id, len(nodes) + 1)))
        return tuple(nodes)

    def _edges(
        self,
        path_dict: dict[str, Any],
        mapping_dict: dict[str, Any],
        node_by_id: dict[str, PlanNode],
    ) -> tuple[PlanEdge, ...]:
        nodes_by_class = {node.type: node for node in node_by_id.values()}
        class_by_mapping = {
            str(item.get("mapping_id")): _class_for_mapping(item)
            for item in mapping_dict.get("mapped_mentions", [])
            if isinstance(item, dict) and item.get("mapping_id")
        }
        edges: list[PlanEdge] = []
        selected_paths = path_dict.get("selected_paths", [])
        if not isinstance(selected_paths, (list, tuple)):
            return ()
        for selected in selected_paths:
            if not isinstance(selected, dict):
                continue
            chain = selected.get("relation_chain")
            if not isinstance(chain, (list, tuple)):
                continue
            current_class = _selected_path_start_class(selected, class_by_mapping)
            for raw_relation_id in chain:
                relation_id = _normalize_relation_id(str(raw_relation_id))
                relation = self.relations.get(relation_id)
                if not isinstance(relation, dict):
                    continue
                from_class = str(relation.get("domain") or relation.get("domain_class") or "")
                to_class = str(relation.get("range") or relation.get("range_class") or "")
                if current_class and current_class != from_class:
                    from_class = current_class
                from_node = nodes_by_class.get(from_class)
                to_node = nodes_by_class.get(to_class)
                if from_node and to_node:
                    edge = PlanEdge(
                        from_node=from_node.id,
                        to_node=to_node.id,
                        relation=relation_id,
                        edge_type=relation_id.removeprefix("REL_"),
                    )
                    if edge not in edges:
                        edges.append(edge)
                current_class = to_class
        return tuple(edges)

    def _filters(
        self,
        binding_dict: dict[str, Any],
        node_by_id: dict[str, PlanNode],
    ) -> dict[str, list[PlanFilter]]:
        filters: dict[str, list[PlanFilter]] = {}
        for item in binding_dict.get("filters", []):
            if not isinstance(item, dict) or item.get("decision", "accept") != "accept":
                continue
            result = item.get("result")
            if not isinstance(result, dict):
                continue
            node_id = str(result.get("node") or "")
            attribute = str(result.get("attribute") or "")
            node = node_by_id.get(node_id)
            if node is None or "." not in attribute:
                continue
            owner, attr = attribute.split(".", 1)
            if owner != node.type:
                continue
            filters.setdefault(node_id, []).append(
                PlanFilter(
                    node=node_id,
                    attr=attr,
                    operator=_operator(str(result.get("operator") or "=")),
                    value=result.get("value"),
                )
            )
        return filters

    def _projections(
        self,
        binding_dict: dict[str, Any],
        node_by_id: dict[str, PlanNode],
    ) -> tuple[PlanProjection, ...]:
        projections: list[PlanProjection] = []
        for item in binding_dict.get("projections", []):
            if not isinstance(item, dict) or item.get("decision", "accept") != "accept":
                continue
            result = item.get("result")
            if not isinstance(result, dict):
                continue
            node_id = str(result.get("node") or "")
            attribute = str(result.get("attribute") or "")
            node = node_by_id.get(node_id)
            if node is None or "." not in attribute:
                continue
            owner, attr = attribute.split(".", 1)
            if owner != node.type:
                continue
            projections.append(
                PlanProjection(node=node_id, attribute=attr, alias=str(result.get("alias") or f"{node.alias}_{attr}"))
            )
        return tuple(projections)

    def _precheck(self, plan: OntologyLogicalPlan, mapping_dict: dict[str, Any]) -> list[dict[str, Any]]:
        failures: list[dict[str, Any]] = []
        physical_failure = _physical_term_failure(plan)
        if physical_failure is not None:
            return [physical_failure]
        node_by_id = {node.id: node for node in plan.nodes}
        for node in plan.nodes:
            if node.type not in self.classes:
                failures.append(_failure("node_type_exists", "EngineeringFailure", "UNKNOWN_ONTOLOGY_CLASS", f"unknown class {node.type}"))
        for edge in plan.edges:
            relation = self.relations.get(edge.relation)
            if relation is None:
                failures.append(_failure("relation_exists", "EngineeringFailure", "UNKNOWN_ONTOLOGY_RELATION", f"unknown relation {edge.relation}"))
                continue
            from_node = node_by_id.get(edge.from_node)
            to_node = node_by_id.get(edge.to_node)
            expected = [relation.get("domain"), relation.get("range")]
            actual = [from_node.type if from_node else None, to_node.type if to_node else None]
            if actual != expected:
                failures.append(
                    _failure(
                        "relation_domain_range",
                        "EngineeringFailure",
                        "ILLEGAL_RELATION_ENDPOINT",
                        f"relation {edge.relation} endpoints do not match domain/range",
                        expected=expected,
                        actual=actual,
                    )
                )
        for node in plan.nodes:
            for item in node.filters:
                attribute_id = f"{node.type}.{item.attr}"
                if attribute_id not in self.attributes:
                    failures.append(_failure("attribute_owner_exists", "EngineeringFailure", "UNKNOWN_ONTOLOGY_ATTRIBUTE", f"unknown attribute {attribute_id}"))
        for projection in plan.projections:
            node = node_by_id.get(projection.node)
            attribute_id = f"{node.type}.{projection.attribute}" if node else f"UNKNOWN.{projection.attribute}"
            if node is None or attribute_id not in self.attributes:
                failures.append(_failure("attribute_owner_exists", "EngineeringFailure", "UNKNOWN_ONTOLOGY_ATTRIBUTE", f"unknown attribute {attribute_id}"))
        projection_expected = bool(_shape_value(plan.shape, "projection_expected"))
        if projection_expected and not plan.projections and not plan.metrics:
            failures.append(
                _failure(
                    "shape_projection_consistency",
                    "EngineeringFailure",
                    "PROJECTION_EXPECTED_BUT_EMPTY",
                    "projection_expected is true but plan has no projections",
                )
            )
        if not projection_expected and plan.projections:
            failures.append(
                _failure(
                    "shape_projection_consistency",
                    "EngineeringFailure",
                    "PROJECTION_UNEXPECTED",
                    "projection_expected is false but plan has projections",
                )
            )
        pending = [key for key, value in plan.shape.items() if value.decision == "pending" or value.pending_until]
        if pending:
            failures.append(
                _failure("shape_no_pending", "EngineeringFailure", "PENDING_SHAPE_FIELD", f"pending shape fields: {', '.join(pending)}")
            )
        connected_node_ids = {edge.from_node for edge in plan.edges} | {edge.to_node for edge in plan.edges}
        if plan.edges:
            for node in plan.nodes:
                if node.id in connected_node_ids:
                    continue
                source = _mapping_source_for_node(node, mapping_dict)
                error_type = "ClarificationNeeded" if source == "explicit_user_mention" else "EngineeringFailure"
                failures.append(
                    _failure(
                        "no_orphan_nodes",
                        error_type,
                        "ORPHAN_ONTOLOGY_NODE",
                        f"node {node.id} ({node.type}) is not connected by selected paths",
                    )
                )
        return failures

    def _raise_precheck_failure(
        self,
        failures: list[dict[str, Any]],
        warnings: tuple[dict[str, Any], ...],
        *,
        plan: OntologyLogicalPlan | None = None,
    ) -> None:
        precheck_result = {"passed": False, "failures": failures}
        payload = {
            "precheck_result": precheck_result,
            "warnings": [dict(item) for item in warnings],
        }
        if plan is not None:
            payload["logical_plan_draft"] = plan.to_dict()
        first = failures[0]
        message = str(first.get("message") or "shape finalization precheck failed")
        error_type = first.get("error_type")
        if error_type == "ClarificationNeeded":
            raise ClarificationNeeded(stage="step_2_6", message=message, clarification=payload)
        if error_type == "ResourceMissing":
            raise ResourceMissing(stage="step_2_6", message=message, payload=payload)
        raise EngineeringFailure(stage="step_2_6", message=message, payload=payload)


def _to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        return payload if isinstance(payload, dict) else {}
    return {}


def _normalize_unresolved(item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    reason_code = str(normalized.get("reason_code") or normalized.get("type") or "")
    if normalized.get("suggested_error_type") is not None:
        normalized["suggested_error_type"] = str(normalized["suggested_error_type"])
    if "type" not in normalized and reason_code:
        normalized["type"] = reason_code.lower()
    if "blocking" not in normalized:
        normalized["blocking"] = True
    return normalized


def _shape_field(value: Any) -> ShapeField:
    if isinstance(value, ShapeField):
        return value
    if isinstance(value, dict):
        return ShapeField(
            value=value.get("value"),
            source=str(value.get("source") or "unknown"),
            decision=str(value.get("decision") or "accept"),
            confidence=float(value.get("confidence", 1.0)),
            derived_from=tuple(str(item) for item in value.get("derived_from", ()) if item is not None)
            if isinstance(value.get("derived_from"), (list, tuple))
            else (),
            pending_until=str(value["pending_until"]) if value.get("pending_until") is not None else None,
        )
    return ShapeField(value=value, source="shape_finalization.compat", decision="accept", confidence=1.0)


def _default_confirmed_shape_fields() -> dict[str, ShapeField]:
    return {
        "aggregation_functions": ShapeField([], "shape_finalization.default", "accept", 1.0),
        "group_by_required": ShapeField(False, "shape_finalization.default", "accept", 1.0),
        "order_required": ShapeField(False, "shape_finalization.default", "accept", 1.0),
        "limit_required": ShapeField(False, "shape_finalization.default", "accept", 1.0),
        "time_grain_required": ShapeField(False, "shape_finalization.default", "accept", 1.0),
    }


def _classes(assets: OntologyAssets) -> set[str]:
    payload = assets.domain_ontology.get("classes", [])
    result = {str(item.get("id")) for item in payload if isinstance(item, dict) and item.get("id")}
    for entry in assets.entries:
        if entry.mention_type == "business_object":
            result.add(entry.canonical_id)
    return result


def _relations(assets: OntologyAssets) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    payload = assets.domain_ontology.get("relations", [])
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict):
            continue
        relation_id = _normalize_relation_id(str(item.get("id") or item.get("relation") or ""))
        if relation_id:
            result[relation_id] = dict(item, id=relation_id)
    for entry in assets.entries:
        if entry.mention_type != "relation_predicate":
            continue
        relation_id = _normalize_relation_id(entry.canonical_id)
        result.setdefault(
            relation_id,
            {
                "id": relation_id,
                "domain": entry.metadata.get("domain"),
                "range": entry.metadata.get("range"),
                "role": entry.metadata.get("role"),
            },
        )
    return result


def _attributes(assets: OntologyAssets) -> set[str]:
    result = set()
    payload = assets.domain_ontology.get("attributes", [])
    if isinstance(payload, list):
        result.update(str(item.get("id")) for item in payload if isinstance(item, dict) and item.get("id"))
    elif isinstance(payload, dict):
        result.update(str(key) for key in payload)
    for entry in assets.entries:
        if entry.mention_type == "attribute":
            result.add(entry.canonical_id)
    return result


def _class_for_mapping(item: dict[str, Any]) -> str | None:
    kind = str(item.get("ontology_kind") or "")
    if kind == "class" and item.get("ontology_id"):
        return str(item["ontology_id"])
    if kind == "relation" and item.get("domain_class"):
        return str(item["domain_class"])
    if kind == "relation_role" and item.get("target_class"):
        return str(item["target_class"])
    if kind == "attribute" and item.get("parent_class"):
        return str(item["parent_class"])
    if kind == "enum_value":
        attribute = item.get("constrains_attribute") or item.get("constrains_field")
        if isinstance(attribute, str) and "." in attribute:
            return attribute.split(".", 1)[0]
    return None


def _node_id(class_id: str, index: int) -> str:
    return {"Service": "s1", "Tunnel": "t1", "NetworkElement": "n1", "Port": "p1", "Protocol": "proto1"}.get(
        class_id,
        f"n{index}",
    )


def _alias(class_id: str, index: int) -> str:
    return {"Service": "s", "Tunnel": "t", "NetworkElement": "ne", "Port": "p", "Protocol": "proto"}.get(
        class_id,
        f"n{index}",
    )


def _normalize_relation_id(relation_id: str) -> str:
    if not relation_id:
        return ""
    return relation_id if relation_id.startswith("REL_") else f"REL_{relation_id}"


def _selected_path_start_class(selected: dict[str, Any], class_by_mapping: dict[str, str | None]) -> str | None:
    mapping_ids = selected.get("mapping_ids")
    if isinstance(mapping_ids, (list, tuple)):
        for mapping_id in mapping_ids:
            class_id = class_by_mapping.get(str(mapping_id))
            if class_id is not None:
                return class_id
    return None


def _operator(value: str) -> str:
    return {"equals": "=", "eq": "=", "==": "="}.get(value, value)


def _intent_identity(payload: dict[str, Any]) -> Any:
    from .models import IntentIdentity

    intent = payload.get("intent", payload)
    if not isinstance(intent, dict):
        intent = {}
    return IntentIdentity(
        primary=str(intent.get("primary") or "record_retrieval_query"),
        secondary=str(intent.get("secondary") or "related_record_query"),
        source=str(intent.get("source") or "shape_finalization.compat"),
        decision=str(intent.get("decision") or "accept"),
        confidence=float(intent.get("confidence", 1.0)),
    )


def _shape_value(shape: dict[str, ShapeField], key: str) -> Any:
    field = shape.get(key)
    return field.value if field is not None else None


def _mapping_source_for_node(node: PlanNode, mapping_dict: dict[str, Any]) -> str | None:
    for item in mapping_dict.get("mapped_mentions", []):
        if isinstance(item, dict) and _class_for_mapping(item) == node.type and item.get("mention_type") in {"OBJECT", "RELATION"}:
            return "explicit_user_mention"
    return None


def _failure(check: str, error_type: str, reason_code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {
        "check": check,
        "accepted": False,
        "error_type": error_type,
        "reason_code": reason_code,
        "message": message,
        **extra,
    }


def _physical_term_failure(plan: OntologyLogicalPlan) -> dict[str, Any] | None:
    forbidden_terms = ("node_label", "edge_type", "node_property", "property:", "label:", "cypher", "match ")
    values: list[str] = [plan.root_operation]
    values.extend(node.type for node in plan.nodes)
    values.extend(edge.relation for edge in plan.edges)
    values.extend(projection.attribute for projection in plan.projections)
    for value in values:
        lower = str(value).lower()
        if any(term in lower for term in forbidden_terms) or ":" in str(value):
            return _failure(
                "logical_plan_ontology_only",
                "EngineeringFailure",
                "PHYSICAL_SCHEMA_TERM_IN_LOGICAL_PLAN",
                f"logical plan contains physical schema/Cypher term: {value}",
            )
    return None


def _clarification_options(value: Any) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    if not isinstance(value, (list, tuple)):
        return options
    for index, item in enumerate(value, start=1):
        if isinstance(item, dict):
            option_id = str(item.get("candidate_id") or item.get("option_id") or f"O{index}")
            label = str(item.get("label") or item.get("message") or item.get("path") or option_id)
        else:
            option_id = f"O{index}"
            label = str(item)
        options.append({"option_id": option_id, "label": label})
    return options


def _logical_plan_output(plan: OntologyLogicalPlan) -> dict[str, Any]:
    payload = plan.to_dict()
    payload["relationships"] = [
        {"from": edge.from_node, "to": edge.to_node, "relation": edge.relation} for edge in plan.edges
    ]
    payload.pop("edges", None)
    return payload
