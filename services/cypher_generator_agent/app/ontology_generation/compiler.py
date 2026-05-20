from __future__ import annotations

from typing import Any

import yaml

from services.cypher_generator_agent.app import resource_paths

from .errors import EngineeringFailure
from .models import CompilerTrace, OntologyLogicalPlan, PlanEdge, PlanNode


class OntologyPhysicalCompiler:
    def __init__(
        self,
        *,
        mapping: dict[str, Any] | None = None,
        physical_schema: dict[str, Any] | None = None,
    ) -> None:
        self.mapping = mapping or _load_yaml(resource_paths.ontology_cypher_mapping_path())
        self.physical_schema = physical_schema or _load_yaml(resource_paths.ontology_physical_graph_schema_path())
        self.class_mappings = {
            item["ontology_class"]: item for item in self.mapping.get("class_mappings", []) if isinstance(item, dict)
        }
        self.attribute_mappings = {
            item["ontology_attribute"]: item for item in self.mapping.get("attribute_mappings", []) if isinstance(item, dict)
        }
        self.relation_mappings = {
            item["ontology_relation"]: item for item in self.mapping.get("relation_mappings", []) if isinstance(item, dict)
        }

    def without_attribute_mapping(self, ontology_attribute: str) -> "OntologyPhysicalCompiler":
        mapping = {
            **self.mapping,
            "attribute_mappings": [
                item
                for item in self.mapping.get("attribute_mappings", [])
                if not isinstance(item, dict) or item.get("ontology_attribute") != ontology_attribute
            ],
        }
        return OntologyPhysicalCompiler(mapping=mapping, physical_schema=self.physical_schema)

    def compile(self, plan: OntologyLogicalPlan) -> CompilerTrace:
        match_clause = self._match_clause(plan)
        lines = [f"MATCH {match_clause}"]
        filters = [self._filter_expression(node) for node in plan.nodes for _ in node.filters]
        filters = [item for item in filters if item]
        if filters:
            lines.append(f"WHERE {' AND '.join(filters)}")
        return_items = [
            f"{self._node_variable(self._node(plan, projection.node))}.{self._attribute_property(self._node(plan, projection.node), projection.attribute)} AS {projection.alias}"
            for projection in plan.projections
        ]
        return_items.extend(self._metric_expression(plan, metric) for metric in plan.metrics)
        lines.append(f"RETURN {', '.join(return_items)}")
        cypher = "\n".join(lines)
        return CompilerTrace(
            renderer_family="ontology_record_retrieval_v1",
            mapping_version=int(self.mapping.get("version", 0)),
            physical_schema_version=int(self.physical_schema.get("version", 0)),
            physical_bindings={node.id: f"{self._node_variable(node)}:{self._node_label(node)}" for node in plan.nodes},
            attribute_bindings=self._attribute_bindings(plan),
            cypher=cypher,
        )

    def _match_clause(self, plan: OntologyLogicalPlan) -> str:
        if plan.edges and _is_chain(plan.edges):
            parts = [self._node_pattern(self._node(plan, plan.edges[0].from_node))]
            for edge in plan.edges:
                parts.append(f"-[:{self._edge_type(edge)}]->")
                parts.append(self._node_pattern(self._node(plan, edge.to_node)))
            return "".join(parts)
        if plan.edges:
            return ", ".join(
                f"{self._node_pattern(self._node(plan, edge.from_node))}-[:{self._edge_type(edge)}]->"
                f"{self._node_pattern(self._node(plan, edge.to_node))}"
                for edge in plan.edges
            )
        return ", ".join(self._node_pattern(node) for node in plan.nodes)

    def _filter_expression(self, node: PlanNode) -> str | None:
        if not node.filters:
            return None
        return " AND ".join(
            f"{self._node_variable(node)}.{self._attribute_property(node, item.attr)} {item.operator} {self._literal(self._mapped_value(node, item.attr, item.value))}"
            for item in node.filters
        )

    def _node(self, plan: OntologyLogicalPlan, node_id: str) -> PlanNode:
        for node in plan.nodes:
            if node.id == node_id:
                return node
        raise EngineeringFailure(stage="compiler", message=f"missing node {node_id}")

    def _node_pattern(self, node: PlanNode) -> str:
        return f"({self._node_variable(node)}:{self._node_label(node)})"

    def _node_label(self, node: PlanNode) -> str:
        mapping = self.class_mappings.get(node.type)
        if not mapping:
            raise EngineeringFailure(stage="compiler", message=f"missing class mapping for {node.type}")
        label = str(mapping.get("node_label"))
        if label not in _physical_labels(self.physical_schema):
            raise EngineeringFailure(stage="compiler", message=f"node label {label} missing from physical graph schema")
        return label

    def _node_variable(self, node: PlanNode) -> str:
        mapping = self.class_mappings.get(node.type)
        if not mapping:
            raise EngineeringFailure(stage="compiler", message=f"missing class mapping for {node.type}")
        return str(mapping.get("variable") or node.alias)

    def _edge_type(self, edge: PlanEdge) -> str:
        mapping = self.relation_mappings.get(edge.relation)
        if not mapping:
            raise EngineeringFailure(stage="compiler", message=f"missing relation mapping for {edge.relation}")
        edge_type = str(mapping.get("edge_type"))
        if edge_type not in _physical_edges(self.physical_schema):
            raise EngineeringFailure(stage="compiler", message=f"edge type {edge_type} missing from physical graph schema")
        return edge_type

    def _attribute_property(self, node: PlanNode, attr: str) -> str:
        ontology_attribute = f"{node.type}.{attr}"
        mapping = self.attribute_mappings.get(ontology_attribute)
        if not mapping:
            raise EngineeringFailure(stage="compiler", message=f"missing attribute mapping for {ontology_attribute}")
        node_property = str(mapping.get("node_property"))
        label = self._node_label(node)
        if node_property not in _physical_properties(self.physical_schema, label):
            raise EngineeringFailure(
                stage="compiler",
                message=f"property {label}.{node_property} missing from physical graph schema",
            )
        return node_property

    def _mapped_value(self, node: PlanNode, attr: str, value: Any) -> Any:
        mapping = self.attribute_mappings.get(f"{node.type}.{attr}") or {}
        transforms = mapping.get("value_transform")
        if isinstance(transforms, dict) and value in transforms:
            return transforms[value]
        return value

    def _attribute_bindings(self, plan: OntologyLogicalPlan) -> dict[str, str]:
        bindings: dict[str, str] = {}
        for node in plan.nodes:
            for item in node.filters:
                ontology_attribute = f"{node.type}.{item.attr}"
                bindings[ontology_attribute] = f"{self._node_variable(node)}.{self._attribute_property(node, item.attr)}"
        for projection in plan.projections:
            node = self._node(plan, projection.node)
            ontology_attribute = f"{node.type}.{projection.attribute}"
            bindings[ontology_attribute] = f"{self._node_variable(node)}.{self._attribute_property(node, projection.attribute)}"
        for metric in plan.metrics:
            for item in metric.condition:
                node = self._node(plan, item.node)
                ontology_attribute = f"{node.type}.{item.attr}"
                bindings[ontology_attribute] = f"{self._node_variable(node)}.{self._attribute_property(node, item.attr)}"
        return bindings

    def _metric_expression(self, plan: OntologyLogicalPlan, metric: Any) -> str:
        node = self._node(plan, metric.node)
        if metric.function == "count":
            distinct = "DISTINCT " if metric.distinct else ""
            return f"count({distinct}{self._node_variable(node)}) AS {metric.alias}"
        if metric.function == "conditional_count":
            if len(metric.condition) != 1:
                raise EngineeringFailure(stage="compiler", message=f"conditional_count requires exactly one condition for {metric.alias}")
            condition = self._condition_expression(plan, metric.condition[0])
            return f"sum(CASE WHEN {condition} THEN 1 ELSE 0 END) AS {metric.alias}"
        raise EngineeringFailure(stage="compiler", message=f"unsupported metric function {metric.function}")

    def _condition_expression(self, plan: OntologyLogicalPlan, condition: Any) -> str:
        node = self._node(plan, condition.node)
        return (
            f"{self._node_variable(node)}.{self._attribute_property(node, condition.attr)} "
            f"{condition.operator} {self._literal(self._mapped_value(node, condition.attr, condition.value))}"
        )

    def _literal(self, value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"


def _is_chain(edges: tuple[PlanEdge, ...]) -> bool:
    if len(edges) < 2:
        return bool(edges)
    return all(left.to_node == right.from_node for left, right in zip(edges, edges[1:]))


def _load_yaml(path: Any) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise EngineeringFailure(stage="compiler", message=f"{path} must contain a YAML mapping")
    return payload


def _physical_labels(schema: dict[str, Any]) -> set[str]:
    return {str(item.get("label")) for item in schema.get("node_labels", []) if isinstance(item, dict)}


def _physical_edges(schema: dict[str, Any]) -> set[str]:
    return {str(item.get("edge_type")) for item in schema.get("edge_types", []) if isinstance(item, dict)}


def _physical_properties(schema: dict[str, Any], label: str) -> set[str]:
    for item in schema.get("node_labels", []):
        if isinstance(item, dict) and item.get("label") == label:
            properties = item.get("properties", [])
            return {str(value) for value in properties if isinstance(value, str)}
    return set()
