from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .models import ContextSignal, IntentTrace, ShapeField


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

    def to_dict(self) -> dict[str, Any]:
        return {
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
        }


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
    shape_updates: dict[str, ShapeField]
    unresolved_items: tuple[dict[str, Any], ...]
    llm_raw_output: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "filters": [item.to_dict() for item in self.filters],
            "projections": [item.to_dict() for item in self.projections],
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
        intent_trace: IntentTrace,
        question: str,
    ) -> BindingTrace:
        nodes = _node_index(merged_nodes)
        family = candidate_family or {}
        context = tuple(context_signals)
        shape = tuple(shape_signals)
        filters: list[BindingItem] = []
        projections: list[BindingItem] = []
        unresolved: list[dict[str, Any]] = []
        llm_raw_output: str | None = None
        filter_index = 0
        projection_index = 0

        for mapping in ontology_mapping.get("mapped_mentions", []):
            if not isinstance(mapping, dict):
                continue
            kind = str(mapping.get("ontology_kind", ""))
            mention_type = str(mapping.get("mention_type", ""))
            if mention_type == "VALUE" or kind in {"enum_value", "literal_value"}:
                filter_index += 1
                candidates = _value_candidates(mapping, nodes, filter_index)
                if not candidates:
                    unresolved.append(_unresolved(mapping, "missing_binding_candidate", "no owner node for constrained attribute"))
                    continue
                selected = _select_by_rules(candidates, context, shape)
                filters.append(_binding_item(mapping, "filter", candidates, selected, "rule", "VALUE constrains_attribute"))
            elif mention_type == "ATTRIBUTE" or kind == "attribute":
                candidates, projection_index = _attribute_candidates(
                    mapping,
                    nodes,
                    family,
                    context,
                    shape,
                    intent_trace,
                    projection_index,
                )
                if not candidates:
                    unresolved.append(_unresolved(mapping, "missing_binding_candidate", "no owner node for attribute candidate"))
                    continue
                selected = _select_by_rules(candidates, context, shape)
                selected_by = "rule"
                reason = "binding score"
                if selected is None and self.llm_selector is not None and _has_local_signal(context, shape):
                    llm_selected, raw_or_reason = _select_with_llm(
                        self.llm_selector,
                        question,
                        mapping,
                        candidates,
                        context,
                        shape,
                    )
                    llm_raw_output = raw_or_reason if raw_or_reason and raw_or_reason.lstrip().startswith("{") else llm_raw_output
                    if llm_selected is None:
                        unresolved.append(_unresolved(mapping, "invalid_llm_binding", raw_or_reason or "invalid llm binding"))
                        continue
                    selected = llm_selected
                    selected_by = "llm"
                    reason = "llm candidate selection"
                if selected is None:
                    unresolved.append(_unresolved(mapping, "ambiguous_attribute_binding", "binding candidates are not distinguishable"))
                    continue
                projections.append(_binding_item(mapping, "projection", candidates, selected, selected_by, reason))

        shape_updates = {
            "filter_level": ShapeField(
                value="record_filter" if filters else "none",
                source="binding",
                decision="accept" if not any(item.get("blocking") for item in unresolved) else "clarify",
                confidence=1.0 if filters else 0.8,
                derived_from=tuple(item.result["value"] for item in filters if "value" in item.result),
            )
        }
        return BindingTrace(
            filters=tuple(filters),
            projections=tuple(projections),
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


def _value_candidates(mapping: dict[str, Any], nodes: dict[str, str], index: int) -> tuple[BindingCandidate, ...]:
    attribute = mapping.get("constrains_attribute") or mapping.get("constrains_field")
    if not isinstance(attribute, str) or "." not in attribute:
        return ()
    owner_class = attribute.split(".", 1)[0]
    owner_node = nodes.get(owner_class)
    if owner_node is None:
        return ()
    span_start, span_end = _span(mapping)
    value = mapping.get("ontology_id") or mapping.get("literal_value") or mapping.get("raw_value")
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
            evidence_ids=(),
            evidence=("constrains_attribute", "owner_node_exists"),
            value=value,
        ),
    )


def _attribute_candidates(
    mapping: dict[str, Any],
    nodes: dict[str, str],
    candidate_family: dict[str, Any],
    context_signals: tuple[ContextSignal, ...],
    shape_signals: tuple[ContextSignal, ...],
    intent_trace: IntentTrace,
    start_index: int,
) -> tuple[tuple[BindingCandidate, ...], int]:
    refs = _attribute_refs(mapping, candidate_family)
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
            intent_trace,
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


def _score_attribute_candidate(
    mapping: dict[str, Any],
    attribute: str,
    owner_class: str,
    single: bool,
    context_signals: tuple[ContextSignal, ...],
    shape_signals: tuple[ContextSignal, ...],
    intent_trace: IntentTrace,
) -> tuple[int, list[str], list[str]]:
    score = 0
    evidence_ids: list[str] = []
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
    if _shape_mentions_attribute(intent_trace, attribute):
        score += 30
        evidence.append("intent_shape_field")
    return score, evidence_ids, evidence


