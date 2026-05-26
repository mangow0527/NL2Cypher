from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import re
from typing import Any

from services.cypher_generator_agent.app.intent_layer.models import InitialShapeField

from .assets import OntologyAssets
from .prompts import PromptOutputValidationError, _parse_ontology_path_selection_text


_RETRIEVAL_PLAN_RELATION_SCORE_THRESHOLD = 0.4
_RETRIEVAL_PLAN_EVIDENCE_TYPE = "retrieval_plan_relation_candidate"


class OntologyPathSelectionValidationError(ValueError):
    pass


@dataclass(frozen=True)
class PathEvidence:
    evidence_id: str
    type: str
    source_id: str | None = None
    evidence_refs: tuple[str, ...] = ()
    semantic_object_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _without_none(
            {
                "evidence_id": self.evidence_id,
                "type": self.type,
                "source_id": self.source_id,
                "evidence_refs": list(self.evidence_refs),
                "semantic_object_id": self.semantic_object_id,
            }
        )


@dataclass(frozen=True)
class PathRequest:
    request_id: str
    from_class: str
    to_class: str
    source_id: str
    source_kind: str
    evidence_refs: tuple[str, ...] = ()
    relation_hint: str | None = None
    relation_hint_id: str | None = None
    role: str | None = None
    semantic_object_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _without_none(
            {
                "request_id": self.request_id,
                "from_class": self.from_class,
                "to_class": self.to_class,
                "relation_hint": self.relation_hint,
                "relation_hint_id": self.relation_hint_id,
                "role": self.role,
                "source_id": self.source_id,
                "source_kind": self.source_kind,
                "evidence_refs": list(self.evidence_refs),
                "semantic_object_id": self.semantic_object_id,
            }
        )


@dataclass(frozen=True)
class CandidatePath:
    path_id: str
    request_id: str
    relation_chain: tuple[str, ...]
    from_class: str
    to_class: str
    source: str
    evidence: tuple[PathEvidence, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path_id": self.path_id,
            "request_id": self.request_id,
            "relation_chain": list(self.relation_chain),
            "from_class": self.from_class,
            "to_class": self.to_class,
            "source": self.source,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class SelectedPath:
    request_id: str
    path_id: str
    relation_chain: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    selected_by: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "path_id": self.path_id,
            "relation_chain": list(self.relation_chain),
            "evidence_ids": list(self.evidence_ids),
            "selected_by": self.selected_by,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class OntologyPathSelectionTrace:
    path_requests: tuple[PathRequest, ...]
    candidate_paths: tuple[CandidatePath, ...]
    llm_raw_output: str
    selected_paths: tuple[SelectedPath, ...]
    shape_updates: dict[str, InitialShapeField]
    clarification: dict[str, Any] | None = None
    llm_prompt: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "path_requests": [item.to_dict() for item in self.path_requests],
            "candidate_paths": [item.to_dict() for item in self.candidate_paths],
            "selected_paths": [item.to_dict() for item in self.selected_paths],
            "shape_updates": {key: value.to_dict() for key, value in self.shape_updates.items()},
            "clarification": dict(self.clarification) if self.clarification is not None else None,
        }
        if self.llm_raw_output:
            payload["llm_raw_output"] = self.llm_raw_output
        if self.llm_prompt:
            payload["llm_prompt"] = self.llm_prompt
        return payload

    def to_stage_dict(self) -> dict[str, Any]:
        return {"ontology_path_selection": self.to_dict()}


class OntologyPathSelectionService:
    def __init__(self, *, assets: OntologyAssets, llm_selector: object) -> None:
        self.assets = assets
        self.llm_selector = llm_selector

    def fill(
        self,
        *,
        ontology_mapping: dict[str, Any],
        question: str,
        lexer_trace: Any | None = None,
    ) -> OntologyPathSelectionTrace:
        path_requests = build_path_requests(ontology_mapping, assets=self.assets)
        candidate_paths = build_candidate_paths(path_requests, self.assets)
        candidate_paths = _add_retrieval_plan_evidence(candidate_paths, lexer_trace)
        candidates_by_request = _candidates_by_request(candidate_paths)
        auto_selected = _auto_single_candidate_paths(path_requests, candidates_by_request)
        plan_selected = _auto_retrieval_plan_supported_paths(path_requests, candidates_by_request, auto_selected)
        clarification_options = build_needs_review_clarification_options(path_requests, self.assets)
        clarification = _service_clarification_for_unselectable_requests(
            path_requests,
            candidates_by_request,
            clarification_options,
        )
        raw_output = ""
        llm_prompt = ""
        llm_selected: tuple[SelectedPath, ...] = ()

        if clarification is None:
            auto_selected_request_ids = {selected.request_id for selected in (*auto_selected, *plan_selected)}
            llm_requests = tuple(
                request
                for request in path_requests
                if request.request_id not in auto_selected_request_ids
                and len(candidates_by_request.get(request.request_id, ())) > 1
            )
            if llm_requests:
                llm_candidate_paths = tuple(
                    candidate
                    for request in llm_requests
                    for candidate in candidates_by_request.get(request.request_id, ())
                )
                selection = self.llm_selector.select(
                    "ontology_path_selection",
                    {
                        "question": question,
                        "path_selection_cards": _path_selection_cards(
                            llm_requests,
                            llm_candidate_paths,
                            ontology_mapping,
                            self.assets,
                        ),
                    },
                )
                llm_prompt = str(getattr(selection, "rendered_prompt", ""))
                raw_output = str(getattr(selection, "raw_response", ""))
                parsed = _parse_path_selection_response(raw_output)
                llm_selected, clarification = validate_path_selection(parsed, llm_requests, llm_candidate_paths)

        selected_paths = _merge_selected_paths(path_requests, (*auto_selected, *plan_selected, *llm_selected))
        return OntologyPathSelectionTrace(
            path_requests=path_requests,
            candidate_paths=candidate_paths,
            llm_raw_output=raw_output,
            selected_paths=selected_paths,
            shape_updates=_shape_updates(path_requests, selected_paths, clarification),
            clarification=clarification,
            llm_prompt=llm_prompt,
        )


