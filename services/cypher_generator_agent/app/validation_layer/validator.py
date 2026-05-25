from __future__ import annotations

from typing import Any

import yaml

from services.cypher_generator_agent.app.infrastructure import resource_paths

from services.cypher_generator_agent.app.ontology_layer.assets import OntologyAssets
from services.cypher_generator_agent.app.ontology_layer.models import OntologyLogicalPlan, ValidatorTrace


class OntologySemanticValidator:
    def __init__(self, assets: OntologyAssets, *, constraints: dict[str, Any] | None = None) -> None:
        self.assets = assets
        self.constraints = constraints or _load_constraints()
        self.cardinality_by_relation = {
            str(item.get("relation")): item
            for item in self.constraints.get("relation_cardinality", [])
            if isinstance(item, dict)
        }

    def validate(self, plan: OntologyLogicalPlan) -> ValidatorTrace:
        checks: list[dict[str, object]] = []
        node_by_id = {node.id: node for node in plan.nodes}
        class_ids = _class_ids(self.assets)
        attribute_ids = _attribute_ids(self.assets)
        for node in plan.nodes:
            checks.append(
                {
                    "check": "node_class_exists",
                    "node": node.id,
                    "class": node.type,
                    "accepted": node.type in class_ids,
                }
            )
        for constraint in self.constraints.get("constraints", []):
            if not isinstance(constraint, dict):
                continue
            if constraint.get("type") == "return_non_empty":
                checks.append(
                    {
                        "check": "constraint_rule",
                        "constraint_id": constraint.get("id"),
                        "severity": constraint.get("severity"),
                        "accepted": bool(plan.projections or plan.metrics or plan.node_returns),
                    }
                )
        for edge in plan.edges:
            from_node = node_by_id.get(edge.from_node)
            to_node = node_by_id.get(edge.to_node)
            edge_nodes_exist = from_node is not None and to_node is not None
            checks.append(
                {
                    "check": "edge_nodes_exist",
                    "edge": edge.relation,
                    "accepted": edge_nodes_exist,
                    "from": edge.from_node,
                    "to": edge.to_node,
                }
            )
            if not edge_nodes_exist:
                continue
            from_type = from_node.type
            to_type = to_node.type
            relation = _domain_relation(self.assets, edge.relation)
            accepted = relation.get("domain") == from_type and relation.get("range") == to_type
            checks.append(
                {
                    "check": "edge_domain_range",
                    "edge": edge.relation,
                    "accepted": accepted,
                    "expected": [relation.get("domain"), relation.get("range")],
                    "actual": [from_type, to_type],
                }
            )
            cardinality = self.cardinality_by_relation.get(edge.relation)
            checks.append(
                {
                    "check": "relation_cardinality_policy",
                    "relation": edge.relation,
                    "accepted": cardinality is not None,
                    "from_side": cardinality.get("from_side") if isinstance(cardinality, dict) else None,
                    "to_side": cardinality.get("to_side") if isinstance(cardinality, dict) else None,
                    "confidence": _cardinality_confidence(cardinality),
                }
            )
        for projection in plan.projections:
            node = node_by_id.get(projection.node)
            attribute_id = f"{node.type}.{projection.attribute}" if node is not None else f"UNKNOWN.{projection.attribute}"
            accepted = projection.attribute == "__internal_id" or attribute_id in self.assets.by_id
            checks.append(
                {
                    "check": "projection_attribute_exists",
                    "attribute": attribute_id,
                    "accepted": node is not None and accepted,
                }
            )
        for node in plan.nodes:
            for item in node.filters:
                attribute_id = f"{node.type}.{item.attr}"
                checks.append(
                    {
                        "check": "filter_attribute_exists",
                        "node": node.id,
                        "attribute": attribute_id,
                        "accepted": attribute_id in attribute_ids,
                    }
                )
        for item in plan.node_returns:
            checks.append(
                {
                    "check": "node_return_exists",
                    "node": item.node,
                    "accepted": item.node in node_by_id,
                }
            )
        for metric in plan.metrics:
            accepted = metric.node in node_by_id and metric.function in {"count", "conditional_count"}
            checks.append(
                {
                    "check": "metric_expression_supported",
                    "metric": metric.alias,
                    "function": metric.function,
                    "node": metric.node,
                    "accepted": accepted,
                }
            )
            for condition in metric.condition:
                node = node_by_id.get(condition.node)
                attribute_id = f"{node.type}.{condition.attr}" if node else f"UNKNOWN.{condition.attr}"
                checks.append(
                    {
                        "check": "metric_condition_attribute_exists",
                        "metric": metric.alias,
                        "attribute": attribute_id,
                        "accepted": node is not None and attribute_id in self.assets.by_id,
                    }
                )
        checks.append(
            {
                "check": "return_non_empty",
                "accepted": bool(plan.projections or plan.metrics or plan.node_returns),
            }
        )
        accepted = all(bool(item["accepted"]) for item in checks)
        return ValidatorTrace(accepted=accepted, checks=tuple(checks))


def _load_constraints() -> dict[str, Any]:
    path = resource_paths.ontology_constraints_path()
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {"constraints": [], "relation_cardinality": []}
    return payload


def _domain_relation(assets: OntologyAssets, relation_id: str) -> dict[str, Any]:
    for item in assets.domain_ontology.get("relations", []):
        if isinstance(item, dict) and item.get("id") == relation_id:
            return item
    return {}


def _class_ids(assets: OntologyAssets) -> set[str]:
    return {
        str(item.get("id"))
        for item in assets.domain_ontology.get("classes", [])
        if isinstance(item, dict) and item.get("id")
    }


def _attribute_ids(assets: OntologyAssets) -> set[str]:
    attribute_ids = {
        str(item.get("id"))
        for item in assets.domain_ontology.get("attributes", [])
        if isinstance(item, dict) and item.get("id")
    }
    attribute_ids.update(entry.canonical_id for entry in assets.entries if entry.mention_type == "ATTRIBUTE")
    return attribute_ids


def _cardinality_confidence(cardinality: object) -> str | None:
    if not isinstance(cardinality, dict):
        return None
    confidences = []
    for side in ("from_side", "to_side"):
        value = cardinality.get(side)
        if isinstance(value, dict) and value.get("confidence"):
            confidences.append(str(value["confidence"]))
    if "needs_review" in confidences:
        return "needs_review"
    if "inferred" in confidences:
        return "inferred"
    if "confirmed" in confidences:
        return "confirmed"
    return None