def _select_by_rules(
    candidates: tuple[BindingCandidate, ...],
    context_signals: tuple[ContextSignal, ...],
    shape_signals: tuple[ContextSignal, ...],
) -> BindingCandidate | None:
    if len(candidates) == 1 and candidates[0].owner_node:
        return candidates[0]
    ordered = sorted(candidates, key=lambda item: item.score, reverse=True)
    if ordered and ordered[0].score >= 80 and (len(ordered) == 1 or ordered[0].score - ordered[1].score >= 20):
        return ordered[0]
    supported = [
        candidate
        for candidate in candidates
        if any(_signal_supports(signal, candidate.attribute, candidate.owner_class, candidate.candidate_id) for signal in (*context_signals, *shape_signals))
    ]
    if len(supported) == 1 and supported[0].score >= 80:
        return supported[0]
    return None


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
        parsed = _parse_first_json_object(raw)
    try:
        selected_id, signal_id = _validate_llm_output(parsed, raw, mapping, narrowed, (*context_signals, *shape_signals))
    except BindingValidationError as exc:
        return None, str(exc)
    selected = next(item for item in narrowed if item.candidate_id == selected_id)
    return selected, raw


def _validate_llm_output(
    parsed: dict[str, Any],
    raw: str,
    mapping: dict[str, Any],
    candidates: tuple[BindingCandidate, ...],
    signals: tuple[ContextSignal, ...],
) -> tuple[str, str]:
    if parsed.get("decision") != "accept":
        raise BindingValidationError(str(parsed.get("reason") or "llm requested clarification"))
    candidate_id = str(parsed.get("candidate_id"))
    signal_id = str(parsed.get("signal_id"))
    candidate = next((item for item in candidates if item.candidate_id == candidate_id), None)
    if candidate is None:
        raise BindingValidationError(f"unknown candidate_id: {candidate_id}")
    signal = next((item for item in signals if item.signal_id == signal_id), None)
    if signal is None:
        raise BindingValidationError(f"unknown signal_id: {signal_id}")
    if not _signal_supports(signal, candidate.attribute, candidate.owner_class, candidate.candidate_id):
        raise BindingValidationError(f"signal {signal_id} does not support candidate {candidate_id}")
    span_start, span_end = _span(mapping)
    if parsed.get("span_start") != span_start or parsed.get("span_end") != span_end:
        raise BindingValidationError("span_start/span_end do not match bound mention")
    if not raw:
        raise BindingValidationError("missing llm_raw_output")
    return candidate_id, signal_id


def _binding_item(
    mapping: dict[str, Any],
    kind: str,
    candidates: tuple[BindingCandidate, ...],
    selected: BindingCandidate,
    selected_by: str,
    reason: str,
) -> BindingItem:
    if kind == "filter":
        result = {
            "node": selected.owner_node,
            "attribute": selected.attribute,
            "operator": "equals",
            "value": selected.value,
        }
    else:
        result = {
            "node": selected.owner_node,
            "attribute": selected.attribute,
            "alias": _projection_alias(selected.attribute),
        }
    return BindingItem(
        item=f"{mapping.get('surface', '')}@{selected.span_start}-{selected.span_end}",
        kind=kind,
        candidates=(selected,) if kind == "projection" and selected_by == "rule" else candidates,
        selected=selected.candidate_id,
        decision="accept",
        result=result,
        evidence_ids=selected.evidence_ids,
        selected_by=selected_by,
        reason=reason,
    )


def _projection_alias(attribute: str) -> str:
    owner, attr = attribute.split(".", 1)
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


def _shape_mentions_attribute(intent_trace: IntentTrace, attribute: str) -> bool:
    for value in intent_trace.shape.values():
        payload = value.value
        if payload == attribute:
            return True
        if isinstance(payload, (list, tuple, set)) and attribute in payload:
            return True
    return False


def _has_local_signal(context_signals: tuple[ContextSignal, ...], shape_signals: tuple[ContextSignal, ...]) -> bool:
    return bool(context_signals or shape_signals)


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


def _span(mapping: dict[str, Any]) -> tuple[int, int]:
    span = mapping.get("span")
    if isinstance(span, (list, tuple)) and len(span) == 2:
        return int(span[0]), int(span[1])
    return int(mapping.get("span_start", 0)), int(mapping.get("span_end", 0))


def _unresolved(mapping: dict[str, Any], reason_code: str, reason: str) -> dict[str, Any]:
    return {
        "id": f"u_{mapping.get('mapping_id', mapping.get('mention_id', 'binding'))}",
        "source_stage": "step_2_5",
        "reason_code": reason_code,
        "blocking": True,
        "surface": mapping.get("surface"),
        "span": list(_span(mapping)),
        "reason": reason,
    }