def build_path_requests(
    ontology_mapping: dict[str, Any],
    *,
    assets: OntologyAssets | None = None,
) -> tuple[PathRequest, ...]:
    if assets is None:
        assets = OntologyAssets.from_default_resources()
    semantic_traversals = _semantic_traversals(assets) if assets is not None else {}
    requests: list[PathRequest] = []
    ontology_objects = _ontology_objects(ontology_mapping)
    relation_hints = _ontology_relation_hints(ontology_mapping)
    ontology_attributes = _ontology_attributes(ontology_mapping)
    if not ontology_objects and not relation_hints:
        return ()
    path_subject_pair_requests = _path_subject_pair_requests(ontology_objects, relation_hints, ontology_attributes)
    covered_relation_hint_ids = {
        request.relation_hint_id
        for request in path_subject_pair_requests
        if request.relation_hint_id
    }
    requests.extend(path_subject_pair_requests)
    for hint in relation_hints:
        if str(hint.get("relation_hint_id") or "") in covered_relation_hint_ids:
            continue
        if not _has_path_role(hint):
            continue
        semantic_object_id = str(hint.get("semantic_object_id") or "")
        if semantic_object_id:
            traversal = semantic_traversals.get(semantic_object_id)
            if traversal is None:
                continue
            from_class = str(traversal.get("from_class") or "")
            to_class = str(traversal.get("to_class") or "")
            if not from_class or not to_class:
                continue
            requests.append(
                _request_from_hint(hint, from_class, to_class, "semantic_object", semantic_object_id=semantic_object_id)
            )
            continue
        relation_id = _normalize_relation_id(str(hint.get("relation_id") or ""))
        from_class = str(hint.get("from_class") or "")
        to_class = str(hint.get("to_class") or "")
        if not from_class or not to_class:
            continue
        source_kind = "relation_role" if hint.get("role") else "relation"
        requests.append(
            _request_from_hint(
                hint,
                from_class,
                to_class,
                source_kind,
                relation_hint=relation_id or None,
                role=str(hint.get("role") or "") or None,
            )
        )
    requests.extend(_terminal_attribute_requests(ontology_attributes, requests))
    requests.extend(_terminal_projection_subject_requests(ontology_objects, requests))
    return tuple(_renumber_requests(_deduplicate_requests(requests)))


def build_candidate_paths(path_requests: tuple[PathRequest, ...], assets: OntologyAssets) -> tuple[CandidatePath, ...]:
    relation_index = _relation_index(assets)
    semantic_traversals = _semantic_traversals(assets)
    default_paths = _default_paths(assets)
    candidates: list[CandidatePath] = []
    evidence_counter = 1

    for request in path_requests:
        if request.relation_hint:
            relation_id = _normalize_relation_id(request.relation_hint)
            relation = relation_index.get(relation_id)
            if relation and _relation_connects(relation, request.from_class, request.to_class):
                source = "role_relation_mapping" if request.source_kind == "relation_role" else "explicit_relation_mapping"
                candidates.append(
                    _candidate(
                        request,
                        (relation_id,),
                        source,
                        evidence_counter,
                        _evidence_type_for_request(request),
                    )
                )
                evidence_counter += 1

    for request in path_requests:
        if request.semantic_object_id:
            traversal = semantic_traversals.get(request.semantic_object_id)
            chain = _relation_chain(traversal)
            if chain:
                candidates.append(
                    _candidate(
                        request,
                        chain,
                        "semantic_traversal",
                        evidence_counter,
                        "semantic_traversal_mapping",
                    )
                )
                evidence_counter += 1

    for request in path_requests:
        for default_path in default_paths:
            if default_path.get("confidence") != "confirmed":
                continue
            if default_path.get("from_class") != request.from_class or default_path.get("to_class") != request.to_class:
                continue
            chain = _relation_chain(default_path)
            if not chain:
                continue
            candidates.append(_candidate(request, chain, "confirmed_default_path", evidence_counter, "default_path"))
            evidence_counter += 1

    for request in path_requests:
        if _has_candidate_for_request(candidates, request.request_id) or _has_needs_review_default_path(request, default_paths):
            continue
        for chain in _graph_paths(request.from_class, request.to_class, relation_index, max_hops=3):
            candidates.append(
                _candidate(request, chain, "ontology_relation_graph", evidence_counter, "ontology_relation_graph")
            )
            evidence_counter += 1

    return tuple(
        CandidatePath(
            path_id=f"P{index}",
            request_id=item.request_id,
            relation_chain=item.relation_chain,
            from_class=item.from_class,
            to_class=item.to_class,
            source=item.source,
            evidence=item.evidence,
        )
        for index, item in enumerate(candidates, start=1)
    )


def _add_retrieval_plan_evidence(
    candidate_paths: tuple[CandidatePath, ...],
    lexer_trace: Any | None,
) -> tuple[CandidatePath, ...]:
    plan_relation_ids = _retrieval_plan_relation_ids(lexer_trace)
    if not plan_relation_ids:
        return candidate_paths
    enriched: list[CandidatePath] = []
    evidence_counter = 1
    for candidate in candidate_paths:
        relation_ids = tuple(
            relation_id
            for relation_id in candidate.relation_chain
            if relation_id in plan_relation_ids
            and not _candidate_has_plan_evidence_for_relation(candidate, relation_id)
        )
        if not relation_ids:
            enriched.append(candidate)
            continue
        evidence_items: list[PathEvidence] = list(candidate.evidence)
        for relation_id in relation_ids:
            evidence_items.append(
                PathEvidence(
                    evidence_id=f"PE_RP{evidence_counter}",
                    type=_RETRIEVAL_PLAN_EVIDENCE_TYPE,
                    source_id=relation_id,
                )
            )
            evidence_counter += 1
        enriched.append(
            CandidatePath(
                path_id=candidate.path_id,
                request_id=candidate.request_id,
                relation_chain=candidate.relation_chain,
                from_class=candidate.from_class,
                to_class=candidate.to_class,
                source=candidate.source,
                evidence=tuple(evidence_items),
            )
        )
    return tuple(enriched)


