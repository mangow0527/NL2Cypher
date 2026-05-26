from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from services.cypher_generator_agent.app.intent_layer.models import IntentOutput, InitialShapeField

from .models import ContextSignal


class BindingValidationError(ValueError):
    pass


@dataclass(frozen=True)
class BindingCandidate:
    candidate_id: str
    kind: str
    mapping_id: str
    mention_id: str
    surface: str
    span_start: int
    span_end: int
    attribute: str
    owner_node: str
    owner_class: str
    score: int
    evidence_ids: tuple[str, ...]
    evidence: tuple[str, ...]
    value: Any = None
    operator: str = "equals"
    value_kind: str | None = None
    value_id: str | None = None
    value_literal: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "id": self.candidate_id,
            "kind": self.kind,
            "mapping_id": self.mapping_id,
            "mention_id": self.mention_id,
            "surface": self.surface,
            "span": [self.span_start, self.span_end],
            "attribute": self.attribute,
            "owner_node": self.owner_node,
            "owner_class": self.owner_class,
            "score": self.score,
            "evidence_ids": list(self.evidence_ids),
            "evidence": list(self.evidence),
            "value": self.value,
            "operator": self.operator,
        }
        if self.value_kind is not None:
            payload["value_kind"] = self.value_kind
        if self.value_id is not None:
            payload["value_id"] = self.value_id
        if self.value_literal is not None:
            payload["value_literal"] = dict(self.value_literal)
        return payload


@dataclass(frozen=True)
class BindingItem:
    item: str
    kind: str
    candidates: tuple[BindingCandidate, ...]
    selected: str | None
    decision: str
    result: dict[str, Any]
    evidence_ids: tuple[str, ...]
    selected_by: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "item": self.item,
            "kind": self.kind,
            "candidates": [item.to_dict() for item in self.candidates],
            "selected": self.selected,
            "decision": self.decision,
            "result": dict(self.result),
            "evidence_ids": list(self.evidence_ids),
            "selected_by": self.selected_by,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class BindingTrace:
    filters: tuple[BindingItem, ...]
    projections: tuple[BindingItem, ...]
    shape_updates: dict[str, InitialShapeField]
    unresolved_items: tuple[dict[str, Any], ...]
    metric_conditions: tuple[BindingItem, ...] = ()
    llm_raw_output: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": "step_3_5_binding",
            "filters": [item.to_dict() for item in self.filters],
            "projections": [item.to_dict() for item in self.projections],
            "metric_conditions": [item.to_dict() for item in self.metric_conditions],
            "shape_updates": {key: value.to_dict() for key, value in self.shape_updates.items()},
            "unresolved_items": [dict(item) for item in self.unresolved_items],
            "llm_raw_output": self.llm_raw_output,
        }


