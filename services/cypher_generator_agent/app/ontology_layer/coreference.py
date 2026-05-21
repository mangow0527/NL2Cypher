from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


SAME_INSTANCE = "same_instance"
DISTINCT_INSTANCES = "distinct_instances"
DISTINGUISHING_WORDS = ("另一", "其他", "不同", "分别", "对比", "差集")
COMPARISON_INTENTS = {"comparison_query", "set_operation_query"}


class CoreferenceValidationError(ValueError):
    pass


@dataclass(frozen=True)
class CoreferenceOccurrence:
    mapping_id: str
    object_candidate_id: str
    surface: str
    span: tuple[int, int]
    ontology_kind: str
    class_id: str
    role: str | None
    selected_roles: tuple[str, ...]


class OntologyCoreferenceService:
    def __init__(self, *, llm_selector: object | None = None) -> None:
        self.llm_selector = llm_selector

    def resolve(
        self,
        *,
        question: str,
        ontology_mapping: dict[str, Any],
        selected_paths: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        shape_signals: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        context_signals: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        explicit_distinction_signals: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        intent: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        occurrences = _coreference_occurrences(ontology_mapping)
        projection_start = _projection_start(shape_signals)
        candidate_pairs: list[dict[str, Any]] = []
        resolved_pairs: list[dict[str, Any]] = []
        unresolved_items: list[dict[str, Any]] = []
        llm_decision_traces: list[dict[str, Any]] = []
        same_pairs: list[dict[str, Any]] = []

        pair_index = 1
        for left_index, left in enumerate(occurrences):
            for right in occurrences[left_index + 1 :]:
                if not _can_pair(left, right, projection_start):
                    continue
                candidate_pair_id = f"CR{pair_index}"
                pair_index += 1
                evidence = _pair_evidence(
                    left=left,
                    right=right,
                    selected_paths=selected_paths,
                    projection_start=projection_start,
                    explicit_distinction_signals=explicit_distinction_signals,
                    intent=intent or {},
                )
                candidate_pair = {
                    "candidate_pair_id": candidate_pair_id,
                    "left_object_id": left.mapping_id,
                    "right_object_id": right.mapping_id,
                    "class_id": left.class_id,
                    "evidence": list(evidence),
                }
                candidate_pairs.append(candidate_pair)

                llm_signals = _llm_signals(left, right, context_signals, shape_signals, evidence)
                if self.llm_selector is None:
                    unresolved_items.append(
                        _unresolved_item(
                            candidate_pair_id,
                            left,
                            right,
                            "缺少 LLM 选择器，无法判断两个本体对象记录是否同指。",
                        )
                    )
                    continue
                if len(llm_signals) < 2:
                    unresolved_items.append(
                        _unresolved_item(
                            candidate_pair_id,
                            left,
                            right,
                            "可引用证据不足，无法安全判断两个本体对象记录是否同指。",
                        )
                    )
                    continue

                variables = _prompt_variables(question, left, right, llm_signals)
                selection = self.llm_selector.select("coreference_selection", variables)
                raw_output = str(getattr(selection, "raw_response", ""))
                parsed = getattr(selection, "parsed", None)
                if not isinstance(parsed, dict):
                    parsed = _parse_coreference_selection_text(raw_output)
                validated = validate_coreference_llm_output(parsed, llm_signals)
                llm_decision_traces.append(
                    {
                        "candidate_pair_id": candidate_pair_id,
                        "llm_prompt": str(getattr(selection, "rendered_prompt", "")),
                        "llm_raw_output": raw_output,
                        "validated_output": dict(validated),
                    }
                )
                if validated["decision"] == "clarify":
                    unresolved_items.append(
                        _unresolved_item(candidate_pair_id, left, right, str(validated.get("reason") or "指代不明。"))
                    )
                    continue
                decision = SAME_INSTANCE if validated["candidate_id"] == "C1" else DISTINCT_INSTANCES
                resolved = _resolved_pair(candidate_pair, decision, "llm", tuple(validated["signal_ids"]))
                resolved_pairs.append(resolved)
                if decision == SAME_INSTANCE:
                    same_pairs.append(resolved)

        merged_nodes = _merged_nodes(same_pairs, {item.mapping_id: item for item in occurrences})
        merged_by_object_id = {
            object_id: node["node_id"] for node in merged_nodes for object_id in node["object_ids"]
        }
        resolved_pairs = [
            dict(item, merged_to=merged_by_object_id.get(str(item["left_object_id"])))
            if item["decision"] == SAME_INSTANCE
            else item
            for item in resolved_pairs
        ]

        return {
            "candidate_pairs": candidate_pairs,
            "resolved_pairs": resolved_pairs,
            "merged_nodes": merged_nodes,
            "unresolved_items": unresolved_items,
            "llm_decision_traces": llm_decision_traces,
        }


def validate_coreference_llm_output(parsed: dict[str, Any], signals: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    decision = parsed.get("decision")
    if decision not in {"accept", "clarify"}:
        raise CoreferenceValidationError("decision must be accept or clarify")
    candidate_id = parsed.get("candidate_id")
    if candidate_id is not None and str(candidate_id) not in {"C1", "C2"}:
        raise CoreferenceValidationError(f"unknown candidate_id: {candidate_id}")
    if decision == "clarify":
        if candidate_id is not None:
            raise CoreferenceValidationError("clarify candidate_id must be null")
        return {"decision": "clarify", "candidate_id": None, "signal_ids": [], "reason": str(parsed.get("reason") or "")}
    if candidate_id is None:
        raise CoreferenceValidationError("accept requires candidate_id")
    normalized_signal_ids: list[str] = []
    for signal in signals:
        signal_id = str(signal.get("signal_id") or "")
        if signal_id and signal_id not in normalized_signal_ids:
            normalized_signal_ids.append(signal_id)
    if len(normalized_signal_ids) < 2:
        raise CoreferenceValidationError("accept requires at least 2 input signals")
    return {
        "decision": "accept",
        "candidate_id": str(candidate_id),
        "signal_ids": normalized_signal_ids,
        "reason": str(parsed.get("reason") or ""),
    }


def _parse_coreference_selection_text(raw_response: str) -> dict[str, Any]:
    for line in raw_response.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("需要澄清"):
            reason = line.split("：", 1)[1].strip() if "：" in line else line.removeprefix("需要澄清").strip(" :：")
            return {"decision": "clarify", "candidate_id": None, "reason": reason or "指代不明。"}
        match = re.search(r"选择\s*(C[12])\s*(?:[。.]|[：:])?\s*理由\s*[：:]\s*(.*)", line)
        if match:
            return {"decision": "accept", "candidate_id": match.group(1), "reason": match.group(2).strip()}
        raise CoreferenceValidationError(f"unrecognized coreference selection line: {line}")
    raise CoreferenceValidationError("coreference selection output is empty")


def _coreference_occurrences(ontology_mapping: dict[str, Any]) -> tuple[CoreferenceOccurrence, ...]:
    occurrences: list[CoreferenceOccurrence] = []
    evidence_index = _evidence_index(ontology_mapping)
    for item in ontology_mapping.get("ontology_objects", []):
        if not isinstance(item, dict):
            continue
        object_candidate_id = str(item.get("object_candidate_id") or "")
        if not object_candidate_id:
            continue
        class_id = str(item.get("class_id") or "")
        if not class_id:
            continue
        evidence = _first_evidence(item, evidence_index)
        span = evidence.get("span", [0, 0])
        span_pair = (int(span[0]), int(span[1])) if isinstance(span, (list, tuple)) and len(span) == 2 else (0, 0)
        role_hint = item.get("role_hint") if isinstance(item.get("role_hint"), dict) else {}
        occurrences.append(
            CoreferenceOccurrence(
                mapping_id=str(item.get("object_id") or object_candidate_id),
                object_candidate_id=object_candidate_id,
                surface=str(evidence.get("surface") or evidence.get("text") or ""),
                span=span_pair,
                ontology_kind="relation_role" if role_hint else "class",
                class_id=class_id,
                role=str(role_hint.get("role")) if role_hint.get("role") is not None else None,
                selected_roles=tuple(str(role) for role in item.get("selected_roles", []) if role),
            )
        )
    return tuple(sorted(occurrences, key=lambda item: (item.span[0], item.span[1], item.mapping_id)))


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


def _can_pair(left: CoreferenceOccurrence, right: CoreferenceOccurrence, projection_start: int | None) -> bool:
    if left.class_id == right.class_id:
        return True
    if left.role and left.role == right.role and left.class_id == right.class_id:
        return True
    return projection_start is not None and _is_projection_occurrence(right, projection_start) and left.class_id == right.class_id


def _pair_evidence(
    *,
    left: CoreferenceOccurrence,
    right: CoreferenceOccurrence,
    selected_paths: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    projection_start: int | None,
    explicit_distinction_signals: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    intent: dict[str, Any],
) -> tuple[str, ...]:
    del selected_paths
    evidence: list[str] = []
    if left.class_id == right.class_id:
        evidence.append("same_class")
    if left.role and left.role == right.role and left.class_id == right.class_id:
        evidence.append("same_role")
    if projection_start is not None and _is_projection_occurrence(right, projection_start):
        evidence.append("right_mapping_in_projection_region")
    has_distinction = _has_explicit_distinction(left, right, explicit_distinction_signals)
    if has_distinction:
        evidence.append("explicit_distinction")
    else:
        evidence.append("no_distinguishing_qualifier")
    if _different_filter_segment(left, right):
        evidence.append("different_filter_segment")
    if _comparison_sides_differ(left, right, intent):
        evidence.append("different_comparison_side")
    return tuple(evidence)


def _projection_start(shape_signals: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> int | None:
    starts: list[int] = []
    for signal in shape_signals:
        signal_type = str(signal.get("signal_type") or signal.get("type") or "")
        if "PROJECTION" not in signal_type and signal.get("signal_id") != "project_marker":
            continue
        span = signal.get("span")
        if isinstance(span, (list, tuple)) and len(span) == 2:
            starts.append(int(span[1]))
    return min(starts) if starts else None


def _is_projection_occurrence(occurrence: CoreferenceOccurrence, projection_start: int) -> bool:
    return occurrence.span[0] >= projection_start


def _has_explicit_distinction(
    left: CoreferenceOccurrence,
    right: CoreferenceOccurrence,
    explicit_distinction_signals: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> bool:
    between_start = min(left.span[1], right.span[1])
    between_end = max(left.span[0], right.span[0])
    for signal in explicit_distinction_signals:
        supports = {str(item) for item in signal.get("supports", [])} if isinstance(signal.get("supports"), list) else set()
        if {left.mapping_id, right.mapping_id}.issubset(supports):
            return True
        span = signal.get("span")
        if isinstance(span, (list, tuple)) and len(span) == 2 and between_start <= int(span[0]) <= between_end:
            return True
        text = str(signal.get("text") or "")
        if any(word in text for word in DISTINGUISHING_WORDS):
            return True
    return False


def _different_filter_segment(left: CoreferenceOccurrence, right: CoreferenceOccurrence) -> bool:
    left_filter = {role for role in left.selected_roles if role == "filter_subject"}
    right_filter = {role for role in right.selected_roles if role == "filter_subject"}
    return bool(left_filter) != bool(right_filter) and left.class_id == right.class_id


def _comparison_sides_differ(left: CoreferenceOccurrence, right: CoreferenceOccurrence, intent: dict[str, Any]) -> bool:
    primary = str(intent.get("primary") or "")
    secondary = str(intent.get("secondary") or "")
    if primary not in COMPARISON_INTENTS and secondary not in COMPARISON_INTENTS:
        return False
    return left.span[0] != right.span[0]


def _llm_signals(
    left: CoreferenceOccurrence,
    right: CoreferenceOccurrence,
    context_signals: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    shape_signals: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    evidence: tuple[str, ...],
) -> tuple[dict[str, Any], ...]:
    signals: list[dict[str, Any]] = []
    signal_index = 1
    for source in (*context_signals, *shape_signals):
        text = str(source.get("text") or source.get("signal_type") or source.get("type") or "")
        if not text:
            continue
        signals.append(
            {
                "signal_id": f"K{signal_index}",
                "text": text,
                "source_signal_id": str(source.get("signal_id") or ""),
                "supports": ("C1", "C2"),
            }
        )
        signal_index += 1
    for item in evidence:
        signals.append(
            {
                "signal_id": f"K{signal_index}",
                "text": _evidence_label(item),
                "source_signal_id": item,
                "supports": ("C1", "C2"),
            }
        )
        signal_index += 1
    return tuple(signals)


def _prompt_variables(
    question: str,
    left: CoreferenceOccurrence,
    right: CoreferenceOccurrence,
    signals: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    return {
        "question": question,
        "left_object_description": _object_description(left),
        "right_object_description": _object_description(right),
        "resolution_candidate_list_with_ids": (
            "C1: 同一个对象\n"
            "C2: 两个不同对象"
        ),
        "signal_list_with_ids": "\n".join(
            f"{signal['signal_id']}: {signal['text']} supports=C1,C2" for signal in signals
        ),
        "allowed_candidate_ids": ["C1", "C2"],
        "allowed_signal_ids": [signal["signal_id"] for signal in signals],
    }


def _object_description(occurrence: CoreferenceOccurrence) -> str:
    parts = [f"原文片段“{occurrence.surface}”", f"位置 {occurrence.span[0]}-{occurrence.span[1]}"]
    if occurrence.role:
        parts.append(f"角色线索 {_role_label(occurrence.role)}")
    if occurrence.selected_roles:
        role_text = "、".join(_selected_role_label(role) for role in occurrence.selected_roles)
        parts.append(f"用途线索 {role_text}")
    return "，".join(parts)


def _role_label(role: str) -> str:
    return {
        "source": "源端",
        "destination": "目的端",
        "target": "目标端",
        "through": "经过",
    }.get(role, role)


def _selected_role_label(role: str) -> str:
    return {
        "filter_subject": "被条件限定",
        "path_subject": "参与连接",
        "projection_subject": "返回字段所属对象",
        "return_subject": "作为结果对象返回",
    }.get(role, role)


def _evidence_label(evidence: str) -> str:
    return {
        "same_class": "两个对象类型一致",
        "same_role": "两个对象的角色线索一致",
        "right_mapping_in_projection_region": "对象 B 位于返回字段区域",
        "no_distinguishing_qualifier": "两者之间没有“另一/不同/分别/对比/差集”等区分词",
        "explicit_distinction": "问题中出现“另一/不同/分别/对比/差集”等区分词",
        "different_filter_segment": "一个对象用于条件限定，另一个不是",
        "different_comparison_side": "两个对象位于对比问题的不同侧",
    }.get(evidence, evidence)


def _resolved_pair(
    candidate_pair: dict[str, Any],
    decision: str,
    selected_by: str,
    signal_ids: tuple[str, ...] | None,
) -> dict[str, Any]:
    payload = {
        "candidate_pair_id": candidate_pair["candidate_pair_id"],
        "left_object_id": candidate_pair["left_object_id"],
        "right_object_id": candidate_pair["right_object_id"],
        "decision": decision,
        "selected_by": selected_by,
        "evidence": list(candidate_pair["evidence"]),
    }
    if signal_ids is not None:
        payload["signal_ids"] = list(signal_ids)
    return payload


def _merged_nodes(
    same_pairs: list[dict[str, Any]],
    occurrence_by_mapping_id: dict[str, CoreferenceOccurrence],
) -> list[dict[str, Any]]:
    parent: dict[str, str] = {}

    def find(item: str) -> str:
        parent.setdefault(item, item)
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root == right_root:
            return
        parent[right_root] = left_root

    for object_id in occurrence_by_mapping_id:
        parent[object_id] = object_id

    for pair in same_pairs:
        union(str(pair["left_object_id"]), str(pair["right_object_id"]))

    groups: dict[str, list[str]] = {}
    for object_id in parent:
        groups.setdefault(find(object_id), []).append(object_id)
    merged_nodes: list[dict[str, Any]] = []
    class_counts: dict[str, int] = {}
    ordered_groups = sorted(
        (sorted(items, key=lambda item: occurrence_by_mapping_id[item].span) for items in groups.values()),
        key=lambda items: occurrence_by_mapping_id[items[0]].span,
    )
    for object_ids in ordered_groups:
        class_id = occurrence_by_mapping_id[object_ids[0]].class_id
        class_counts[class_id] = class_counts.get(class_id, 0) + 1
        merged_nodes.append({"node_id": _merged_node_id(class_id, class_counts[class_id]), "class_id": class_id, "object_ids": object_ids})
    return merged_nodes


def _merged_node_id(class_id: str, index: int) -> str:
    prefix = {"Service": "s", "Tunnel": "t", "NetworkElement": "n", "Port": "p", "Protocol": "proto"}.get(class_id, "n")
    return f"{prefix}{index}"


def _unresolved_item(
    candidate_pair_id: str,
    left: CoreferenceOccurrence,
    right: CoreferenceOccurrence,
    reason: str,
) -> dict[str, Any]:
    return {
        "id": f"u_{candidate_pair_id}",
        "source_stage": "step_3_4",
        "type": "ambiguous_coreference",
        "blocking": True,
        "candidate_pair_id": candidate_pair_id,
        "object_ids": [left.mapping_id, right.mapping_id],
        "message": reason,
        "reason": reason,
        "reason_code": "AMBIGUOUS_COREFERENCE",
        "suggested_error_type": "ClarificationNeeded",
        "options": [SAME_INSTANCE, DISTINCT_INSTANCES],
    }