def _retrieval_plan_relation_ids(lexer_trace: Any | None) -> set[str]:
    if lexer_trace is None:
        return set()
    raw_recalls = getattr(lexer_trace, "vector_recalls", None)
    if not isinstance(raw_recalls, (list, tuple)):
        return set()
    relation_ids: set[str] = set()
    for recall in raw_recalls:
        if not isinstance(recall, dict):
            continue
        if recall.get("source") != "question_framing_retrieval_plan":
            continue
        candidates = recall.get("candidates")
        if not isinstance(candidates, (list, tuple)):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            if str(candidate.get("mention_type") or "").upper() != "RELATION":
                continue
            score = _float_or_zero(candidate.get("score"))
            if score < _RETRIEVAL_PLAN_RELATION_SCORE_THRESHOLD:
                continue
            relation_id = _normalize_relation_id(str(candidate.get("canonical_id") or "").removeprefix("REL_"))
            if relation_id:
                relation_ids.add(relation_id)
    return relation_ids


def _candidate_has_plan_evidence_for_relation(candidate: CandidatePath, relation_id: str) -> bool:
    return any(
        evidence.type == _RETRIEVAL_PLAN_EVIDENCE_TYPE and evidence.source_id == relation_id
        for evidence in candidate.evidence
    )


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def build_needs_review_clarification_options(
    path_requests: tuple[PathRequest, ...],
    assets: OntologyAssets,
) -> tuple[dict[str, Any], ...]:
    options: list[dict[str, Any]] = []
    for request in path_requests:
        for default_path in _default_paths(assets):
            if default_path.get("confidence") != "needs_review":
                continue
            if default_path.get("from_class") != request.from_class or default_path.get("to_class") != request.to_class:
                continue
            chain = _relation_chain(default_path)
            if not chain:
                continue
            options.append(
                {
                    "request_id": request.request_id,
                    "default_path_id": str(default_path.get("id") or ""),
                    "from_class": request.from_class,
                    "to_class": request.to_class,
                    "relation_chain": list(chain),
                    "label": _chain_label(request.from_class, chain, assets),
                }
            )
    return tuple(options)


def validate_path_selection(
    parsed: dict[str, Any],
    path_requests: tuple[PathRequest, ...],
    candidate_paths: tuple[CandidatePath, ...],
) -> tuple[tuple[SelectedPath, ...], dict[str, Any] | None]:
    decision = parsed.get("decision")
    if decision not in {"accept", "clarify"}:
        raise OntologyPathSelectionValidationError("decision must be accept or clarify")
    request_ids = {request.request_id for request in path_requests}
    candidate_by_path = {candidate.path_id: candidate for candidate in candidate_paths}

    if decision == "clarify":
        if parsed.get("selected_paths") not in ([], ()):
            raise OntologyPathSelectionValidationError("clarify requires empty selected_paths")
        clarification = parsed.get("clarification")
        if not isinstance(clarification, dict) or not clarification.get("reason"):
            raise OntologyPathSelectionValidationError("clarify requires clarification.reason")
        options = clarification.get("options")
        if not isinstance(options, list) or not options:
            raise OntologyPathSelectionValidationError("clarify requires clarification.options")
        return (), {
            "status": "unresolved",
            "reason_code": "ambiguous_path",
            "reason": str(clarification["reason"]),
            "options": [str(item) for item in options],
        }

    selected_payload = parsed.get("selected_paths")
    if not isinstance(selected_payload, list):
        raise OntologyPathSelectionValidationError("accept requires selected_paths list")
    seen_requests: set[str] = set()
    selected: list[SelectedPath] = []
    for item in selected_payload:
        if not isinstance(item, dict):
            raise OntologyPathSelectionValidationError("selected_paths entries must be objects")
        request_id = str(item.get("request_id"))
        if request_id not in request_ids:
            raise OntologyPathSelectionValidationError(f"unknown request_id: {request_id}")
        if request_id in seen_requests:
            raise OntologyPathSelectionValidationError(f"duplicate request_id: {request_id}")
        path_id = str(item.get("path_id"))
        candidate = candidate_by_path.get(path_id)
        if candidate is None:
            raise OntologyPathSelectionValidationError(f"unknown path_id: {path_id}")
        if candidate.request_id != request_id:
            raise OntologyPathSelectionValidationError(f"path_id {path_id} does not belong to request_id {request_id}")
        normalized_evidence_ids = [evidence.evidence_id for evidence in candidate.evidence]
        if not normalized_evidence_ids:
            raise OntologyPathSelectionValidationError(f"path_id {path_id} has no evidence")
        selected.append(
            SelectedPath(
                request_id=request_id,
                path_id=path_id,
                relation_chain=candidate.relation_chain,
                evidence_ids=tuple(normalized_evidence_ids),
                selected_by="llm",
                reason=str(item.get("reason") or ""),
            )
        )
        seen_requests.add(request_id)
    missing = sorted(request_ids - seen_requests)
    if missing:
        raise OntologyPathSelectionValidationError(f"accept must cover every path_request: {', '.join(missing)}")
    return tuple(selected), None