class OntologyBindingService:
    def __init__(self, *, llm_selector: object | None = None) -> None:
        self.llm_selector = llm_selector

    def bind(
        self,
        *,
        ontology_mapping: dict[str, Any],
        merged_nodes: Any,
        candidate_family: dict[str, Any] | None,
        context_signals: tuple[ContextSignal, ...] | list[ContextSignal],
        shape_signals: tuple[ContextSignal, ...] | list[ContextSignal],
        intent_output: IntentOutput,
        question: str,
        unmatched_fragments: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
        path_owner_scope: tuple[str, ...] | list[str] = (),
    ) -> BindingTrace:
        nodes = _node_index(merged_nodes)
        family = candidate_family or {}
        context = tuple(context_signals)
        shape = tuple(shape_signals)
        path_scope = tuple(str(item) for item in path_owner_scope if str(item))
        filters: list[BindingItem] = []
        projections: list[BindingItem] = []
        metric_conditions: list[BindingItem] = []
        unresolved: list[dict[str, Any]] = []
        llm_raw_output: str | None = None
        filter_index = 0
        projection_index = 0
        binding_mappings = _binding_mappings(ontology_mapping)
        predicate_mappings, predicate_attribute_mentions = _predicate_mappings(
            question=question,
            binding_mappings=binding_mappings,
            ontology_mapping=ontology_mapping,
            nodes=nodes,
        )

        for mapping in predicate_mappings:
            filter_index += 1
            candidates = _value_candidates(mapping, nodes, filter_index)
            if not candidates:
                unresolved.append(
                    _unresolved(
                        mapping,
                        "missing_binding_candidate",
                        "no owner node for composed predicate",
                        no_option_reason="没有可用的绑定候选。",
                    )
                )
                continue
            selected = _select_by_rules(candidates, context, shape)
            item = _binding_item(
                mapping,
                "filter",
                candidates,
                selected,
                "predicate_assembly",
                "attribute operator literal predicate",
            )
            filters.append(item)

        for mapping in binding_mappings:
            if not isinstance(mapping, dict):
                continue
            kind = str(mapping.get("ontology_kind", ""))
            mention_type = str(mapping.get("mention_type", ""))
            if mention_type == "VALUE" or kind in {"enum_value", "literal_value"}:
                filter_index += 1
                candidates = _value_candidates(mapping, nodes, filter_index)
                if not candidates:
                    unresolved.append(
                        _unresolved(
                            mapping,
                            "missing_binding_candidate",
                            "no owner node for constrained attribute",
                            no_option_reason="没有可用的绑定候选。",
                        )
                    )
                    continue
                selected = _select_by_rules(candidates, context, shape)
                item_kind = "metric_condition" if mapping.get("condition_scope") == "metric_condition" else "filter"
                item = _binding_item(mapping, item_kind, candidates, selected, "auto_single_candidate", "unique filter candidate")
                if item_kind == "metric_condition":
                    metric_conditions.append(item)
                else:
                    filters.append(item)
            elif mention_type == "ATTRIBUTE" or kind == "attribute":
                if str(mapping.get("mention_id") or "") in predicate_attribute_mentions:
                    continue
                candidates, projection_index = _attribute_candidates(
                    mapping,
                    nodes,
                    family,
                    context,
                    shape,
                    intent_output,
                    projection_index,
                    path_scope,
                )
                if not candidates:
                    unresolved.append(
                        _unresolved(
                            mapping,
                            "missing_binding_candidate",
                            "no owner node for attribute candidate",
                            no_option_reason="没有可用的绑定候选。",
                        )
                    )
                    continue
                selected_many = _select_many_by_rules(candidates)
                if selected_many:
                    for selected_candidate in selected_many:
                        projections.append(
                            _binding_item(
                                mapping,
                                "projection",
                                candidates,
                                selected_candidate,
                                "auto_projection_owner_context",
                                "endpoint projection candidates share explicit return context",
                            )
                        )
                    continue
                selected = _select_by_rules(candidates, context, shape)
                selected_by = "auto_single_candidate" if selected is not None else "llm"
                reason = "unique projection candidate" if selected is not None else "llm candidate selection"
                if selected is None and self.llm_selector is not None and _has_local_signal(context, shape):
                    llm_selected, raw_or_reason = _select_with_llm(
                        self.llm_selector,
                        question,
                        mapping,
                        candidates,
                        context,
                        shape,
                    )
                    llm_raw_output = raw_or_reason or llm_raw_output
                    if llm_selected is None:
                        unresolved.append(
                            _unresolved(
                                mapping,
                                "invalid_llm_binding",
                                raw_or_reason or "invalid llm binding",
                                candidates=tuple(sorted(candidates, key=lambda item: item.score, reverse=True)[:4]),
                            )
                        )
                        continue
                    selected = llm_selected
                    selected_by = "llm"
                    reason = "llm candidate selection"
                if selected is None:
                    unresolved.append(
                        _unresolved(
                            mapping,
                            "ambiguous_attribute_binding",
                            "binding candidates are not distinguishable",
                            candidates=tuple(sorted(candidates, key=lambda item: item.score, reverse=True)[:4]),
                        )
                    )
                    continue
                projections.append(_binding_item(mapping, "projection", candidates, selected, selected_by, reason))

        for mapping in _runtime_literal_mappings(
            question=question,
            unmatched_fragments=tuple(unmatched_fragments),
            ontology_mapping=ontology_mapping,
            nodes=nodes,
            intent_output=intent_output,
        ):
            filter_index += 1
            candidates = _value_candidates(mapping, nodes, filter_index)
            if not candidates:
                unresolved.append(
                    _unresolved(
                        mapping,
                        "missing_binding_candidate",
                        "no owner node for runtime literal",
                        no_option_reason="没有可用的绑定候选。",
                    )
                )
                continue
            selected = _select_by_rules(candidates, context, shape)
            item_kind = "metric_condition" if mapping.get("condition_scope") == "metric_condition" else "filter"
            item = _binding_item(mapping, item_kind, candidates, selected, "auto_single_candidate", "unique runtime literal candidate")
            if item_kind == "metric_condition":
                metric_conditions.append(item)
            else:
                filters.append(item)

        filter_level = "multi_predicate" if len(filters) > 1 else ("record_filter" if filters else "none")
        shape_updates = {
            "filter_level": InitialShapeField(
                value=filter_level,
                source="binding",
                decision="accept" if not any(item.get("blocking") for item in unresolved) else "clarify",
                confidence=1.0 if filters else 0.8,
                derived_from=tuple(str(item.result["value"]) for item in filters if "value" in item.result),
            )
        }
        quantifier_effects = _quantifier_effects_from_shape(shape)
        if quantifier_effects:
            shape_updates["quantifier_effects"] = InitialShapeField(
                value=quantifier_effects,
                source="binding.quantifier",
                decision="accept",
                confidence=1.0,
                derived_from=tuple(item["mention_id"] for item in quantifier_effects),
            )
        return BindingTrace(
            filters=tuple(filters),
            projections=tuple(projections),
            metric_conditions=tuple(metric_conditions),
            shape_updates=shape_updates,
            unresolved_items=tuple(unresolved),
            llm_raw_output=llm_raw_output,
        )


def _node_index(merged_nodes: Any) -> dict[str, str]:
    nodes: dict[str, str] = {}
    iterable = merged_nodes.get("nodes", []) if isinstance(merged_nodes, dict) else merged_nodes
    for item in iterable or []:
        if not isinstance(item, dict):
            continue
        class_id = item.get("class_id") or item.get("class") or item.get("type") or item.get("ontology_id")
        node_id = item.get("node_id") or item.get("id")
        if isinstance(class_id, str) and isinstance(node_id, str):
            nodes[class_id] = node_id
    return nodes


