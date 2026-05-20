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
        for constraint in self.constraints.get("constraints", []):
            if not isinstance(constraint, dict):
                continue
            if constraint.get("type") == "return_non_empty":
                checks.append(
                    {
                        "check": "constraint_rule",
                        "constraint_id": constraint.get("id"),
                        "severity": constraint.get("severity"),
                        "accepted": bool(plan.projections or plan.metrics),
                    }
                )
        for edge in plan.edges:
            from_type = node_by_id[edge.from_node].type
            to_type = node_by_id[edge.to_node].type
            relation = self.assets.relation(edge.relation)
            accepted = relation.metadata.get("domain") == from_type and relation.metadata.get("range") == to_type
            checks.append(
                {
                    "check": "edge_domain_range",
                    "edge": edge.relation,
                    "accepted": accepted,
                    "expected": [relation.metadata.get("domain"), relation.metadata.get("range")],
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
            node = node_by_id[projection.node]
            attribute_id = f"{node.type}.{projection.attribute}"
            accepted = attribute_id in self.assets.by_id
            checks.append(
                {
                    "check": "projection_attribute_exists",
                    "attribute": attribute_id,
                    "accepted": accepted,
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
                "accepted": bool(plan.projections or plan.metrics),
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