def _ontology_objects(ontology_mapping: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(item) for item in ontology_mapping.get("ontology_objects", []) if isinstance(item, dict)]


def _ontology_relation_hints(ontology_mapping: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(item) for item in ontology_mapping.get("ontology_relation_hints", []) if isinstance(item, dict)]


def _ontology_attributes(ontology_mapping: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(item) for item in ontology_mapping.get("ontology_attributes", []) if isinstance(item, dict)]


def _evidence_refs(item: dict[str, Any] | None) -> tuple[str, ...]:
    if not isinstance(item, dict):
        return ()
    value = item.get("evidence_refs")
    if isinstance(value, (list, tuple)):
        return tuple(str(ref) for ref in value if ref)
    return ()


def _order(item: dict[str, Any]) -> int:
    try:
        return int(item.get("order", 0))
    except (TypeError, ValueError):
        return 0


def _request_order(request: PathRequest) -> int:
    for ref in request.evidence_refs:
        if ref.startswith("E") and ref[1:].isdigit():
            return int(ref[1:])
    return 0


def _has_path_role(item: dict[str, Any]) -> bool:
    selected_roles = item.get("selected_roles")
    if not isinstance(selected_roles, (list, tuple)) or not selected_roles:
        return True
    return "path_subject" in {str(role) for role in selected_roles}


def _path_subject_pair_requests(
    ontology_objects: list[dict[str, Any]],
    relation_hints: list[dict[str, Any]],
    ontology_attributes: list[dict[str, Any]],
) -> list[PathRequest]:
    class_mentions = [
        item
        for item in ontology_objects
        if isinstance(item, dict)
        and _has_selected_role(item, "path_subject")
        and item.get("class_id")
        and not isinstance(item.get("role_hint"), dict)
    ]
    class_mentions.sort(key=_order)
    if len(class_mentions) == 1 and not _has_selected_path_relation(relation_hints):
        attribute_target = _first_unique_attribute_target_after(class_mentions[0], ontology_attributes)
        if attribute_target is not None:
            class_mentions.append(attribute_target)
    requests: list[PathRequest] = []
    for left, right in zip(class_mentions, class_mentions[1:]):
        from_class = str(left.get("class_id") or "")
        to_class = str(right.get("class_id") or "")
        if not from_class or not to_class or from_class == to_class:
            continue
        bridge_relation = _bridge_relation_between(left, right, relation_hints)
        if bridge_relation is None and _relation_hint_chain_exists_between(left, right, relation_hints):
            continue
        requests.append(
            PathRequest(
                request_id="PR0",
                from_class=from_class,
                to_class=to_class,
                source_id=str(bridge_relation.get("relation_hint_id") or "") if bridge_relation else "",
                source_kind="path_subject_pair",
                evidence_refs=_evidence_refs(bridge_relation) if bridge_relation else (*_evidence_refs(left), *_evidence_refs(right)),
                relation_hint=_normalize_relation_id(str(bridge_relation.get("relation_id") or "")) if bridge_relation else None,
                relation_hint_id=str(bridge_relation.get("relation_hint_id") or "") if bridge_relation else None,
                role=str(bridge_relation.get("role") or "") or None if bridge_relation else None,
            )
        )
    return requests


def _first_unique_attribute_target_after(
    class_mapping: dict[str, Any],
    ontology_attributes: list[dict[str, Any]],
) -> dict[str, Any] | None:
    class_order = _order(class_mapping)
    for item in sorted((value for value in ontology_attributes if isinstance(value, dict)), key=_order):
        if _order(item) <= class_order:
            continue
        parent_class = _unique_attribute_parent(item)
        if parent_class:
            return {
                "object_id": f"{item.get('attribute_ref_id', 'attribute')}_parent",
                "class_id": parent_class,
                "evidence_refs": list(_evidence_refs(item)),
                "order": item.get("order"),
            }
    return None


def _has_selected_path_relation(relation_hints: list[dict[str, Any]]) -> bool:
    return any(
        isinstance(item, dict)
        and _has_selected_role(item, "path_subject")
        for item in relation_hints
    )


def _bridge_relation_between(
    left: dict[str, Any],
    right: dict[str, Any],
    relation_hints: list[dict[str, Any]],
) -> dict[str, Any] | None:
    left_order = _order(left)
    right_order = _order(right)
    from_class = str(left.get("class_id") or "")
    to_class = str(right.get("class_id") or "")
    for item in relation_hints:
        if not isinstance(item, dict):
            continue
        item_order = _order(item)
        if item_order < left_order or item_order > right_order:
            continue
        if item.get("from_class") == from_class and item.get("to_class") == to_class:
            return item
    return None


def _relation_hint_chain_exists_between(
    left: dict[str, Any],
    right: dict[str, Any],
    relation_hints: list[dict[str, Any]],
) -> bool:
    left_order = _order(left)
    right_order = _order(right)
    from_class = str(left.get("class_id") or "")
    to_class = str(right.get("class_id") or "")
    if not from_class or not to_class:
        return False
    edges: dict[str, set[str]] = {}
    for item in relation_hints:
        if not isinstance(item, dict) or not _has_path_role(item):
            continue
        item_order = _order(item)
        if item_order < left_order or item_order > right_order:
            continue
        hint_from = str(item.get("from_class") or "")
        hint_to = str(item.get("to_class") or "")
        if hint_from and hint_to:
            edges.setdefault(hint_from, set()).add(hint_to)
    frontier = [from_class]
    seen = {from_class}
    while frontier:
        current = frontier.pop(0)
        for next_class in edges.get(current, ()):
            if next_class == to_class:
                return True
            if next_class in seen:
                continue
            seen.add(next_class)
            frontier.append(next_class)
    return False