def _binding_mappings(ontology_mapping: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    evidence_index = _evidence_index(ontology_mapping)
    mappings: list[dict[str, Any]] = []
    for item in ontology_mapping.get("ontology_values", []):
        if not isinstance(item, dict):
            continue
        evidence = _first_evidence(item, evidence_index)
        value_ref_id = item.get("value_ref_id") or item.get("value_id") or item.get("ontology_id")
        ontology_id = item.get("ontology_id") or item.get("value_ontology_id") or item.get("value_id")
        mappings.append(
            {
                "mapping_id": value_ref_id,
                "mention_id": evidence.get("mention_id", ""),
                "mention_type": "VALUE",
                "surface": evidence.get("surface") or evidence.get("text") or "",
                "span": evidence.get("span", [0, 0]),
                "ontology_kind": "enum_value",
                "ontology_id": ontology_id,
                "raw_value": item.get("raw_value"),
                "constrains_attribute": item.get("constrains_attribute"),
                "evidence_refs": item.get("evidence_refs", []),
            }
        )
    for item in ontology_mapping.get("ontology_attributes", []):
        if not isinstance(item, dict):
            continue
        evidence = _first_evidence(item, evidence_index)
        attribute_ref_id = item.get("attribute_ref_id") or item.get("attribute_id") or item.get("ontology_id")
        ontology_id = item.get("ontology_id") or item.get("attribute_ontology_id") or item.get("attribute_id")
        attribute_candidates = item.get("attribute_candidates", [])
        if not attribute_candidates and isinstance(ontology_id, str) and ontology_id:
            attribute_candidates = [ontology_id]
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        mappings.append(
            {
                "mapping_id": attribute_ref_id,
                "mention_id": evidence.get("mention_id", ""),
                "mention_type": "ATTRIBUTE",
                "surface": evidence.get("surface") or evidence.get("text") or "",
                "span": evidence.get("span", [0, 0]),
                "ontology_kind": "attribute",
                "ontology_id": ontology_id,
                "parent_class": item.get("parent_class"),
                "attribute_candidates": attribute_candidates,
                "projection_distribution": item.get("projection_distribution"),
                "owner_scope": item.get("owner_scope"),
                "metadata": dict(metadata),
                "evidence_refs": item.get("evidence_refs", []),
            }
        )
    return tuple(mappings)


def _predicate_mappings(
    *,
    question: str,
    binding_mappings: tuple[dict[str, Any], ...],
    ontology_mapping: dict[str, Any],
    nodes: dict[str, str],
) -> tuple[tuple[dict[str, Any], ...], set[str]]:
    evidence = [dict(item) for item in ontology_mapping.get("evidence", []) if isinstance(item, dict)]
    operators = [item for item in evidence if item.get("mention_type") == "COMPARISON_OPERATOR"]
    predicate_values = [
        item for item in evidence if item.get("mention_type") in {"VALUE", "LITERAL_VALUE", "TIME_EXPRESSION"}
    ]
    attributes = [item for item in binding_mappings if item.get("mention_type") == "ATTRIBUTE"]
    mappings: list[dict[str, Any]] = []
    used_attribute_mentions: set[str] = set()
    for attribute_mapping in attributes:
        attr_start, attr_end = _span(attribute_mapping)
        operator = _nearest_structured_evidence(
            question,
            operators,
            start_at=attr_end,
            max_gap=4,
        )
        if operator is None:
            continue
        op_start, op_end = _span(operator)
        predicate_value = _nearest_structured_evidence(
            question,
            predicate_values,
            start_at=op_end,
            max_gap=4,
        )
        if predicate_value is None:
            continue
        used_attribute_mentions.add(str(attribute_mapping.get("mention_id") or ""))
        if predicate_value.get("mention_type") == "VALUE":
            continue
        attribute = _select_predicate_attribute(attribute_mapping, nodes)
        if attribute is None:
            continue
        raw_literal = str(predicate_value.get("surface") or (predicate_value.get("metadata") or {}).get("raw") or "")
        value_literal = _literal_for_attribute(raw_literal, attribute)
        if value_literal is None:
            continue
        mappings.append(
            {
                "mapping_id": f"PC{len(mappings) + 1}",
                "mention_id": str(attribute_mapping.get("mention_id") or ""),
                "mention_type": "VALUE",
                "surface": question[attr_start : _span(predicate_value)[1]],
                "span": [attr_start, _span(predicate_value)[1]],
                "ontology_kind": "literal_value",
                "literal_value": value_literal["parsed"],
                "raw_value": raw_literal,
                "parsed_value": value_literal["parsed"],
                "value_kind": "literal",
                "value_literal": value_literal,
                "operator": _operator_from_evidence(operator),
                "constrains_attribute": attribute,
                "evidence_refs": tuple(
                    ref
                    for ref in (
                        *attribute_mapping.get("evidence_refs", ()),
                        operator.get("evidence_id"),
                        predicate_value.get("evidence_id"),
                    )
                    if ref
                ),
                "composed_by": "predicate_assembly",
            }
        )
    return tuple(mappings), used_attribute_mentions


def _nearest_structured_evidence(
    question: str,
    evidence: list[dict[str, Any]],
    *,
    start_at: int,
    max_gap: int,
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for item in evidence:
        span_start, _ = _span(item)
        if span_start < start_at:
            continue
        if span_start - start_at > max_gap:
            continue
        if not _only_predicate_glue(question[start_at:span_start]):
            continue
        candidates.append(item)
    return min(candidates, key=lambda item: _span(item)[0], default=None)


def _only_predicate_glue(text: str) -> bool:
    return not text or bool(re.fullmatch(r"[\s的为是:：,，]*", text))


def _select_predicate_attribute(mapping: dict[str, Any], nodes: dict[str, str]) -> str | None:
    refs = _attribute_refs(mapping, {})
    available = [ref for ref in refs if "." in ref and ref.split(".", 1)[0] in nodes]
    if len(available) == 1:
        return available[0]
    parent_class = mapping.get("parent_class")
    if isinstance(parent_class, str):
        candidate = next((ref for ref in available if ref.startswith(f"{parent_class}.")), None)
        if candidate is not None:
            return candidate
    ontology_id = mapping.get("ontology_id")
    if isinstance(ontology_id, str) and ontology_id in available:
        return ontology_id
    return None


def _operator_from_evidence(evidence: dict[str, Any]) -> str:
    metadata = evidence.get("metadata")
    if isinstance(metadata, dict) and metadata.get("cypher_op"):
        return str(metadata["cypher_op"])
    return {
        "OP_EQ": "=",
        "OP_NE": "<>",
        "OP_GT": ">",
        "OP_GTE": ">=",
        "OP_LT": "<",
        "OP_LTE": "<=",
        "OP_BETWEEN": "BETWEEN",
    }.get(str(evidence.get("ontology_id") or ""), "=")


def _literal_for_attribute(raw_literal: str, attribute: str) -> dict[str, Any] | None:
    raw = raw_literal.strip()
    if not raw:
        return None
    numeric = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([A-Za-z%]+|毫秒|秒)?", raw)
    if numeric is not None:
        parsed_number: int | float = float(numeric.group(1))
        if parsed_number.is_integer():
            parsed_number = int(parsed_number)
        unit = numeric.group(2)
        attr_name = attribute.rsplit(".", 1)[-1]
        literal_type = "number"
        normalized_unit = unit
        if unit in {"ms", "毫秒"} or (unit is None and attr_name == "latency"):
            literal_type = "duration_ms"
            normalized_unit = "ms"
        elif unit in {"Mbps", "Gbps"} or (unit is None and attr_name == "bandwidth"):
            literal_type = "bandwidth_mbps"
            normalized_unit = unit or "Mbps"
            if unit == "Gbps":
                parsed_number = parsed_number * 1000
                if isinstance(parsed_number, float) and parsed_number.is_integer():
                    parsed_number = int(parsed_number)
                normalized_unit = "Mbps"
        elif unit == "%":
            literal_type = "percentage"
        return {
            "raw": raw,
            "parsed": parsed_number,
            "type": literal_type,
            **({"unit": normalized_unit} if normalized_unit else {}),
        }
    return {"raw": raw, "parsed": raw.strip("\"'“”‘’"), "type": "string"}


def _runtime_literal_mappings(
    *,
    question: str,
    unmatched_fragments: tuple[dict[str, Any], ...],
    ontology_mapping: dict[str, Any],
    nodes: dict[str, str],
    intent_output: IntentOutput,
) -> tuple[dict[str, Any], ...]:
    mappings: list[dict[str, Any]] = []
    for literal_index, fragment in enumerate(
        _runtime_literal_sources(
            question=question,
            unmatched_fragments=unmatched_fragments,
            ontology_mapping=ontology_mapping,
        ),
        start=1,
    ):
        literal = str(fragment["surface"])
        span = fragment["span"]
        owner = _nearest_role_condition_owner(question, int(span[0]), ontology_mapping, nodes)
        if owner is None:
            continue
        owner_class, evidence_refs = owner
        attribute = _runtime_literal_attribute(owner_class, literal)
        if attribute is None:
            continue
        mappings.append(
            {
                "mapping_id": f"RL{literal_index}",
                "mention_id": f"runtime_literal_{literal_index}",
                "mention_type": "VALUE",
                "surface": literal,
                "span": [int(span[0]), int(span[1])],
                "ontology_kind": "literal_value",
                "literal_value": literal,
                "raw_value": literal,
                "constrains_attribute": attribute,
                "evidence_refs": evidence_refs,
                "condition_scope": "metric_condition" if _is_metric_condition_scope(intent_output) else "filter",
            }
        )
    return tuple(mappings)


def _runtime_literal_sources(
    *,
    question: str,
    unmatched_fragments: tuple[dict[str, Any], ...],
    ontology_mapping: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    fragments: list[dict[str, Any]] = list(_runtime_literal_fragments(question, unmatched_fragments))
    seen_spans = {
        (int(fragment["span"][0]), int(fragment["span"][1]))
        for fragment in fragments
        if isinstance(fragment.get("span"), (list, tuple)) and len(fragment["span"]) == 2
    }
    for item in ontology_mapping.get("evidence", []):
        if not isinstance(item, dict) or item.get("mention_type") != "LITERAL_VALUE":
            continue
        surface = str(item.get("surface") or "")
        span = item.get("span")
        if not surface or not isinstance(span, (list, tuple)) or len(span) != 2:
            continue
        span_key = (int(span[0]), int(span[1]))
        if span_key in seen_spans or not _is_runtime_literal_value(surface):
            continue
        fragments.append({"surface": surface, "span": [span_key[0], span_key[1]]})
        seen_spans.add(span_key)
    return tuple(fragments)


def _runtime_literal_fragments(question: str, unmatched_fragments: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    fragments: list[dict[str, Any]] = []
    for fragment in unmatched_fragments:
        if not isinstance(fragment, dict):
            continue
        surface = str(fragment.get("surface") or "")
        span = fragment.get("span")
        if not isinstance(span, (list, tuple)) or len(span) != 2:
            continue
        if _is_runtime_literal_value(surface):
            fragments.append({"surface": surface, "span": [int(span[0]), int(span[1])]})
    if fragments:
        return tuple(fragments)
    return tuple(
        {"surface": match.group(0), "span": [match.start(), match.end()]}
        for match in re.finditer(r"\b[A-Za-z][A-Za-z0-9]+_[A-Za-z0-9_]+\b", question)
    )


def _nearest_role_condition_owner(
    question: str,
    literal_start: int,
    ontology_mapping: dict[str, Any],
    nodes: dict[str, str],
) -> tuple[str, list[str]] | None:
    best: tuple[int, str, list[str]] | None = None
    evidence_by_id = _evidence_index(ontology_mapping)
    for hint in ontology_mapping.get("ontology_relation_hints", []):
        if not isinstance(hint, dict) or not hint.get("role"):
            continue
        owner_class = str(hint.get("to_class") or hint.get("target_class") or "")
        if not owner_class or owner_class not in nodes:
            continue
        refs = [str(ref) for ref in hint.get("evidence_refs", []) if ref]
        evidence = next((evidence_by_id.get(ref) for ref in refs if evidence_by_id.get(ref)), None)
        if evidence is None:
            continue
        span = evidence.get("span")
        if not isinstance(span, (list, tuple)) or len(span) != 2:
            continue
        evidence_end = int(span[1])
        if evidence_end > literal_start:
            continue
        between = question[evidence_end:literal_start]
        if not re.search(r"(?:为|是|等于|=|:|：)\s*$", between):
            continue
        distance = literal_start - evidence_end
        if best is None or distance < best[0]:
            best = (distance, owner_class, refs)
    if best is None:
        return None
    return best[1], best[2]


def _runtime_literal_attribute(owner_class: str, literal: str) -> str | None:
    value = literal.strip().strip("\"'“”‘’")
    if value.startswith(f"{owner_class}_"):
        return f"{owner_class}.id"
    if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", value):
        return f"{owner_class}.ip_address"
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", value):
        return f"{owner_class}.id"
    return None


def _is_runtime_literal_value(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    if any(char in text for char in "\"'“”‘’"):
        return True
    if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", text):
        return True
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9]+_[A-Za-z0-9_]+", text):
        return True
    if re.fullmatch(r"\d{4}[-/年]\d{1,2}(?:[-/月]\d{1,2}日?)?", text):
        return True
    if re.fullmatch(r"\d+(?:\.\d+)?(?:%|[A-Za-z]+|[个条次台])?", text):
        return True
    return False


def _is_metric_condition_scope(intent_output: IntentOutput) -> bool:
    return (
        intent_output.intent.primary == "breakdown_query"
        and intent_output.intent.secondary == "multi_metric_breakdown_query"
    )


def _evidence_index(ontology_mapping: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("evidence_id")): dict(item)
        for item in ontology_mapping.get("evidence", [])
        if isinstance(item, dict) and item.get("evidence_id")
    }


def _first_evidence(item: dict[str, Any], evidence_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    refs = item.get("evidence_refs")
    if isinstance(refs, (list, tuple)):
        for ref in refs:
            evidence = evidence_index.get(str(ref))
            if evidence is not None:
                return evidence
    return {}


def _value_candidates(mapping: dict[str, Any], nodes: dict[str, str], index: int) -> tuple[BindingCandidate, ...]:
    attribute = mapping.get("constrains_attribute") or mapping.get("constrains_field")
    if not isinstance(attribute, str) or "." not in attribute:
        return ()
    owner_class = attribute.split(".", 1)[0]
    owner_node = nodes.get(owner_class)
    if owner_node is None:
        return ()
    span_start, span_end = _span(mapping)
    value_kind = str(mapping.get("value_kind") or ("literal" if mapping.get("ontology_kind") == "literal_value" else "enum"))
    value_id = str(mapping.get("ontology_id") or mapping.get("value_id") or "") if value_kind == "enum" else None
    if "parsed_value" in mapping:
        value = mapping.get("parsed_value")
    elif value_kind == "enum":
        value = mapping.get("raw_value") or mapping.get("literal_value") or mapping.get("ontology_id") or mapping.get("value_id")
    else:
        value = mapping.get("literal_value") or mapping.get("raw_value")
    value_literal = mapping.get("value_literal")
    evidence_refs = tuple(str(ref) for ref in mapping.get("evidence_refs", []) if ref)
    return (
        BindingCandidate(
            candidate_id=f"bc_filter_{index}",
            kind="filter",
            mapping_id=str(mapping.get("mapping_id", "")),
            mention_id=str(mapping.get("mention_id", "")),
            surface=str(mapping.get("surface", "")),
            span_start=span_start,
            span_end=span_end,
            attribute=attribute,
            owner_node=owner_node,
            owner_class=owner_class,
            score=150,
            evidence_ids=evidence_refs,
            evidence=("constrains_attribute", "owner_node_exists"),
            value=value,
            operator=str(mapping.get("operator") or "equals"),
            value_kind=value_kind,
            value_id=value_id or None,
            value_literal=dict(value_literal) if isinstance(value_literal, dict) else None,
        ),
    )


def _attribute_candidates(
    mapping: dict[str, Any],
    nodes: dict[str, str],
    candidate_family: dict[str, Any],
    context_signals: tuple[ContextSignal, ...],
    shape_signals: tuple[ContextSignal, ...],
    intent_output: IntentOutput,
    start_index: int,
    path_owner_scope: tuple[str, ...],
) -> tuple[tuple[BindingCandidate, ...], int]:
    projection_owner_context = _projection_owner_context(mapping, nodes, context_signals, path_owner_scope)
    refs = _attribute_refs(mapping, candidate_family)
    refs = _refs_with_projection_owner_type(refs, nodes, projection_owner_context)
    single = len(refs) == 1
    candidates: list[BindingCandidate] = []
    for attribute in refs:
        if "." not in attribute:
            continue
        owner_class = attribute.split(".", 1)[0]
        owner_node = nodes.get(owner_class)
        if owner_node is None:
            continue
        start_index += 1
        score, evidence_ids, evidence = _score_attribute_candidate(
            mapping,
            attribute,
            owner_class,
            single,
            context_signals,
            shape_signals,
            intent_output,
            projection_owner_context,
        )
        span_start, span_end = _span(mapping)
        candidates.append(
            BindingCandidate(
                candidate_id=f"bc_projection_{start_index}",
                kind="projection",
                mapping_id=str(mapping.get("mapping_id", "")),
                mention_id=str(mapping.get("mention_id", "")),
                surface=str(mapping.get("surface", "")),
                span_start=span_start,
                span_end=span_end,
                attribute=attribute,
                owner_node=owner_node,
                owner_class=owner_class,
                score=score,
                evidence_ids=tuple(evidence_ids),
                evidence=tuple(evidence),
            )
        )
    return tuple(candidates), start_index


def _attribute_refs(mapping: dict[str, Any], candidate_family: dict[str, Any]) -> tuple[str, ...]:
    for key in ("attribute_candidates", "candidate_refs"):
        value = mapping.get(key)
        if isinstance(value, (list, tuple)) and value:
            return tuple(str(item) for item in value)
    mention_id = mapping.get("mention_id")
    family_refs = candidate_family.get(str(mention_id)) if mention_id is not None else None
    if isinstance(family_refs, (list, tuple)) and family_refs:
        return tuple(str(item) for item in family_refs)
    ontology_id = mapping.get("ontology_id")
    return (str(ontology_id),) if ontology_id else ()


def _refs_with_projection_owner_type(
    refs: tuple[str, ...],
    nodes: dict[str, str],
    projection_owner_context: dict[str, str],
) -> tuple[str, ...]:
    if not any(ref.endswith(".elem_type") for ref in refs):
        return refs
    result = list(refs)
    for owner_class in projection_owner_context:
        if owner_class not in nodes:
            continue
        candidate = f"{owner_class}.elem_type"
        if candidate not in result:
            result.append(candidate)
    return tuple(result)


def _projection_owner_context(
    mapping: dict[str, Any],
    nodes: dict[str, str],
    context_signals: tuple[ContextSignal, ...],
    path_owner_scope: tuple[str, ...],
) -> dict[str, str]:
    surface = str(mapping.get("surface") or "")
    span_start, span_end = _span(mapping)
    owners: dict[str, str] = _distribution_projection_owner_context(mapping, nodes, path_owner_scope)
    if not owners:
        owners = _both_sides_projection_owner_context(mapping, nodes, context_signals)
    for signal in context_signals:
        if signal.signal_type != "PROXIMAL_MODIFIER":
            continue
        if signal.span_start > span_start or signal.span_end < span_end:
            continue
        if surface and surface not in signal.text:
            continue
        if "的" not in signal.text:
            continue
        subject, projection_tail = signal.text.split("的", 1)
        if surface and surface in projection_tail:
            before_surface = projection_tail.split(surface, 1)[0]
            if _has_intermediate_owner(before_surface):
                continue
        for class_id in nodes:
            if class_id not in signal.supports:
                continue
            if _subject_mentions_class(subject, class_id):
                owners[class_id] = signal.signal_id
    return owners


def _distribution_projection_owner_context(
    mapping: dict[str, Any],
    nodes: dict[str, str],
    path_owner_scope: tuple[str, ...],
) -> dict[str, str]:
    distribution = str(mapping.get("projection_distribution") or "")
    if distribution not in {"each_owner", "each_endpoint", "pairwise"}:
        return {}
    owner_scope = mapping.get("owner_scope")
    if not isinstance(owner_scope, (list, tuple)) or not owner_scope:
        owner_scope = path_owner_scope
    owners: dict[str, str] = {}
    for raw_class_id in owner_scope:
        class_id = str(raw_class_id)
        if class_id in nodes:
            owners[class_id] = "mapping.owner_scope"
    return owners


def _both_sides_projection_owner_context(
    mapping: dict[str, Any],
    nodes: dict[str, str],
    context_signals: tuple[ContextSignal, ...],
) -> dict[str, str]:
    if not _is_elem_type_projection_mapping(mapping):
        return {}
    span_start, span_end = _span(mapping)
    return_signals = [
        signal
        for signal in context_signals
        if signal.signal_type == "QUESTION_FRAMING_ATOM"
        and "RETURN_CONTENT" in signal.supports
        and signal.span_start <= span_start
        and span_end <= signal.span_end
        and _mentions_both_sides(signal.text)
    ]
    if not return_signals:
        return {}
    path_signals = [
        signal
        for signal in context_signals
        if signal.signal_type == "QUESTION_FRAMING_ATOM" and "RELATION_PATH" in signal.supports
    ]
    if not path_signals:
        return {}
    evidence_id = return_signals[0].signal_id
    owners: dict[str, str] = {}
    for class_id in nodes:
        if any(_text_mentions_class(signal.text, class_id) for signal in path_signals):
            owners[class_id] = evidence_id
    return owners


def _is_elem_type_projection_mapping(mapping: dict[str, Any]) -> bool:
    refs: list[str] = []
    for key in ("ontology_id", "attribute_id"):
        value = mapping.get(key)
        if isinstance(value, str):
            refs.append(value)
    for key in ("attribute_candidates", "candidate_refs"):
        value = mapping.get(key)
        if isinstance(value, (list, tuple)):
            refs.extend(str(item) for item in value)
    return any(ref.endswith(".elem_type") for ref in refs) or "类型" in str(mapping.get("surface") or "")


def _mentions_both_sides(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    return any(token in compact for token in ("双方", "两端", "两侧", "两者", "二者"))


def _text_mentions_class(text: str, class_id: str) -> bool:
    aliases = {
        "Service": ("服务", "业务"),
        "Tunnel": ("隧道",),
        "NetworkElement": ("源网元", "目的网元", "网元", "设备"),
        "Port": ("端口", "接口"),
        "Protocol": ("协议",),
        "Fiber": ("光纤",),
        "Link": ("链路",),
    }.get(class_id, (class_id,))
    return any(alias in text for alias in aliases)


def _has_intermediate_owner(text: str) -> bool:
    return any(
        token in text
        for token in (
            "源网元",
            "目的网元",
            "网元",
            "设备",
            "端口",
            "接口",
            "隧道",
            "链路",
            "光纤",
            "协议",
        )
    )


def _subject_mentions_class(subject: str, class_id: str) -> bool:
    normalized = subject.strip().strip("所有全部各个每个这些那些")
    aliases = {
        "Service": ("服务", "业务"),
        "Tunnel": ("隧道",),
        "NetworkElement": ("源网元", "目的网元", "网元", "设备"),
        "Port": ("端口", "接口"),
        "Protocol": ("协议",),
        "Fiber": ("光纤",),
        "Link": ("链路",),
    }.get(class_id, (class_id,))
    return any(normalized.endswith(alias) for alias in aliases)


def _score_attribute_candidate(
    mapping: dict[str, Any],
    attribute: str,
    owner_class: str,
    single: bool,
    context_signals: tuple[ContextSignal, ...],
    shape_signals: tuple[ContextSignal, ...],
    intent_output: IntentOutput,
    projection_owner_context: dict[str, str],
) -> tuple[int, list[str], list[str]]:
    score = 0
    evidence_ids: list[str] = [str(ref) for ref in mapping.get("evidence_refs", []) if ref]
    evidence: list[str] = []
    if single:
        score += 100
        evidence.append("single_ontology_candidate")
    score += 60
    evidence.append("parent_class_owner_node_exists")
    if mapping.get("parent_class") == owner_class:
        score += 20
        evidence.append("parent_class_match")
    if _in_projection_region(mapping, shape_signals):
        score += 20
        evidence.append("projection_region")
    for signal in (*context_signals, *shape_signals):
        if _signal_supports(signal, attribute, owner_class, ""):
            score += 30
            evidence_ids.append(signal.signal_id)
            evidence.append(signal.signal_type)
            break
    if _shape_mentions_attribute(intent_output, attribute):
        score += 30
        evidence.append("intent_shape_field")
    if owner_class in projection_owner_context:
        score += 120
        evidence_ids.append(projection_owner_context[owner_class])
        evidence.append("projection_owner_context")
    return score, evidence_ids, evidence


def _select_by_rules(
    candidates: tuple[BindingCandidate, ...],
    context_signals: tuple[ContextSignal, ...],
    shape_signals: tuple[ContextSignal, ...],
) -> BindingCandidate | None:
    del context_signals, shape_signals
    projection_owner_candidates = [
        item for item in candidates if "projection_owner_context" in item.evidence and item.owner_node
    ]
    if len(projection_owner_candidates) == 1:
        return projection_owner_candidates[0]
    if len(candidates) == 1 and candidates[0].owner_node:
        return candidates[0]
    return None


def _select_many_by_rules(candidates: tuple[BindingCandidate, ...]) -> tuple[BindingCandidate, ...]:
    projection_owner_candidates = tuple(
        item
        for item in candidates
        if "projection_owner_context" in item.evidence
        and item.owner_node
    )
    if len(projection_owner_candidates) <= 1:
        return ()
    return projection_owner_candidates


def _select_with_llm(
    llm_selector: object,
    question: str,
    mapping: dict[str, Any],
    candidates: tuple[BindingCandidate, ...],
    context_signals: tuple[ContextSignal, ...],
    shape_signals: tuple[ContextSignal, ...],
) -> tuple[BindingCandidate | None, str]:
    narrowed = tuple(sorted(candidates, key=lambda item: item.score, reverse=True)[:4])
    variables = {
        "question": question,
        "surface": str(mapping.get("surface", "")),
        "span_start": _span(mapping)[0],
        "span_end": _span(mapping)[1],
        "binding_candidate_list_with_ids": _candidate_prompt_lines(narrowed),
        "signal_list_with_ids": _signal_prompt_lines((*context_signals, *shape_signals), narrowed),
        "allowed_candidate_ids": [item.candidate_id for item in narrowed],
        "allowed_signal_ids": [item.signal_id for item in (*context_signals, *shape_signals)],
    }
    result = llm_selector.select("binding_selection", variables)
    raw = str(getattr(result, "raw_response", ""))
    parsed = getattr(result, "parsed", None)
    if not isinstance(parsed, dict):
        try:
            parsed = _parse_first_json_object(raw)
        except BindingValidationError:
            parsed = _parse_binding_selection_text(raw)
    try:
        selected_id = _validate_llm_output(parsed, raw, narrowed)
    except BindingValidationError as exc:
        return None, str(exc)
    selected = next(item for item in narrowed if item.candidate_id == selected_id)
    return selected, raw


def _validate_llm_output(
    parsed: dict[str, Any],
    raw: str,
    candidates: tuple[BindingCandidate, ...],
) -> str:
    if parsed.get("decision") != "accept":
        raise BindingValidationError(str(parsed.get("reason") or "llm requested clarification"))
    candidate_id = str(parsed.get("candidate_id"))
    candidate = next((item for item in candidates if item.candidate_id == candidate_id), None)
    if candidate is None:
        raise BindingValidationError(f"unknown candidate_id: {candidate_id}")
    if not raw:
        raise BindingValidationError("missing llm_raw_output")
    return candidate_id


def _binding_item(
    mapping: dict[str, Any],
    kind: str,
    candidates: tuple[BindingCandidate, ...],
    selected: BindingCandidate,
    selected_by: str,
    reason: str,
) -> BindingItem:
    if kind in {"filter", "metric_condition"}:
        result = {
            "node": selected.owner_node,
            "attribute": selected.attribute,
            "operator": selected.operator,
            "value": selected.value,
        }
        if selected.value_kind is not None:
            result["value_kind"] = selected.value_kind
        if selected.value_id is not None:
            result["value_id"] = selected.value_id
        if selected.value_literal is not None:
            result["value_literal"] = dict(selected.value_literal)
    else:
        attribute = _projection_attribute(selected)
        result = {
            "node": selected.owner_node,
            "attribute": attribute,
            "alias": _projection_alias(attribute),
        }
    return BindingItem(
        item=f"{mapping.get('surface', '')}@{selected.span_start}-{selected.span_end}",
        kind=kind,
        candidates=(selected,) if kind == "projection" and selected_by == "auto_single_candidate" else candidates,
        selected=selected.candidate_id,
        decision="accept",
        result=result,
        evidence_ids=selected.evidence_ids,
        selected_by=selected_by,
        reason=reason,
    )


def _projection_attribute(selected: BindingCandidate) -> str:
    owner, attr = selected.attribute.split(".", 1)
    if attr == "id" and _is_internal_id_surface(selected.surface):
        return f"{owner}.__internal_id"
    return selected.attribute


def _is_internal_id_surface(surface: str) -> bool:
    text = surface.replace(" ", "")
    return "内部ID" in text or "内部id" in text


def _projection_alias(attribute: str) -> str:
    owner, attr = attribute.split(".", 1)
    if attr == "__internal_id":
        return "id"
    prefix = {"Service": "service", "Tunnel": "tunnel", "NetworkElement": "source_ne", "Port": "port", "Protocol": "protocol"}.get(
        owner, owner.lower()
    )
    return f"{prefix}_{attr}"


def _in_projection_region(mapping: dict[str, Any], shape_signals: tuple[ContextSignal, ...]) -> bool:
    span_start, _ = _span(mapping)
    for signal in shape_signals:
        if signal.span_end <= span_start and {"answer_projection_region", "projection_region", "return_field"}.intersection(signal.supports):
            return True
    return False


def _shape_mentions_attribute(intent_output: IntentOutput, attribute: str) -> bool:
    for value in intent_output.initial_shape.values():
        payload = value.value
        if payload == attribute:
            return True
        if isinstance(payload, (list, tuple, set)) and attribute in payload:
            return True
    return False


def _has_local_signal(context_signals: tuple[ContextSignal, ...], shape_signals: tuple[ContextSignal, ...]) -> bool:
    return bool(context_signals or shape_signals)


def _quantifier_effects_from_shape(shape_signals: tuple[ContextSignal, ...]) -> list[dict[str, Any]]:
    effects: list[dict[str, Any]] = []
    for signal in shape_signals:
        supports = tuple(str(value) for value in signal.supports)
        if "quantifier" not in supports:
            continue
        canonical_id = next((value for value in supports if value.startswith("QUANT_")), "")
        if not canonical_id:
            continue
        semantic = next(
            (value for value in ("no_implicit_filter", "not_exists", "existential_scope") if value in supports),
            "",
        )
        effects.append(
            {
                "mention_id": signal.signal_id,
                "canonical_id": canonical_id,
                "semantic": semantic,
                "affects_intent": "affects_intent" in supports,
            }
        )
    return effects


def _signal_supports(signal: ContextSignal, attribute: str, owner_class: str, candidate_id: str) -> bool:
    supports = set(signal.supports)
    return bool(
        (candidate_id and candidate_id in supports)
        or attribute in supports
        or owner_class in supports
        or attribute.split(".", 1)[-1] in supports
    )


def _candidate_prompt_lines(candidates: tuple[BindingCandidate, ...]) -> str:
    return "\n".join(
        f"{item.candidate_id}: {item.kind} {item.surface}@{item.span_start}-{item.span_end} "
        f"-> node={item.owner_node}, owner={item.owner_class}, attribute={item.attribute}, score={item.score}"
        for item in candidates
    )


def _signal_prompt_lines(signals: tuple[ContextSignal, ...], candidates: tuple[BindingCandidate, ...]) -> str:
    lines: list[str] = []
    for signal in signals:
        supported = [
            item.candidate_id
            for item in candidates
            if _signal_supports(signal, item.attribute, item.owner_class, item.candidate_id)
        ]
        if supported:
            lines.append(
                f"{signal.signal_id}: {signal.signal_type} text={signal.text} span={signal.span_start}-{signal.span_end} "
                f"supports={','.join(supported)}"
            )
    return "\n".join(lines) or "无"


def _parse_first_json_object(raw_response: str) -> dict[str, Any]:
    start = raw_response.find("{")
    if start < 0:
        raise BindingValidationError("response does not contain JSON object")
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(raw_response)):
        char = raw_response[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                parsed = json.loads(raw_response[start : index + 1])
                if not isinstance(parsed, dict):
                    raise BindingValidationError("JSON output must be an object")
                return parsed
    raise BindingValidationError("response JSON object is incomplete")


def _parse_binding_selection_text(raw_response: str) -> dict[str, Any]:
    for line in raw_response.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("需要澄清"):
            reason = line.split("：", 1)[1].strip() if "：" in line else line.removeprefix("需要澄清").strip(" :：")
            return {"decision": "clarify", "candidate_id": None, "reason": reason or "绑定候选不足以判断。"}
        match = re.search(r"选择\s*([A-Za-z0-9_]+)\s*(?:[。.]|[：:])?\s*理由\s*[：:]\s*(.*)", line)
        if match:
            return {"decision": "accept", "candidate_id": match.group(1), "reason": match.group(2).strip()}
        raise BindingValidationError(f"unrecognized binding selection line: {line}")
    raise BindingValidationError("binding selection output is empty")


def _span(mapping: dict[str, Any]) -> tuple[int, int]:
    span = mapping.get("span")
    if isinstance(span, (list, tuple)) and len(span) == 2:
        return int(span[0]), int(span[1])
    return int(mapping.get("span_start", 0)), int(mapping.get("span_end", 0))


def _unresolved(
    mapping: dict[str, Any],
    reason_code: str,
    reason: str,
    *,
    candidates: tuple[BindingCandidate, ...] = (),
    no_option_reason: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": f"u_{mapping.get('mapping_id', mapping.get('mention_id', 'binding'))}",
        "source_stage": "step_3_5",
        "reason_code": reason_code,
        "suggested_error_type": "ClarificationNeeded",
        "blocking": True,
        "surface": mapping.get("surface"),
        "span": list(_span(mapping)),
        "message": reason,
        "reason": reason,
    }
    options = _binding_clarification_options(candidates)
    if options:
        payload["options"] = options
    else:
        payload["options"] = []
        payload["no_option_reason"] = no_option_reason or "没有可用的固定绑定候选。"
    return payload


def _binding_clarification_options(candidates: tuple[BindingCandidate, ...]) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    for candidate in candidates:
        label = _binding_clarification_label(candidate)
        options.append({"option_id": candidate.candidate_id, "label": label})
    return options


def _binding_clarification_label(candidate: BindingCandidate) -> str:
    owner = candidate.owner_class
    attr = candidate.attribute
    if "." in candidate.attribute:
        owner_from_attr, attr = candidate.attribute.split(".", 1)
        owner = owner or owner_from_attr
    owner_label = _binding_class_label(owner)
    attr_label = _binding_attribute_label(attr, candidate.surface)
    if owner_label and attr_label:
        return f"{owner_label}的{attr_label}"
    return f"{candidate.surface} -> {candidate.attribute}"


def _binding_class_label(class_id: str) -> str:
    return {
        "Service": "服务",
        "Tunnel": "隧道",
        "NetworkElement": "网元",
        "Port": "端口",
        "Fiber": "光纤",
        "Link": "链路",
        "Protocol": "协议",
    }.get(class_id, class_id)


def _binding_attribute_label(attribute: str, surface: str) -> str:
    surface_text = surface.strip()
    return {
        "name": "名称",
        "latency": "延迟",
        "delay": "延迟",
        "id": "ID",
        "__internal_id": "内部ID",
        "element_type": "类型",
        "type": "类型",
        "standard": "标准",
        "ietf_standard": "标准",
    }.get(attribute, surface_text or attribute)
