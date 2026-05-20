from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import re
from typing import Any

from .assets import OntologyAssets
from .models import IntentTrace, ShapeField
from .prompts import PromptOutputValidationError, _parse_ontology_path_selection_text


class OntologyPathSelectionValidationError(ValueError):
    pass


@dataclass(frozen=True)
class PathEvidence:
    evidence_id: str
    type: str
    mapping_id: str | None = None
    surface: str | None = None
    semantic_object_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _without_none(
            {
                "evidence_id": self.evidence_id,
                "type": self.type,
                "mapping_id": self.mapping_id,
                "surface": self.surface,
                "semantic_object_id": self.semantic_object_id,
            }
        )


@dataclass(frozen=True)
class PathRequest:
    request_id: str
    from_class: str
    to_class: str
    source_mapping_id: str
    source_surface: str
    source_kind: str
    relation_hint: str | None = None
    role: str | None = None
    semantic_object_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _without_none(
            {
                "request_id": self.request_id,
                "from_class": self.from_class,
                "to_class": self.to_class,
                "relation_hint": self.relation_hint,
                "role": self.role,
                "source_mapping_id": self.source_mapping_id,
                "source_surface": self.source_surface,
                "source_kind": self.source_kind,
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
    shape_updates: dict[str, ShapeField]
    clarification: dict[str, Any] | None = None

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
        return payload

    def to_stage_dict(self) -> dict[str, Any]:
        return {"ontology_path_selection": self.to_dict()}


class OntologyPathSelectionService:
    def __init__(self, *, assets: OntologyAssets, llm_selector: object) -> None:
        self.assets = assets
        self.llm_selector = llm_selector

    def fill(self, *, ontology_mapping: dict[str, Any], intent_trace: IntentTrace, question: str) -> OntologyPathSelectionTrace:
        path_requests = build_path_requests(ontology_mapping, intent_trace, assets=self.assets)
        candidate_paths = build_candidate_paths(path_requests, self.assets)
        candidates_by_request = _candidates_by_request(candidate_paths)
        auto_selected = _auto_single_candidate_paths(path_requests, candidates_by_request)
        clarification_options = build_needs_review_clarification_options(path_requests, self.assets)
        clarification = _service_clarification_for_unselectable_requests(
            path_requests,
            candidates_by_request,
            clarification_options,
        )
        raw_output = ""
        llm_selected: tuple[SelectedPath, ...] = ()

        if clarification is None:
            llm_requests = tuple(
                request for request in path_requests if len(candidates_by_request.get(request.request_id, ())) > 1
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
                raw_output = str(getattr(selection, "raw_response", ""))
                parsed = _parse_path_selection_response(raw_output)
                llm_selected, clarification = validate_path_selection(parsed, llm_requests, llm_candidate_paths)

        selected_paths = _merge_selected_paths(path_requests, (*auto_selected, *llm_selected))
        return OntologyPathSelectionTrace(
            path_requests=path_requests,
            candidate_paths=candidate_paths,
            llm_raw_output=raw_output,
            selected_paths=selected_paths,
            shape_updates=_shape_updates(selected_paths, clarification),
            clarification=clarification,
        )


def build_path_requests(
    ontology_mapping: dict[str, Any],
    intent_trace: IntentTrace | None = None,
    *,
    assets: OntologyAssets | None = None,
) -> tuple[PathRequest, ...]:
    del intent_trace
    if assets is None:
        assets = OntologyAssets.from_default_resources()
    relation_index = _relation_index(assets) if assets is not None else {}
    semantic_traversals = _semantic_traversals(assets) if assets is not None else {}
    requests: list[PathRequest] = []
    mapped_mentions = ontology_mapping.get("mapped_mentions", [])
    if not isinstance(mapped_mentions, list):
        return ()
    for item in mapped_mentions:
        if not isinstance(item, dict):
            continue
        if not _is_path_role_mapping(item):
            continue
        ontology_kind = str(item.get("ontology_kind") or "")
        if ontology_kind == "relation":
            relation_id = _normalize_relation_id(str(item.get("ontology_id") or ""))
            relation = relation_index.get(relation_id, {})
            from_class = str(item.get("domain_class") or relation.get("domain") or "")
            to_class = str(item.get("range_class") or relation.get("range") or "")
            if not from_class or not to_class:
                continue
            requests.append(_request(item, from_class, to_class, "relation", relation_hint=relation_id))
        elif ontology_kind == "relation_role":
            relation_id = _normalize_relation_id(str(item.get("ontology_id") or ""))
            relation = relation_index.get(relation_id, {})
            target_class = str(item.get("target_class") or relation.get("range") or "")
            from_class = str(item.get("domain_class") or relation.get("domain") or "")
            if not from_class:
                from_class = _domain_for_role_relation(relation_index, relation_id, target_class, str(item.get("role") or ""))
            if not from_class or not target_class:
                continue
            requests.append(
                _request(
                    item,
                    from_class,
                    target_class,
                    "relation_role",
                    relation_hint=relation_id,
                    role=str(item.get("role") or "") or None,
                )
            )
        elif ontology_kind == "semantic_object":
            semantic_object_id = str(item.get("ontology_id") or item.get("semantic_object_id") or "")
            traversal = semantic_traversals.get(semantic_object_id)
            if traversal is None:
                continue
            from_class = str(traversal.get("from_class") or "")
            to_class = str(traversal.get("to_class") or "")
            if not from_class or not to_class:
                continue
            requests.append(
                _request(
                    item,
                    from_class,
                    to_class,
                    "semantic_object",
                    semantic_object_id=semantic_object_id,
                )
            )
    return tuple(_renumber_requests(requests))


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


def _is_path_role_mapping(item: dict[str, Any]) -> bool:
    selected_roles = item.get("selected_roles")
    if not isinstance(selected_roles, (list, tuple)) or not selected_roles:
        return True
    return "path_subject" in {str(role) for role in selected_roles}


def _request(
    item: dict[str, Any],
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
        source_mapping_id=str(item.get("mapping_id") or ""),
        source_surface=str(item.get("surface") or ""),
        source_kind=source_kind,
        relation_hint=relation_hint,
        role=role,
        semantic_object_id=semantic_object_id,
    )


def _renumber_requests(requests: list[PathRequest]) -> tuple[PathRequest, ...]:
    return tuple(
        PathRequest(
            request_id=f"PR{index}",
            from_class=request.from_class,
            to_class=request.to_class,
            source_mapping_id=request.source_mapping_id,
            source_surface=request.source_surface,
            source_kind=request.source_kind,
            relation_hint=request.relation_hint,
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
                mapping_id=request.source_mapping_id or None,
                surface=request.source_surface or None,
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
        if entry.mention_type != "relation_predicate":
            continue
        relation_id = _normalize_relation_id(entry.canonical_id)
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
    selected_paths: tuple[SelectedPath, ...],
    clarification: dict[str, Any] | None = None,
) -> dict[str, ShapeField]:
    if clarification is not None or not selected_paths:
        return {
            "relation_resolution_expected": ShapeField(
                value=True,
                source="ontology_path_selection",
                decision="clarify",
                confidence=1.0,
                pending_until="user_clarification",
            )
        }
    hop_count = sum(len(item.relation_chain) for item in selected_paths)
    return {
        "hop_count": ShapeField(value=hop_count, source="ontology_path_selection", decision="accept", confidence=1.0),
        "relation_chain_type": ShapeField(
            value="fixed_chain",
            source="ontology_path_selection",
            decision="accept",
            confidence=1.0,
        ),
    }


def _path_selection_cards(
    path_requests: tuple[PathRequest, ...],
    candidate_paths: tuple[CandidatePath, ...],
    ontology_mapping: dict[str, Any],
    assets: OntologyAssets,
) -> str:
    labels = _object_label_index(ontology_mapping)
    candidates_by_request = _candidates_by_request(candidate_paths)
    cards: list[str] = []
    for request in path_requests:
        from_label = _object_label(request.from_class, labels)
        to_label = _object_label(request.to_class, labels)
        lines = [f"任务 {request.request_id}：选择\"{from_label}\"和\"{to_label}\"之间的连接路径"]
        clues = _request_clues(request)
        lines.append(f"原文线索：{clues}")
        lines.append("候选路径：")
        for candidate in candidates_by_request.get(request.request_id, ()):
            lines.append(f"- {candidate.path_id}：{_candidate_description(candidate, labels, assets)}")
        cards.append("\n".join(lines))
    return "\n\n".join(cards)


def _request_clues(request: PathRequest) -> str:
    clues: list[str] = []
    if request.source_surface:
        clues.append(f"\"{request.source_surface}\"")
    if request.role:
        clues.append(f"{_role_label(request.role)}角色")
    return "、".join(clues) if clues else "无额外线索"


def _candidate_description(candidate: CandidatePath, labels: dict[str, str], assets: OntologyAssets) -> str:
    from_label = _object_label(candidate.from_class, labels)
    target_label = _candidate_target_label(candidate, labels, assets)
    evidence = _candidate_clues(candidate, assets)
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


def _candidate_clues(candidate: CandidatePath, assets: OntologyAssets) -> str:
    clues: list[str] = []
    for evidence in candidate.evidence:
        if evidence.surface:
            clues.append(f"原文\"{evidence.surface}\"")
    for relation_id in candidate.relation_chain:
        relation = _relation_index(assets).get(_normalize_relation_id(relation_id), {})
        role = relation.get("role")
        if role:
            clues.append(f"{_role_label(str(role))}角色")
    return "、".join(dict.fromkeys(clues)) if clues else "系统候选"


def _object_label_index(ontology_mapping: dict[str, Any]) -> dict[str, str]:
    labels: dict[str, str] = {}
    mapped_mentions = ontology_mapping.get("mapped_mentions", [])
    if not isinstance(mapped_mentions, list):
        return labels
    for item in mapped_mentions:
        if not isinstance(item, dict):
            continue
        surface = str(item.get("surface") or "")
        if not surface:
            continue
        class_id = _class_id_for_prompt(item)
        if class_id and class_id not in labels:
            labels[class_id] = surface
    return labels


def _class_id_for_prompt(item: dict[str, Any]) -> str:
    if item.get("ontology_kind") == "class" and item.get("ontology_id"):
        return str(item["ontology_id"])
    if item.get("ontology_kind") == "relation_role" and item.get("target_class"):
        return str(item["target_class"])
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
    return "ontology_mapping"


def _normalize_relation_id(relation_id: str) -> str:
    if not relation_id:
        return ""
    if relation_id.startswith("REL_"):
        return relation_id
    return f"REL_{relation_id}"


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