def _terminal_attribute_requests(
    ontology_attributes: list[dict[str, Any]],
    requests: list[PathRequest],
) -> list[PathRequest]:
    if not requests:
        return []
    classes_in_paths = {request.from_class for request in requests} | {request.to_class for request in requests}
    added: list[PathRequest] = []
    for item in sorted((value for value in ontology_attributes if isinstance(value, dict)), key=_order):
        parent_class = _unique_attribute_parent(item)
        if not parent_class or parent_class in classes_in_paths:
            continue
        previous_request = _nearest_request_before(item, requests)
        if previous_request is None or previous_request.to_class == parent_class:
            continue
        added.append(
            PathRequest(
                request_id="PR0",
                from_class=previous_request.to_class,
                to_class=parent_class,
                source_id=str(item.get("attribute_ref_id") or ""),
                source_kind="attribute_parent_link",
                evidence_refs=_evidence_refs(item),
            )
        )
        classes_in_paths.add(parent_class)
    return added


def _terminal_projection_subject_requests(
    ontology_objects: list[dict[str, Any]],
    requests: list[PathRequest],
) -> list[PathRequest]:
    classes_in_paths = {request.from_class for request in requests} | {request.to_class for request in requests}
    available_requests = list(requests)
    added: list[PathRequest] = []
    for item in sorted((value for value in ontology_objects if isinstance(value, dict)), key=_order):
        class_id = str(item.get("class_id") or "")
        if not class_id or class_id in classes_in_paths:
            continue
        if not (_has_selected_role(item, "projection_subject") or _has_selected_role(item, "return_subject")):
            continue
        previous_request = _nearest_request_before(item, available_requests)
        if previous_request is not None:
            from_class = previous_request.to_class
        else:
            anchor = _nearest_path_subject_before(item, ontology_objects)
            from_class = str(anchor.get("class_id") or "") if anchor else ""
        if not from_class or from_class == class_id:
            continue
        added.append(
            PathRequest(
                request_id="PR0",
                from_class=from_class,
                to_class=class_id,
                source_id=str(item.get("object_id") or ""),
                source_kind="projection_subject_link",
                evidence_refs=_evidence_refs(item),
            )
        )
        classes_in_paths.add(class_id)
        available_requests.append(added[-1])
    return added


def _nearest_request_before(
    item: dict[str, Any],
    requests: list[PathRequest],
) -> PathRequest | None:
    item_order = _order(item)
    preceding: list[tuple[int, PathRequest]] = []
    for request in requests:
        request_order = _order({"order": _request_order(request)})
        if request_order <= item_order:
            preceding.append((request_order, request))
    if not preceding:
        if not requests:
            return None
        return requests[-1]
    return max(preceding, key=lambda value: value[0])[1]


def _nearest_path_subject_before(
    item: dict[str, Any],
    ontology_objects: list[dict[str, Any]],
) -> dict[str, Any] | None:
    item_order = _order(item)
    anchors = [
        value
        for value in ontology_objects
        if isinstance(value, dict)
        and _has_selected_role(value, "path_subject")
        and value.get("class_id")
        and _order(value) < item_order
    ]
    if anchors:
        return max(anchors, key=_order)
    anchors = [
        value
        for value in ontology_objects
        if isinstance(value, dict)
        and _has_selected_role(value, "path_subject")
        and value.get("class_id")
    ]
    if anchors:
        return max(anchors, key=_order)
    return None


def _unique_attribute_parent(item: dict[str, Any]) -> str:
    candidate_refs = item.get("attribute_candidates")
    parent_class = item.get("parent_class")
    if isinstance(parent_class, str) and parent_class and (
        not isinstance(candidate_refs, list) or len(candidate_refs) <= 1
    ):
        return parent_class
    return ""


def _deduplicate_requests(requests: list[PathRequest]) -> list[PathRequest]:
    deduplicated: list[PathRequest] = []
    seen: set[tuple[str, str, str | None, str | None, str | None]] = set()
    for request in requests:
        key = (request.from_class, request.to_class, request.relation_hint, request.role, request.semantic_object_id)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(request)
    return deduplicated


def _has_selected_role(item: dict[str, Any], role: str) -> bool:
    selected_roles = item.get("selected_roles")
    if not isinstance(selected_roles, (list, tuple)):
        return False
    return role in {str(value) for value in selected_roles}


def _request_from_hint(
    hint: dict[str, Any],
    from_class: str,
    to_class: str,
    source_kind: str,
    *,
    relation_hint: str | None = None,
    role: str | None = None,
    semantic_object_id: str | None = None,
) -> PathRequest:
    return PathRequest(
        request_id="PR0",
        from_class=from_class,
        to_class=to_class,
        source_id=str(hint.get("relation_hint_id") or hint.get("semantic_object_id") or ""),
        source_kind=source_kind,
        evidence_refs=_evidence_refs(hint),
        relation_hint=relation_hint,
        relation_hint_id=str(hint.get("relation_hint_id") or "") or None,
        role=role,
        semantic_object_id=semantic_object_id,
    )


def _renumber_requests(requests: list[PathRequest]) -> tuple[PathRequest, ...]:
    return tuple(
        PathRequest(
            request_id=f"PR{index}",
            from_class=request.from_class,
            to_class=request.to_class,
            source_id=request.source_id,
            source_kind=request.source_kind,
            evidence_refs=request.evidence_refs,
            relation_hint=request.relation_hint,
            relation_hint_id=request.relation_hint_id,
            role=request.role,
            semantic_object_id=request.semantic_object_id,
        )
        for index, request in enumerate(requests, start=1)
    )


