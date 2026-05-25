from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .assets import OntologyAssets
from services.cypher_generator_agent.app.clarification_layer.errors import ClarificationNeeded
from services.cypher_generator_agent.app.infrastructure.errors import EngineeringFailure, ResourceMissing
from services.cypher_generator_agent.app.intent_layer.models import Intent, InitialShapeField
from .models import (
    OntologyLogicalPlan,
    PlanEdge,
    PlanFilter,
    PlanMetric,
    PlanNode,
    PlanNodeReturn,
    PlanProjection,
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
        intent_output: Any,
        ontology_mapping: Any,
        ontology_path_selection: Any | None = None,
        coreference: Any | None = None,
        binding: Any | None = None,
        unresolved_items: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
        warnings: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    ) -> ShapeFinalizationResult:
        intent_trace_dict = _to_dict(intent_output)
        mapping_dict = _to_dict(ontology_mapping)
        path_dict = _to_dict(ontology_path_selection)
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

        shape = self._final_shape(intent_output, intent_trace_dict, path_dict, binding_dict)
        nodes = self._nodes(coref_dict, mapping_dict, path_dict)
        node_by_id = {node.id: node for node in nodes}
        edges = self._edges(path_dict, mapping_dict, node_by_id)
        filters = self._filters(binding_dict, node_by_id)
        nodes = tuple(
            PlanNode(id=node.id, type=node.type, alias=node.alias, filters=tuple(filters.get(node.id, ()))) for node in nodes
        )
        projections = _normalize_projection_aliases(self._projections(binding_dict, node_by_id), nodes, edges)
        metrics = self._metrics(intent_output, nodes, binding_dict, shape, mapping_dict, projections)
        projections = _projections_after_metric(intent_output, shape, projections, metrics)
        node_returns = self._node_returns(intent_output, shape, nodes, projections, metrics, mapping_dict)
        nodes = _prune_unreferenced_nodes(nodes, edges, projections, metrics, node_returns, mapping_dict)
        plan = OntologyLogicalPlan(
            root_operation="SELECT",
            intent=intent_output.intent if hasattr(intent_output, "intent") else _intent_identity(intent_trace_dict),
            shape=shape,
            nodes=nodes,
            edges=edges,
            projections=projections,
            node_returns=node_returns,
            metrics=metrics,
        )
        plan, reconciliation_warnings = self._reconcile_projection_contract(plan)
        nonblocking_warnings = (*nonblocking_warnings, *reconciliation_warnings)
        failures = self._precheck(plan, mapping_dict)
        if failures:
            self._raise_precheck_failure(failures, nonblocking_warnings, plan=plan)
        precheck_result = {"passed": True, "failures": []}
        return ShapeFinalizationResult(
            logical_plan=plan,
            precheck_result=precheck_result,
            warnings=nonblocking_warnings,
            trace={
                "stage": "step_3_6",
                "shape_backfilled": {key: value.to_dict() for key, value in plan.shape.items()},
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
        source_step = item.get("source_step") or item.get("source_stage")
        failure = {
            "check": "blocking_unresolved_empty",
            "accepted": False,
            "error_type": error_type,
            "reason_code": item.get("reason_code") or str(item.get("type") or "UNCLASSIFIED").upper(),
            "message": item.get("message") or item.get("reason") or "blocking unresolved item",
            "source_unresolved_id": item.get("id"),
        }
        if source_step:
            failure["source_step"] = str(source_step)
        if error_type == "ClarificationNeeded":
            options = _clarification_options(item.get("candidates") or item.get("options"))
            failure["clarification_options"] = options
            if not options and item.get("no_option_reason"):
                failure["no_option_reason"] = str(item["no_option_reason"])
        return failure

    def _final_shape(
        self,
        intent_output: Any,
        intent_trace_dict: dict[str, Any],
        path_dict: dict[str, Any],
        binding_dict: dict[str, Any],
    ) -> dict[str, InitialShapeField]:
        shape = dict(getattr(intent_output, "initial_shape", {}) or {})
        if not shape:
            shape = {key: _shape_field(value) for key, value in intent_trace_dict.get("initial_shape", {}).items()}
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
                shape["relation_resolution_expected"] = InitialShapeField(
                    value=current.value,
                    source="shape_finalization",
                    decision="accept",
                    confidence=current.confidence,
                    derived_from=current.derived_from,
                )
        return shape

    def _nodes(self, coref_dict: dict[str, Any], mapping_dict: dict[str, Any], path_dict: dict[str, Any]) -> tuple[PlanNode, ...]:
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
        for item in (*_mapping_node_sources(mapping_dict), *_path_node_sources(path_dict, self.relations)):
            if not isinstance(item, dict):
                continue
            class_id = item.get("class_id")
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
            current_class = None
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

    def _node_returns(
        self,
        intent_output: Any,
        shape: dict[str, InitialShapeField],
        nodes: tuple[PlanNode, ...],
        projections: tuple[PlanProjection, ...],
        metrics: tuple[PlanMetric, ...],
        mapping_dict: dict[str, Any],
    ) -> tuple[PlanNodeReturn, ...]:
        intent = getattr(intent_output, "intent", None)
        secondary = getattr(intent, "secondary", None)
        return_subject_classes = _return_subject_classes(mapping_dict)
        projection_subject_classes = _projection_subject_classes(mapping_dict)
        projection_expected = bool(_shape_value(shape, "projection_expected"))
        if metrics:
            return ()

        def selected_node_returns(classes: tuple[str, ...] = ()) -> tuple[PlanNodeReturn, ...]:
            return tuple(
                PlanNodeReturn(node=node.id, alias=node.alias)
                for node in nodes
                if not classes or node.type in classes
            )

        if return_subject_classes:
            return selected_node_returns(return_subject_classes)
        if projection_expected and projection_subject_classes and not projections:
            return selected_node_returns(projection_subject_classes)
        if secondary == "entity_detail_query":
            return selected_node_returns()
        if secondary == "entity_list_query" and not projections:
            return selected_node_returns()
        return ()

    def _reconcile_projection_contract(
        self,
        plan: OntologyLogicalPlan,
    ) -> tuple[OntologyLogicalPlan, tuple[dict[str, Any], ...]]:
        projection_expected = bool(_shape_value(plan.shape, "projection_expected"))
        warnings: list[dict[str, Any]] = []
        shape = plan.shape
        node_returns = plan.node_returns

        if not projection_expected and plan.projections:
            previous = plan.shape.get("projection_expected")
            shape = dict(plan.shape)
            shape["projection_expected"] = InitialShapeField(
                True,
                "shape_finalization.reconciled",
                "accept",
                max(float(getattr(previous, "confidence", 0.0) or 0.0), 0.9),
                derived_from=tuple(
                    dict.fromkeys(
                        (
                            *(getattr(previous, "derived_from", ()) or ()),
                            "binding.projections",
                            getattr(previous, "source", "unknown"),
                        )
                    )
                ),
            )
            warnings.append(
                {
                    "source_step": "step_3_6",
                    "check": "shape_projection_consistency",
                    "reason_code": "PROJECTION_EXPECTATION_RECONCILED",
                    "message": "projection_expected was false but explicit bound projections were present; using projections as the stronger signal",
                }
            )

        if projection_expected and not plan.projections and not plan.metrics and not node_returns and len(plan.nodes) == 1 and not plan.edges:
            node = plan.nodes[0]
            node_returns = (PlanNodeReturn(node=node.id, alias=node.alias),)
            warnings.append(
                {
                    "source_step": "step_3_6",
                    "check": "shape_projection_consistency",
                    "reason_code": "PROJECTION_TARGET_DEFAULTED_TO_ENTITY",
                    "message": "projection_expected was true but no bound fields were present for a single-object query; returning the entity",
                }
            )

        if shape is plan.shape and node_returns is plan.node_returns:
            return plan, ()
        return (
            OntologyLogicalPlan(
                root_operation=plan.root_operation,
                intent=plan.intent,
                shape=shape,
                nodes=plan.nodes,
                edges=plan.edges,
                projections=plan.projections,
                node_returns=node_returns,
                metrics=plan.metrics,
            ),
            tuple(warnings),
        )

    def _metrics(
        self,
        intent_output: Any,
        nodes: tuple[PlanNode, ...],
        binding_dict: dict[str, Any],
        shape: dict[str, InitialShapeField],
        mapping_dict: dict[str, Any],
        projections: tuple[PlanProjection, ...],
    ) -> tuple[PlanMetric, ...]:
        intent = getattr(intent_output, "intent", None)
        primary = str(getattr(intent, "primary", ""))
        secondary = str(getattr(intent, "secondary", ""))
        if primary == "breakdown_query" and secondary == "multi_metric_breakdown_query":
            target = _node_by_type(nodes, "Tunnel") or _metric_target_node(nodes)
            metrics = [PlanMetric(function="count", node=target.id, alias=f"{_metric_alias_prefix(target.type)}_count")]
            node_by_id = {node.id: node for node in nodes}
            for index, condition in enumerate(_metric_conditions(binding_dict), start=1):
                metrics.append(
                    PlanMetric(
                        function="conditional_count",
                        node=target.id,
                        alias=_conditional_metric_alias(target, condition, node_by_id, index),
                        condition=(condition,),
                    )
                )
            return tuple(metrics)
        aggregation_functions = tuple(str(item) for item in (_shape_value(shape, "aggregation_functions") or ()))
        count_required = bool(_shape_value(shape, "aggregation_required")) and "count" in aggregation_functions
        if (primary == "metric_query" and secondary == "count_metric_query") or count_required:
            return (_count_metric(nodes, mapping_dict, projections),)
        return ()

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
            if node is None or (projection.attribute != "__internal_id" and attribute_id not in self.attributes):
                failures.append(_failure("attribute_owner_exists", "EngineeringFailure", "UNKNOWN_ONTOLOGY_ATTRIBUTE", f"unknown attribute {attribute_id}"))
        projection_expected = bool(_shape_value(plan.shape, "projection_expected"))
        if projection_expected and not plan.projections and not plan.metrics and not plan.node_returns:
            projection_target_options = _projection_target_clarification_options(plan)
            failures.append(
                _failure(
                    "shape_projection_consistency",
                    "ClarificationNeeded",
                    "MISSING_PROJECTION_TARGET",
                    "当前问题需要返回字段或对象，但未能确定具体返回内容",
                    source_step="step_3_5",
                    clarification_options=projection_target_options,
                    **(
                        {}
                        if projection_target_options
                        else {"no_option_reason": "当前 logical plan 没有可作为返回目标的本体节点或字段候选。"}
                    ),
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
        if len(plan.nodes) > 1 and not plan.edges:
            failures.append(
                _failure(
                    "no_cartesian_product",
                    "ClarificationNeeded",
                    "AMBIGUOUS_PATH",
                    "多个查询对象之间缺少明确连接关系，需要确认按哪条业务关系连接",
                    source_step="step_3_3",
                    clarification_options=self._path_clarification_options(plan.nodes),
                )
            )
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

    def _path_clarification_options(self, nodes: tuple[PlanNode, ...]) -> list[dict[str, Any]]:
        class_ids = {node.type for node in nodes}
        options: list[dict[str, Any]] = []
        seen: set[tuple[str, str, tuple[str, ...]]] = set()

        for relation_id, relation in self.relations.items():
            from_class = str(relation.get("domain") or relation.get("domain_class") or "")
            to_class = str(relation.get("range") or relation.get("range_class") or "")
            if from_class not in class_ids or to_class not in class_ids:
                continue
            key = (from_class, to_class, (relation_id,))
            if key in seen:
                continue
            seen.add(key)
            options.append(
                {
                    "option_id": f"P{len(options) + 1}",
                    "label": f"{from_class} -> {to_class}（{relation_id}）",
                    "from_class": from_class,
                    "to_class": to_class,
                    "relation_chain": [relation_id],
                }
            )

        default_paths = self.assets.domain_ontology.get("default_paths", [])
        for item in default_paths if isinstance(default_paths, list) else []:
            if not isinstance(item, dict):
                continue
            from_class = str(item.get("from_class") or "")
            to_class = str(item.get("to_class") or "")
            chain = [str(value) for value in item.get("relation_chain", []) if str(value)]
            if from_class not in class_ids or to_class not in class_ids or not chain:
                continue
            key = (from_class, to_class, tuple(chain))
            if key in seen:
                continue
            seen.add(key)
            options.append(
                {
                    "option_id": f"P{len(options) + 1}",
                    "label": f"{from_class} -> {to_class}（{' -> '.join(chain)}）",
                    "from_class": from_class,
                    "to_class": to_class,
                    "relation_chain": chain,
                }
            )
        return options

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
        source_step = next((item.get("source_step") for item in failures if item.get("source_step")), None)
        if source_step:
            payload["source_step"] = str(source_step)
        if plan is not None:
            payload["logical_plan_draft"] = plan.to_dict()
        first = failures[0]
        message = str(first.get("message") or "shape finalization precheck failed")
        error_type = first.get("error_type")
        if error_type == "ClarificationNeeded":
            raise ClarificationNeeded(stage="step_3_6", message=message, clarification=payload)
        if error_type == "ResourceMissing":
            raise ResourceMissing(stage="step_3_6", message=message, payload=payload)
        raise EngineeringFailure(stage="step_3_6", message=message, payload=payload)


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


def _shape_field(value: Any) -> InitialShapeField:
    if isinstance(value, InitialShapeField):
        return value
    if isinstance(value, dict):
        return InitialShapeField(
            value=value.get("value"),
            source=str(value.get("source") or "unknown"),
            decision=str(value.get("decision") or "accept"),
            confidence=float(value.get("confidence", 1.0)),
            derived_from=tuple(str(item) for item in value.get("derived_from", ()) if item is not None)
            if isinstance(value.get("derived_from"), (list, tuple))
            else (),
            pending_until=str(value["pending_until"]) if value.get("pending_until") is not None else None,
        )
    return InitialShapeField(value=value, source="shape_finalization.normalized", decision="accept", confidence=1.0)


def _default_confirmed_shape_fields() -> dict[str, InitialShapeField]:
    return {
        "aggregation_functions": InitialShapeField([], "shape_finalization.default", "accept", 1.0),
        "group_by_required": InitialShapeField(False, "shape_finalization.default", "accept", 1.0),
        "order_required": InitialShapeField(False, "shape_finalization.default", "accept", 1.0),
        "limit_required": InitialShapeField(False, "shape_finalization.default", "accept", 1.0),
        "time_grain_required": InitialShapeField(False, "shape_finalization.default", "accept", 1.0),
    }


def _classes(assets: OntologyAssets) -> set[str]:
    payload = assets.domain_ontology.get("classes", [])
    result = {str(item.get("id")) for item in payload if isinstance(item, dict) and item.get("id")}
    for entry in assets.entries:
        if entry.mention_type == "OBJECT":
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
        if entry.mention_type != "RELATION":
            continue
        relation_id = entry.canonical_id.removeprefix("REL_")
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
        if entry.mention_type == "ATTRIBUTE":
            result.add(entry.canonical_id)
    return result


def _mapping_node_sources(mapping_dict: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    sources: list[dict[str, Any]] = []
    for item in mapping_dict.get("ontology_objects", []):
        if isinstance(item, dict) and isinstance(item.get("class_id"), str):
            sources.append({"class_id": item["class_id"], "source": "explicit_user_mention"})
    for item in mapping_dict.get("ontology_attributes", []):
        if not isinstance(item, dict):
            continue
        parent_class = item.get("parent_class")
        candidates = item.get("attribute_candidates")
        if isinstance(parent_class, str) and parent_class and (
            not isinstance(candidates, list) or len(candidates) <= 1
        ):
            sources.append({"class_id": parent_class, "source": "attribute_owner"})
    for item in mapping_dict.get("ontology_values", []):
        if not isinstance(item, dict):
            continue
        attribute = item.get("constrains_attribute")
        if isinstance(attribute, str) and "." in attribute:
            sources.append({"class_id": attribute.split(".", 1)[0], "source": "value_owner"})
    return tuple(sources)


def _return_subject_classes(mapping_dict: dict[str, Any]) -> tuple[str, ...]:
    return _classes_for_selected_role(mapping_dict, "return_subject")


def _projection_subject_classes(mapping_dict: dict[str, Any]) -> tuple[str, ...]:
    return _classes_for_selected_role(mapping_dict, "projection_subject")


def _classes_for_selected_role(mapping_dict: dict[str, Any], role: str) -> tuple[str, ...]:
    classes: list[str] = []
    for item in mapping_dict.get("ontology_objects", []):
        if not isinstance(item, dict):
            continue
        roles = item.get("selected_roles")
        class_id = item.get("class_id")
        if isinstance(class_id, str) and isinstance(roles, (list, tuple)) and role in roles:
            classes.append(class_id)
    return tuple(dict.fromkeys(classes))


def _path_node_sources(path_dict: dict[str, Any], relations: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    sources: list[dict[str, Any]] = []
    selected_paths = path_dict.get("selected_paths", [])
    if not isinstance(selected_paths, (list, tuple)):
        return ()
    for selected in selected_paths:
        if not isinstance(selected, dict):
            continue
        chain = selected.get("relation_chain")
        if not isinstance(chain, (list, tuple)):
            continue
        for raw_relation_id in chain:
            relation = relations.get(_normalize_relation_id(str(raw_relation_id)))
            if not isinstance(relation, dict):
                continue
            for key in ("domain", "domain_class", "range", "range_class"):
                value = relation.get(key)
                if isinstance(value, str) and value:
                    sources.append({"class_id": value, "source": "selected_path"})
    return tuple(sources)


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
    return relation_id


def _operator(value: str) -> str:
    return {"equals": "=", "eq": "=", "==": "="}.get(value, value)


def _normalize_projection_aliases(
    projections: tuple[PlanProjection, ...],
    nodes: tuple[PlanNode, ...],
    edges: tuple[PlanEdge, ...],
) -> tuple[PlanProjection, ...]:
    if (
        len(nodes) != 1
        or edges
        or not any(item.attribute == "__internal_id" for item in projections)
        or any(item.node != nodes[0].id for item in projections)
    ):
        return projections
    aliases = {"__internal_id": "id", "name": "name", "elem_type": "type"}
    return tuple(
        PlanProjection(node=item.node, attribute=item.attribute, alias=aliases.get(item.attribute, item.alias))
        for item in projections
    )


def _prune_unreferenced_nodes(
    nodes: tuple[PlanNode, ...],
    edges: tuple[PlanEdge, ...],
    projections: tuple[PlanProjection, ...],
    metrics: tuple[PlanMetric, ...],
    node_returns: tuple[PlanNodeReturn, ...],
    mapping_dict: dict[str, Any],
) -> tuple[PlanNode, ...]:
    if len(nodes) <= 1:
        return nodes
    referenced = {edge.from_node for edge in edges} | {edge.to_node for edge in edges}
    referenced.update(item.node for item in projections)
    referenced.update(item.node for item in node_returns)
    for metric in metrics:
        referenced.add(metric.node)
        referenced.update(item.node for item in metric.condition)
    referenced.update(node.id for node in nodes if node.filters)
    if not referenced:
        return nodes
    pruned = tuple(
        node
        for node in nodes
        if node.id in referenced or _mapping_source_for_node(node, mapping_dict) != "attribute_owner"
    )
    return pruned or nodes


def _intent_identity(payload: dict[str, Any]) -> Any:
    intent = payload.get("intent", payload)
    if not isinstance(intent, dict):
        intent = {}
    return Intent(
        primary=str(intent.get("primary") or "record_retrieval_query"),
        secondary=str(intent.get("secondary") or "related_record_query"),
        source=str(intent.get("source") or "shape_finalization.default"),
        decision=str(intent.get("decision") or "accept"),
        confidence=float(intent.get("confidence", 1.0)),
    )


def _shape_value(shape: dict[str, InitialShapeField], key: str) -> Any:
    field = shape.get(key)
    return field.value if field is not None else None


def _mapping_source_for_node(node: PlanNode, mapping_dict: dict[str, Any]) -> str | None:
    for item in _mapping_node_sources(mapping_dict):
        if item.get("class_id") == node.type:
            return str(item.get("source") or "")
    return None


def _node_by_type(nodes: tuple[PlanNode, ...], node_type: str) -> PlanNode | None:
    for node in nodes:
        if node.type == node_type:
            return node
    return None


def _count_metric(
    nodes: tuple[PlanNode, ...],
    mapping_dict: dict[str, Any],
    projections: tuple[PlanProjection, ...],
) -> PlanMetric:
    target = _metric_target_node(nodes, preferred_classes=_classes_for_selected_role(mapping_dict, "metric_subject"))
    attribute = _count_attribute_from_projections(target, projections)
    alias = "total" if attribute is not None else f"{_metric_alias_prefix(target.type)}_count"
    return PlanMetric(function="count", node=target.id, alias=alias, attribute=attribute)


def _count_attribute_from_projections(
    target: PlanNode,
    projections: tuple[PlanProjection, ...],
) -> str | None:
    candidate_attrs = [
        item.attribute
        for item in projections
        if item.node == target.id and item.attribute not in {"__internal_id"}
    ]
    if len(candidate_attrs) == 1:
        return candidate_attrs[0]
    return None


def _projections_after_metric(
    intent_output: Any,
    shape: dict[str, InitialShapeField],
    projections: tuple[PlanProjection, ...],
    metrics: tuple[PlanMetric, ...],
) -> tuple[PlanProjection, ...]:
    if not metrics:
        return projections
    if bool(_shape_value(shape, "group_by_required")):
        return projections
    intent = getattr(intent_output, "intent", None)
    primary = str(getattr(intent, "primary", ""))
    secondary = str(getattr(intent, "secondary", ""))
    aggregation_functions = tuple(str(item) for item in (_shape_value(shape, "aggregation_functions") or ()))
    count_metric = (primary == "metric_query" and secondary == "count_metric_query") or (
        bool(_shape_value(shape, "aggregation_required")) and "count" in aggregation_functions
    )
    if count_metric and all(item.function == "count" for item in metrics):
        return ()
    return projections


def _metric_target_node(nodes: tuple[PlanNode, ...], *, preferred_classes: tuple[str, ...] = ()) -> PlanNode:
    for preferred in preferred_classes:
        node = _node_by_type(nodes, preferred)
        if node is not None:
            return node
    for preferred in ("Tunnel", "Service", "NetworkElement", "Port"):
        node = _node_by_type(nodes, preferred)
        if node is not None:
            return node
    if nodes:
        return nodes[-1]
    raise ClarificationNeeded(
        stage="step_3_6",
        message="metric query has no ontology node to count",
        clarification={
            "source_step": "step_3_6",
            "reason_code": "MISSING_METRIC_TARGET",
            "reason": "当前问题是统计类查询，但未能确定要统计的对象。",
            "missing_information": "用户需要明确要统计服务、隧道、网元、端口或其他对象。",
            "options": [],
            "no_option_reason": "当前 logical plan 中没有可统计的本体对象。",
        },
    )


def _metric_alias_prefix(class_id: str) -> str:
    return {"Service": "service", "Tunnel": "tunnel", "NetworkElement": "network_element", "Port": "port"}.get(
        class_id,
        class_id.lower(),
    )


def _metric_conditions(binding_dict: dict[str, Any]) -> tuple[PlanFilter, ...]:
    conditions: list[PlanFilter] = []
    for item in binding_dict.get("metric_conditions", []):
        if not isinstance(item, dict) or item.get("decision", "accept") != "accept":
            continue
        result = item.get("result")
        if not isinstance(result, dict):
            continue
        attribute = str(result.get("attribute") or "")
        if "." not in attribute:
            continue
        _, attr = attribute.split(".", 1)
        conditions.append(
            PlanFilter(
                node=str(result.get("node") or ""),
                attr=attr,
                operator=_operator(str(result.get("operator") or "=")),
                value=result.get("value"),
            )
        )
    return tuple(conditions)


def _conditional_metric_alias(
    target: PlanNode,
    condition: PlanFilter,
    node_by_id: dict[str, PlanNode],
    index: int,
) -> str:
    condition_node = node_by_id.get(condition.node)
    condition_prefix = _condition_alias_prefix(condition_node.type if condition_node else "")
    target_prefix = _metric_alias_prefix(target.type)
    if condition_prefix:
        return f"{condition_prefix}_{target_prefix}_count"
    return f"conditional_{index}_{target_prefix}_count"


def _condition_alias_prefix(class_id: str) -> str:
    return {"NetworkElement": "source_ne", "Port": "port", "Service": "service", "Tunnel": "tunnel"}.get(
        class_id,
        class_id.lower() if class_id else "",
    )


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


def _projection_target_clarification_options(plan: OntologyLogicalPlan) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in plan.nodes:
        if node.type in seen:
            continue
        seen.add(node.type)
        options.append(
            {
                "option_id": f"N{len(options) + 1}",
                "label": f"返回 {node.type} 对象",
                "node": node.id,
                "class_id": node.type,
            }
        )
    return options


def _logical_plan_output(plan: OntologyLogicalPlan) -> dict[str, Any]:
    payload = plan.to_dict()
    payload["relationships"] = [
        {"from": edge.from_node, "to": edge.to_node, "relation": edge.relation} for edge in plan.edges
    ]
    payload.pop("edges", None)
    return payload
