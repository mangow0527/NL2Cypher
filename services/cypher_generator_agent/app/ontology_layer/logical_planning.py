from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.cypher_generator_agent.app.intent_layer.models import IntentOutput

from .assets import OntologyAssets
from .binding import BindingTrace, OntologyBindingService
from .coreference import OntologyCoreferenceService
from .models import LexerTrace, OntologyLogicalPlan
from .shape_finalization import OntologyShapeFinalizer, ShapeFinalizationResult


@dataclass(frozen=True)
class OntologyLogicalPlanningTrace:
    coreference: dict[str, Any]
    binding: BindingTrace
    shape_finalization: ShapeFinalizationResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "coreference": dict(self.coreference),
            "binding": self.binding.to_dict(),
            "shape_finalization": self.shape_finalization.to_dict(),
        }


class OntologyLogicalPlanningService:
    def __init__(
        self,
        *,
        assets: OntologyAssets,
        coreference_service: OntologyCoreferenceService | None = None,
        binding_service: OntologyBindingService | None = None,
        shape_finalizer: OntologyShapeFinalizer | None = None,
    ) -> None:
        self.assets = assets
        self.coreference_service = coreference_service or OntologyCoreferenceService()
        self.binding_service = binding_service or OntologyBindingService()
        self.shape_finalizer = shape_finalizer or OntologyShapeFinalizer(assets)
        self.relations = _relations_by_id(assets)

    def plan(
        self,
        *,
        question: str,
        lexer_trace: LexerTrace,
        intent_output: IntentOutput,
        ontology_mapping: dict[str, Any],
        ontology_path_selection: Any,
    ) -> tuple[OntologyLogicalPlan, OntologyLogicalPlanningTrace]:
        path_payload = _to_dict(ontology_path_selection)
        coreference = self.coreference_service.resolve(
            question=question,
            ontology_mapping=ontology_mapping,
            selected_paths=path_payload.get("selected_paths", []),
            shape_signals=[signal.to_dict() for signal in lexer_trace.shape_signals],
            context_signals=[signal.to_dict() for signal in lexer_trace.context_signals],
            explicit_distinction_signals=[],
            intent={"primary": intent_output.intent.primary, "secondary": intent_output.intent.secondary},
        )
        coreference = _with_planning_nodes(coreference, ontology_mapping, path_payload, self.relations)
        binding = self.binding_service.bind(
            ontology_mapping=ontology_mapping,
            merged_nodes=coreference.get("merged_nodes", []),
            candidate_family={},
            context_signals=lexer_trace.context_signals,
            shape_signals=lexer_trace.shape_signals,
            intent_output=intent_output,
            question=question,
            unmatched_fragments=lexer_trace.unmatched_fragments,
        )
        shape_finalization = self.shape_finalizer.finalize(
            intent_output=intent_output,
            ontology_mapping=ontology_mapping,
            ontology_path_selection=ontology_path_selection,
            coreference=coreference,
            binding=binding.to_dict(),
        )
        return shape_finalization.logical_plan, OntologyLogicalPlanningTrace(
            coreference=coreference,
            binding=binding,
            shape_finalization=shape_finalization,
        )


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


def _with_planning_nodes(
    coreference: dict[str, Any],
    ontology_mapping: dict[str, Any],
    path_payload: dict[str, Any],
    relations: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    merged_nodes = [dict(item) for item in coreference.get("merged_nodes", []) if isinstance(item, dict)]
    known_classes = {str(item.get("class_id")) for item in merged_nodes if item.get("class_id")}
    for class_id in _planning_node_classes(ontology_mapping, path_payload, relations):
        if class_id in known_classes:
            continue
        merged_nodes.append({"node_id": _node_id(class_id), "class_id": class_id, "object_ids": []})
        known_classes.add(class_id)
    return {**coreference, "merged_nodes": merged_nodes}


def _planning_node_classes(
    ontology_mapping: dict[str, Any],
    path_payload: dict[str, Any],
    relations: dict[str, dict[str, Any]],
) -> tuple[str, ...]:
    classes: list[str] = []
    for item in ontology_mapping.get("ontology_objects", []):
        if isinstance(item, dict):
            _append_class(classes, item.get("class_id"))
    for item in ontology_mapping.get("ontology_values", []):
        if not isinstance(item, dict):
            continue
        attribute = item.get("constrains_attribute")
        if isinstance(attribute, str) and "." in attribute:
            _append_class(classes, attribute.split(".", 1)[0])
    for item in ontology_mapping.get("ontology_attributes", []):
        if not isinstance(item, dict):
            continue
        parent = item.get("parent_class")
        candidates = item.get("attribute_candidates")
        if isinstance(parent, str) and parent and (not isinstance(candidates, list) or len(candidates) <= 1):
            _append_class(classes, parent)
    for selected in path_payload.get("selected_paths", []):
        if not isinstance(selected, dict):
            continue
        chain = selected.get("relation_chain")
        if not isinstance(chain, (list, tuple)):
            continue
        for raw_relation_id in chain:
            relation = relations.get(_normalize_relation_id(str(raw_relation_id)))
            if not isinstance(relation, dict):
                continue
            _append_class(classes, relation.get("domain") or relation.get("domain_class"))
            _append_class(classes, relation.get("range") or relation.get("range_class"))
    return tuple(classes)


def _append_class(classes: list[str], value: Any) -> None:
    if not isinstance(value, str) or not value or value in classes:
        return
    classes.append(value)


def _relations_by_id(assets: OntologyAssets) -> dict[str, dict[str, Any]]:
    relations: dict[str, dict[str, Any]] = {}
    for item in assets.domain_ontology.get("relations", []):
        if not isinstance(item, dict):
            continue
        relation_id = _normalize_relation_id(str(item.get("id") or item.get("relation") or ""))
        if relation_id:
            relations[relation_id] = dict(item)
    for entry in assets.entries:
        if entry.mention_type != "relation_predicate":
            continue
        relation_id = _normalize_relation_id(entry.canonical_id)
        relations.setdefault(
            relation_id,
            {
                "id": relation_id,
                "domain": entry.metadata.get("domain"),
                "range": entry.metadata.get("range"),
                "role": entry.metadata.get("role"),
            },
        )
    return relations


def _normalize_relation_id(relation_id: str) -> str:
    return relation_id.removeprefix("REL_")


def _node_id(class_id: str) -> str:
    return {"Service": "s1", "Tunnel": "t1", "NetworkElement": "n1", "Port": "p1", "Protocol": "proto1"}.get(
        class_id,
        f"{class_id[:1].lower()}1",
    )