def _candidate(
    request: PathRequest,
    relation_chain: tuple[str, ...],
    source: str,
    evidence_counter: int,
    evidence_type: str,
) -> CandidatePath:
    return CandidatePath(
        path_id="P0",
        request_id=request.request_id,
        relation_chain=relation_chain,
        from_class=request.from_class,
        to_class=request.to_class,
        source=source,
        evidence=(
            PathEvidence(
                evidence_id=f"PE{evidence_counter}",
                type=evidence_type,
                source_id=request.source_id or None,
                evidence_refs=request.evidence_refs,
                semantic_object_id=request.semantic_object_id,
            ),
        ),
    )


def _relation_index(assets: OntologyAssets | None) -> dict[str, dict[str, Any]]:
    if assets is None:
        return {}
    relations: dict[str, dict[str, Any]] = {}
    domain_relations = assets.domain_ontology.get("relations", [])
    if isinstance(domain_relations, list):
        for item in domain_relations:
            if not isinstance(item, dict):
                continue
            relation_id = _normalize_relation_id(str(item.get("id") or item.get("relation") or ""))
            if relation_id:
                relations[relation_id] = dict(item, id=relation_id)
    for entry in assets.entries:
        if entry.mention_type != "RELATION":
            continue
        relation_id = entry.canonical_id.removeprefix("REL_")
        relations.setdefault(
            relation_id,
            {
                "id": relation_id,
                "domain": entry.metadata.get("domain"),
                "range": entry.metadata.get("range"),
                "allowed_directions": ["outgoing"],
                "role": entry.metadata.get("role"),
            },
        )
    return relations


def _semantic_traversals(assets: OntologyAssets | None) -> dict[str, dict[str, Any]]:
    if assets is None:
        return {}
    payload = assets.semantic_objects.get("traversals", [])
    traversals: dict[str, dict[str, Any]] = {}
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            traversal_id = str(item.get("id") or "")
            if traversal_id:
                traversals[traversal_id] = dict(item)
    return traversals


def _default_paths(assets: OntologyAssets) -> tuple[dict[str, Any], ...]:
    payload = assets.domain_ontology.get("default_paths", [])
    if not isinstance(payload, list):
        return ()
    return tuple(dict(item) for item in payload if isinstance(item, dict))


def _has_candidate_for_request(candidates: list[CandidatePath], request_id: str) -> bool:
    return any(candidate.request_id == request_id for candidate in candidates)


def _has_needs_review_default_path(request: PathRequest, default_paths: tuple[dict[str, Any], ...]) -> bool:
    for default_path in default_paths:
        if default_path.get("confidence") != "needs_review":
            continue
        if default_path.get("from_class") == request.from_class and default_path.get("to_class") == request.to_class:
            return True
    return False


def _domain_for_role_relation(
    relations: dict[str, dict[str, Any]],
    relation_id: str,
    target_class: str,
    role: str,
) -> str:
    relation = relations.get(relation_id)
    if relation and relation.get("range") == target_class:
        return str(relation.get("domain") or "")
    for candidate in relations.values():
        if candidate.get("range") == target_class and (not role or candidate.get("role") == role):
            return str(candidate.get("domain") or "")
    return ""


def _relation_chain(item: dict[str, Any] | None) -> tuple[str, ...]:
    if not isinstance(item, dict):
        return ()
    value = item.get("relation_chain")
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(_normalize_relation_id(str(relation_id)) for relation_id in value if relation_id)


def _relation_connects(relation: dict[str, Any], from_class: str, to_class: str) -> bool:
    return relation.get("domain") == from_class and relation.get("range") == to_class


def _graph_paths(
    from_class: str,
    to_class: str,
    relations: dict[str, dict[str, Any]],
    *,
    max_hops: int,
) -> tuple[tuple[str, ...], ...]:
    graph: dict[str, list[tuple[str, str]]] = {}
    for relation_id, relation in relations.items():
        domain = relation.get("domain")
        range_ = relation.get("range")
        if not isinstance(domain, str) or not isinstance(range_, str):
            continue
        allowed_directions = relation.get("allowed_directions")
        if allowed_directions and "outgoing" not in allowed_directions:
            continue
        graph.setdefault(domain, []).append((relation_id, range_))
    paths: list[tuple[str, ...]] = []
    queue: deque[tuple[str, tuple[str, ...], tuple[str, ...]]] = deque([(from_class, (), (from_class,))])
    while queue:
        current, chain, seen = queue.popleft()
        if len(chain) >= max_hops:
            continue
        for relation_id, next_class in graph.get(current, []):
            if next_class in seen:
                continue
            next_chain = (*chain, relation_id)
            if next_class == to_class:
                paths.append(next_chain)
                continue
            queue.append((next_class, next_chain, (*seen, next_class)))
    return tuple(paths)


def _candidates_by_request(candidate_paths: tuple[CandidatePath, ...]) -> dict[str, tuple[CandidatePath, ...]]:
    grouped: dict[str, list[CandidatePath]] = {}
    for candidate in candidate_paths:
        grouped.setdefault(candidate.request_id, []).append(candidate)
    return {request_id: tuple(items) for request_id, items in grouped.items()}


def _auto_single_candidate_paths(
    path_requests: tuple[PathRequest, ...],
    candidates_by_request: dict[str, tuple[CandidatePath, ...]],
) -> tuple[SelectedPath, ...]:
    selected: list[SelectedPath] = []
    for request in path_requests:
        candidates = candidates_by_request.get(request.request_id, ())
        if len(candidates) != 1:
            continue
        candidate = candidates[0]
        selected.append(
            SelectedPath(
                request_id=request.request_id,
                path_id=candidate.path_id,
                relation_chain=candidate.relation_chain,
                evidence_ids=tuple(evidence.evidence_id for evidence in candidate.evidence),
                selected_by="auto_single_candidate",
                reason="该连接任务只有一个可接受候选路径，服务层自动接受。",
            )
        )
    return tuple(selected)


def _auto_retrieval_plan_supported_paths(
    path_requests: tuple[PathRequest, ...],
    candidates_by_request: dict[str, tuple[CandidatePath, ...]],
    already_selected: tuple[SelectedPath, ...],
) -> tuple[SelectedPath, ...]:
    selected_request_ids = {selected.request_id for selected in already_selected}
    selected: list[SelectedPath] = []
    for request in path_requests:
        if request.request_id in selected_request_ids:
            continue
        candidates = candidates_by_request.get(request.request_id, ())
        if len(candidates) <= 1:
            continue
        supported_candidates = tuple(
            candidate for candidate in candidates if _retrieval_plan_evidence_covers_chain(candidate)
        )
        if len(supported_candidates) != 1:
            continue
        candidate = supported_candidates[0]
        selected.append(
            SelectedPath(
                request_id=request.request_id,
                path_id=candidate.path_id,
                relation_chain=candidate.relation_chain,
                evidence_ids=tuple(evidence.evidence_id for evidence in candidate.evidence),
                selected_by="auto_retrieval_plan_relation",
                reason="结构化检索计划只支持这一条候选路径，服务层自动接受。",
            )
        )
    return tuple(selected)


def _retrieval_plan_evidence_covers_chain(candidate: CandidatePath) -> bool:
    plan_relation_ids = {
        str(evidence.source_id)
        for evidence in candidate.evidence
        if evidence.type == _RETRIEVAL_PLAN_EVIDENCE_TYPE and evidence.source_id
    }
    return bool(plan_relation_ids) and all(relation_id in plan_relation_ids for relation_id in candidate.relation_chain)


def _service_clarification_for_unselectable_requests(
    path_requests: tuple[PathRequest, ...],
    candidates_by_request: dict[str, tuple[CandidatePath, ...]],
    review_options: tuple[dict[str, Any], ...],
) -> dict[str, Any] | None:
    unselectable_request_ids = {
        request.request_id for request in path_requests if len(candidates_by_request.get(request.request_id, ())) == 0
    }
    if not unselectable_request_ids:
        return None
    options = [
        str(option.get("label") or option.get("default_path_id") or "")
        for option in review_options
        if option.get("request_id") in unselectable_request_ids
    ]
    options = [option for option in dict.fromkeys(options) if option]
    if not options:
        options = ["没有可接受的本体路径候选。"]
    return {
        "status": "unresolved",
        "reason_code": "ambiguous_path",
        "reason": "存在没有可接受候选路径的连接任务，需要用户确认。",
        "options": options,
    }


def _merge_selected_paths(
    path_requests: tuple[PathRequest, ...],
    selected_paths: tuple[SelectedPath, ...],
) -> tuple[SelectedPath, ...]:
    selected_by_request = {selected.request_id: selected for selected in selected_paths}
    return tuple(
        selected_by_request[request.request_id]
        for request in path_requests
        if request.request_id in selected_by_request
    )


def _shape_updates(
    path_requests: tuple[PathRequest, ...],
    selected_paths: tuple[SelectedPath, ...],
    clarification: dict[str, Any] | None = None,
) -> dict[str, InitialShapeField]:
    if clarification is not None:
        return {
            "relation_resolution_expected": InitialShapeField(
                value=True,
                source="ontology_path_selection",
                decision="clarify",
                confidence=1.0,
                pending_until="user_clarification",
            )
        }
    if not path_requests:
        return {
            "hop_count": InitialShapeField(value=0, source="ontology_path_selection", decision="accept", confidence=1.0),
            "relation_chain_type": InitialShapeField(
                value="zero_hop",
                source="ontology_path_selection",
                decision="accept",
                confidence=1.0,
            ),
            "relation_resolution_expected": InitialShapeField(
                value=False,
                source="ontology_path_selection",
                decision="accept",
                confidence=1.0,
            ),
        }
    if not selected_paths:
        return {
            "relation_resolution_expected": InitialShapeField(
                value=True,
                source="ontology_path_selection",
                decision="clarify",
                confidence=1.0,
                pending_until="user_clarification",
            )
        }
    hop_count = sum(len(item.relation_chain) for item in selected_paths)
    updates = {
        "hop_count": InitialShapeField(value=hop_count, source="ontology_path_selection", decision="accept", confidence=1.0),
        "relation_chain_type": InitialShapeField(
            value="fixed_chain",
            source="ontology_path_selection",
            decision="accept",
            confidence=1.0,
        ),
    }
    owner_scope = _path_owner_scope(path_requests, selected_paths)
    if owner_scope:
        updates["path_owner_scope"] = InitialShapeField(
            value=list(owner_scope),
            source="ontology_path_selection",
            decision="accept",
            confidence=1.0,
            derived_from=tuple(selected.request_id for selected in selected_paths),
        )
    return updates


def _path_owner_scope(
    path_requests: tuple[PathRequest, ...],
    selected_paths: tuple[SelectedPath, ...],
) -> tuple[str, ...]:
    requests_by_id = {request.request_id: request for request in path_requests}
    scope: list[str] = []
    for selected in selected_paths:
        request = requests_by_id.get(selected.request_id)
        if request is None:
            continue
        for class_id in (request.from_class, request.to_class):
            if class_id and class_id not in scope:
                scope.append(class_id)
    return tuple(scope)


def _path_selection_cards(
    path_requests: tuple[PathRequest, ...],
    candidate_paths: tuple[CandidatePath, ...],
    ontology_mapping: dict[str, Any],
    assets: OntologyAssets,
) -> str:
    labels = _object_label_index(ontology_mapping)
    evidence_index = _evidence_index(ontology_mapping)
    candidates_by_request = _candidates_by_request(candidate_paths)
    cards: list[str] = []
    for request in path_requests:
        from_label = _object_label(request.from_class, labels)
        to_label = _object_label(request.to_class, labels)
        lines = [f"任务 {request.request_id}：选择\"{from_label}\"和\"{to_label}\"之间的连接路径"]
        clues = _request_clues(request, evidence_index)
        lines.append(f"原文线索：{clues}")
        lines.append("候选路径：")
        for candidate in candidates_by_request.get(request.request_id, ()):
            lines.append(f"- {candidate.path_id}：{_candidate_description(candidate, labels, evidence_index, assets)}")
        cards.append("\n".join(lines))
    return "\n\n".join(cards)


def _request_clues(request: PathRequest, evidence_index: dict[str, dict[str, Any]]) -> str:
    clues: list[str] = []
    for evidence_ref in request.evidence_refs:
        surface = evidence_index.get(evidence_ref, {}).get("surface")
        if surface:
            clues.append(f"\"{surface}\"")
    if request.role:
        clues.append(f"{_role_label(request.role)}角色")
    return "、".join(clues) if clues else "无额外线索"


def _candidate_description(
    candidate: CandidatePath,
    labels: dict[str, str],
    evidence_index: dict[str, dict[str, Any]],
    assets: OntologyAssets,
) -> str:
    from_label = _object_label(candidate.from_class, labels)
    target_label = _candidate_target_label(candidate, labels, assets)
    evidence = _candidate_clues(candidate, evidence_index, assets)
    return f"{from_label} 连接到 {target_label}。线索：{evidence}。"


def _candidate_target_label(candidate: CandidatePath, labels: dict[str, str], assets: OntologyAssets) -> str:
    to_label = _object_label(candidate.to_class, labels)
    if len(candidate.relation_chain) != 1:
        return _chain_label(candidate.from_class, candidate.relation_chain, assets)
    relation = _relation_index(assets).get(_normalize_relation_id(candidate.relation_chain[0]), {})
    role = str(relation.get("role") or "")
    if not role:
        return to_label
    return _role_object_label(role, to_label)


def _role_object_label(role: str, to_label: str) -> str:
    prefix = {
        "source": "源",
        "destination": "目的",
        "through": "经过",
    }.get(role)
    if not prefix:
        return to_label
    if to_label.endswith("网元"):
        return f"{prefix}网元"
    if to_label.startswith(prefix):
        return to_label
    return f"{prefix}{to_label}"


def _candidate_clues(candidate: CandidatePath, evidence_index: dict[str, dict[str, Any]], assets: OntologyAssets) -> str:
    clues: list[str] = []
    for evidence in candidate.evidence:
        if evidence.type == _RETRIEVAL_PLAN_EVIDENCE_TYPE and evidence.source_id:
            clues.append(f"结构化检索计划召回关系 {evidence.source_id}")
        for evidence_ref in evidence.evidence_refs:
            surface = evidence_index.get(evidence_ref, {}).get("surface")
            if surface:
                clues.append(f"原文\"{surface}\"")
    for relation_id in candidate.relation_chain:
        relation = _relation_index(assets).get(_normalize_relation_id(relation_id), {})
        role = relation.get("role")
        if role:
            clues.append(f"{_role_label(str(role))}角色")
    return "、".join(dict.fromkeys(clues)) if clues else "系统候选"


def _object_label_index(ontology_mapping: dict[str, Any]) -> dict[str, str]:
    labels: dict[str, str] = {}
    evidence_index = _evidence_index(ontology_mapping)
    for item in _ontology_objects(ontology_mapping):
        if not isinstance(item, dict):
            continue
        surface = _first_surface(item, evidence_index)
        if not surface:
            continue
        class_id = str(item.get("class_id") or "")
        if class_id and class_id not in labels:
            labels[class_id] = surface
    return labels


def _evidence_index(ontology_mapping: dict[str, Any]) -> dict[str, dict[str, Any]]:
    evidence = ontology_mapping.get("evidence", [])
    if not isinstance(evidence, list):
        return {}
    return {
        str(item.get("evidence_id")): dict(item)
        for item in evidence
        if isinstance(item, dict) and item.get("evidence_id")
    }


def _first_surface(item: dict[str, Any], evidence_index: dict[str, dict[str, Any]]) -> str:
    for evidence_ref in _evidence_refs(item):
        surface = evidence_index.get(evidence_ref, {}).get("surface")
        if isinstance(surface, str) and surface:
            return surface
    return ""


def _object_label(class_id: str, labels: dict[str, str]) -> str:
    return labels.get(class_id) or class_id


def _role_label(role: str) -> str:
    return {
        "source": "源端",
        "destination": "目的端",
        "target": "目标端",
        "through": "经过",
    }.get(role, role)


def _evidence_type_for_request(request: PathRequest) -> str:
    if request.source_kind == "relation_role":
        return "ontology_relation_role_mapping"
    if request.source_kind == "relation":
        return "ontology_relation_mapping"
    if request.source_kind == "path_subject_pair":
        return "path_subject_pair"
    return "ontology_mapping"


def _normalize_relation_id(relation_id: str) -> str:
    if not relation_id:
        return ""
    return relation_id


def _parse_path_selection_response(raw_response: str) -> dict[str, Any]:
    try:
        return _parse_ontology_path_selection_text(raw_response)
    except PromptOutputValidationError as exc:
        raise OntologyPathSelectionValidationError(str(exc)) from exc


def _without_none(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item is not None}


def _chain_label(from_class: str, chain: tuple[str, ...], assets: OntologyAssets) -> str:
    relations = _relation_index(assets)
    classes = [from_class]
    current = from_class
    for relation_id in chain:
        relation = relations.get(_normalize_relation_id(relation_id), {})
        next_class = str(relation.get("range") or "")
        if not next_class:
            next_class = current
        classes.append(next_class)
        current = next_class
    return " -> ".join(classes)
