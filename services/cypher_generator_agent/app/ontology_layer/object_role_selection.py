from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from services.cypher_generator_agent.app.intent_layer.models import IntentOutput

from .models import LexerTrace


ALLOWED_OBJECT_ROLES = (
    "filter_subject",
    "path_subject",
    "projection_subject",
    "return_subject",
    "metric_subject",
    "group_subject",
)


class ObjectRoleSelectionValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ObjectEvidence:
    evidence_id: str
    type: str
    text: str
    span: tuple[int, int]
    source_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "evidence_id": self.evidence_id,
            "type": self.type,
            "text": self.text,
            "span": list(self.span),
        }
        if self.source_id is not None:
            payload["source_id"] = self.source_id
        return payload


@dataclass(frozen=True)
class ObjectCandidate:
    candidate_id: str
    mention_id: str
    mention_type: str
    surface: str
    span: tuple[int, int]
    lexical_canonical_id: str
    candidate_refs: tuple[str, ...]
    metadata: dict[str, Any]
    evidence: tuple[ObjectEvidence, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "mention_id": self.mention_id,
            "mention_type": self.mention_type,
            "surface": self.surface,
            "span": list(self.span),
            "lexical_canonical_id": self.lexical_canonical_id,
            "candidate_refs": list(self.candidate_refs),
            "metadata": dict(self.metadata),
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class SelectedObjectRole:
    candidate_id: str
    mention_id: str
    roles: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    selected_by: str
    reason: str
    class_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "candidate_id": self.candidate_id,
            "mention_id": self.mention_id,
            "roles": list(self.roles),
            "evidence_ids": list(self.evidence_ids),
            "selected_by": self.selected_by,
            "reason": self.reason,
        }
        if self.class_id is not None:
            payload["class_id"] = self.class_id
        return payload


@dataclass(frozen=True)
class ObjectRoleSelection:
    selected_objects: tuple[SelectedObjectRole, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"selected_objects": [item.to_dict() for item in self.selected_objects]}


@dataclass(frozen=True)
class ObjectRoleSelectionTrace:
    object_candidates: tuple[ObjectCandidate, ...]
    allowed_object_roles: tuple[str, ...]
    llm_raw_output: str
    object_role_selection: ObjectRoleSelection
    clarification: dict[str, Any] | None = None
    input_context: dict[str, Any] | None = None
    llm_prompt: str = ""

    def to_dict(self) -> dict[str, Any]:
        candidates = [item.to_dict() for item in self.object_candidates]
        roles = list(self.allowed_object_roles)
        selection = self.object_role_selection.to_dict()
        payload = {
            "object_candidates": candidates,
            "allowed_object_roles": roles,
            "llm_raw_output": self.llm_raw_output,
            "object_role_selection": selection,
            "clarification": dict(self.clarification) if self.clarification is not None else None,
            "input_context": dict(self.input_context) if self.input_context is not None else {},
        }
        if self.llm_prompt:
            payload["llm_prompt"] = self.llm_prompt
        return payload


class OntologyObjectRoleSelectionService:
    def __init__(self, *, llm_selector: object) -> None:
        self.llm_selector = llm_selector

    def select(self, *, lexer_trace: LexerTrace, intent_output: IntentOutput) -> ObjectRoleSelectionTrace:
        candidates = build_object_candidates(lexer_trace)
        if not candidates:
            return ObjectRoleSelectionTrace(
                object_candidates=(),
                allowed_object_roles=ALLOWED_OBJECT_ROLES,
                llm_raw_output="",
                object_role_selection=ObjectRoleSelection(selected_objects=()),
                clarification={
                    "reason_code": "missing_object_candidate",
                    "reason": "当前问题缺少可继续规划的对象片段。",
                    "blocking_evidence": [],
                },
                input_context=_input_context(lexer_trace, intent_output),
            )
        selection = self.llm_selector.select(
            "object_role_selection",
            {
                "question": lexer_trace.question,
                "planning_prompt_text": _planning_prompt_text(intent_output),
                "object_candidate_list": _candidate_list(candidates),
                "allowed_object_roles": list(ALLOWED_OBJECT_ROLES),
                "allowed_candidate_ids": [candidate.candidate_id for candidate in candidates],
            },
        )
        raw_output = str(getattr(selection, "raw_response", ""))
        parsed = _parse_object_role_selection_response(raw_output)
        selected_objects, clarification = validate_object_role_selection(parsed, candidates, lexer_trace)
        selected_objects = _normalize_roles_for_intent(selected_objects, intent_output)
        return ObjectRoleSelectionTrace(
            object_candidates=candidates,
            allowed_object_roles=ALLOWED_OBJECT_ROLES,
            llm_raw_output=raw_output,
            object_role_selection=ObjectRoleSelection(selected_objects=selected_objects),
            clarification=clarification,
            input_context=_input_context(lexer_trace, intent_output),
            llm_prompt=str(getattr(selection, "rendered_prompt", "")),
        )


def build_object_candidates(lexer_trace: LexerTrace) -> tuple[ObjectCandidate, ...]:
    candidates: list[ObjectCandidate] = []
    mention_ids = _mention_ids(lexer_trace)
    evidence_counter = 1
    represented_classes: set[str] = set()
    for mention_index, mention in enumerate(lexer_trace.mentions):
        if mention.mention_type == "OBJECT":
            evidence_type = "self_mention"
        elif mention.mention_type == "RELATION" and _is_role_like_relation(mention):
            evidence_type = "role_surface"
        else:
            continue

        evidence: list[ObjectEvidence] = [
            ObjectEvidence(
                evidence_id=f"E{evidence_counter}",
                type=evidence_type,
                text=mention.surface,
                span=(mention.span_start, mention.span_end),
                source_id=mention_ids[mention_index],
            )
        ]
        evidence_counter += 1

        for related_type, related in _nearby_evidence_mentions(mention_index, lexer_trace):
            evidence.append(
                ObjectEvidence(
                    evidence_id=f"E{evidence_counter}",
                    type=related_type,
                    text=related.surface,
                    span=(related.span_start, related.span_end),
                )
            )
            evidence_counter += 1

        for signal in _candidate_signals(mention, lexer_trace):
            evidence.append(
                ObjectEvidence(
                    evidence_id=f"E{evidence_counter}",
                    type=signal.signal_type.lower(),
                    text=signal.text,
                    span=(signal.span_start, signal.span_end),
                    source_id=signal.signal_id,
                )
            )
            evidence_counter += 1

        candidates.append(
            ObjectCandidate(
                candidate_id=f"SM{len(candidates) + 1}",
                mention_id=mention_ids[mention_index],
                mention_type=mention.mention_type,
                surface=mention.surface,
                span=(mention.span_start, mention.span_end),
                lexical_canonical_id=mention.canonical_id,
                candidate_refs=_candidate_refs(mention),
                metadata=dict(mention.metadata),
                evidence=tuple(evidence),
            )
        )
        represented_classes.update(_represented_classes_for_candidate(candidates[-1]))
    if any(candidate.mention_type == "OBJECT" for candidate in candidates):
        return tuple(candidates)

    inferred_by_class: dict[str, list[tuple[int, Any, str]]] = {}
    for mention_index, mention in enumerate(lexer_trace.mentions):
        for class_id, evidence_type in _inferred_owner_classes(mention):
            if class_id in represented_classes:
                continue
            inferred_by_class.setdefault(class_id, []).append((mention_index, mention, evidence_type))

    for class_id, sources in inferred_by_class.items():
        if not sources:
            continue
        evidence: list[ObjectEvidence] = []
        for mention_index, mention, evidence_type in sources:
            evidence.append(
                ObjectEvidence(
                    evidence_id=f"E{evidence_counter}",
                    type=evidence_type,
                    text=mention.surface,
                    span=(mention.span_start, mention.span_end),
                    source_id=mention_ids[mention_index],
                )
            )
            evidence_counter += 1
        spans = [(mention.span_start, mention.span_end) for _, mention, _ in sources]
        first_index = min(index for index, _, _ in sources)
        candidates.append(
            ObjectCandidate(
                candidate_id=f"SM{len(candidates) + 1}",
                mention_id=mention_ids[first_index],
                mention_type="OBJECT",
                surface=_class_surface(class_id),
                span=(min(span[0] for span in spans), max(span[1] for span in spans)),
                lexical_canonical_id=class_id,
                candidate_refs=(class_id,),
                metadata={
                    "inferred_from": "attribute_or_value_owner",
                    "inferred_class_id": class_id,
                    "source_mention_ids": [mention_ids[index] for index, _, _ in sources],
                },
                evidence=tuple(evidence),
            )
        )
    return tuple(candidates)


def validate_object_role_selection(
    parsed: dict[str, Any],
    candidates: tuple[ObjectCandidate, ...],
    lexer_trace: LexerTrace,
) -> tuple[tuple[SelectedObjectRole, ...], dict[str, Any] | None]:
    decision = parsed.get("decision")
    if decision not in {"accept", "clarify"}:
        raise ObjectRoleSelectionValidationError("decision must be accept or clarify")

    candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    if decision == "clarify":
        clarification = parsed.get("clarification")
        if not isinstance(clarification, dict) or not clarification.get("reason"):
            raise ObjectRoleSelectionValidationError("clarify requires clarification.reason")
        blocking_evidence = clarification.get("blocking_evidence", [])
        if not isinstance(blocking_evidence, list):
            raise ObjectRoleSelectionValidationError("clarify requires blocking_evidence list")
        return (), dict(clarification)

    selected_objects = parsed.get("selected_objects")
    if not isinstance(selected_objects, list):
        raise ObjectRoleSelectionValidationError("accept requires selected_objects list")
    selected: list[SelectedObjectRole] = []
    for item in selected_objects:
        if not isinstance(item, dict):
            raise ObjectRoleSelectionValidationError("object role selection entries must be objects")
        candidate_id = str(item.get("candidate_id"))
        candidate = candidate_by_id.get(candidate_id)
        if candidate is None:
            raise ObjectRoleSelectionValidationError(f"unknown candidate_id: {candidate_id}")
        roles = item.get("roles")
        if not isinstance(roles, list) or not roles:
            raise ObjectRoleSelectionValidationError("roles must be a non-empty list")
        normalized_roles: list[str] = []
        for role in roles:
            role_id = str(role)
            if role_id not in ALLOWED_OBJECT_ROLES:
                raise ObjectRoleSelectionValidationError(f"unknown role: {role_id}")
            if role_id not in normalized_roles:
                normalized_roles.append(role_id)
        normalized_evidence_ids = [evidence.evidence_id for evidence in candidate.evidence]
        selected.append(
            SelectedObjectRole(
                candidate_id=candidate.candidate_id,
                mention_id=candidate.mention_id,
                roles=tuple(normalized_roles),
                evidence_ids=tuple(normalized_evidence_ids),
                selected_by="llm",
                reason=str(item.get("reason") or ""),
                class_id=_candidate_class_id(candidate),
            )
        )
    return tuple(selected), None


def _normalize_roles_for_intent(
    selected_objects: tuple[SelectedObjectRole, ...],
    intent_output: IntentOutput,
) -> tuple[SelectedObjectRole, ...]:
    intent = getattr(intent_output, "intent", None)
    if getattr(intent, "secondary", None) != "attribute_projection_query":
        return selected_objects
    normalized: list[SelectedObjectRole] = []
    for item in selected_objects:
        roles = [role for role in item.roles if role != "return_subject"]
        if len(roles) != len(item.roles) and "projection_subject" not in roles:
            roles.append("projection_subject")
        if tuple(roles) == item.roles:
            normalized.append(item)
            continue
        normalized.append(
            SelectedObjectRole(
                candidate_id=item.candidate_id,
                mention_id=item.mention_id,
                roles=tuple(roles),
                evidence_ids=item.evidence_ids,
                selected_by=item.selected_by,
                reason=item.reason,
                class_id=item.class_id,
            )
        )
    return tuple(normalized)


def _nearby_evidence_mentions(mention_index: int, lexer_trace: LexerTrace) -> tuple[tuple[str, Any], ...]:
    mention = lexer_trace.mentions[mention_index]
    if mention.mention_type == "RELATION" and _is_role_like_relation(mention):
        return ()
    evidence: list[tuple[str, Any]] = []
    nearest_value = _nearest_mention(mention, lexer_trace.mentions, {"VALUE"}, side="left", max_gap=4)
    if nearest_value is not None:
        evidence.append(("nearby_value", nearest_value))
    nearest_relation = _nearest_mention(mention, lexer_trace.mentions, {"RELATION"}, side="both", max_gap=4)
    if nearest_relation is not None and nearest_relation is not mention and not _is_role_like_relation(mention):
        evidence.append(("nearby_relation", nearest_relation))
    nearest_attribute = _nearest_mention(mention, lexer_trace.mentions, {"ATTRIBUTE"}, side="right", max_gap=8)
    if nearest_attribute is not None:
        evidence.append(("nearby_attribute", nearest_attribute))
    nearest_operation = _nearest_mention(mention, lexer_trace.mentions, {"OPERATION"}, side="left", max_gap=8)
    if nearest_operation is not None and nearest_operation.canonical_id == "OP_RETURN_FIELD":
        evidence.append(("projection_marker", nearest_operation))
    return tuple(evidence)


def _nearest_mention(
    mention: Any,
    mentions: tuple[Any, ...],
    mention_types: set[str],
    *,
    side: str,
    max_gap: int,
) -> Any | None:
    candidates: list[tuple[int, Any]] = []
    for other in mentions:
        if other is mention or other.mention_type not in mention_types:
            continue
        if other.span_end <= mention.span_start and side in {"left", "both"}:
            gap = mention.span_start - other.span_end
            if gap <= max_gap:
                candidates.append((gap, other))
        elif other.span_start >= mention.span_end and side in {"right", "both"}:
            gap = other.span_start - mention.span_end
            if gap <= max_gap:
                candidates.append((gap, other))
    if not candidates:
        return None
    return min(candidates, key=lambda item: (item[0], item[1].span_start))[1]


def _candidate_signals(mention: Any, lexer_trace: LexerTrace) -> tuple[Any, ...]:
    refs = {str(mention.canonical_id), mention.surface, *_candidate_refs(mention)}
    matched: list[Any] = []
    for signal in (*lexer_trace.context_signals, *lexer_trace.shape_signals):
        supports = {str(item) for item in signal.supports}
        if refs & supports or _span_overlaps(
            (mention.span_start, mention.span_end),
            (signal.span_start, signal.span_end),
        ):
            matched.append(signal)
    return tuple(matched)


def _span_overlaps(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


def _is_role_like_relation(mention: Any) -> bool:
    if mention.mention_type != "RELATION":
        return False
    metadata = mention.metadata if isinstance(mention.metadata, dict) else {}
    role = metadata.get("role")
    endpoint_roles = {"source", "destination", "src", "dst", "source_endpoint", "destination_endpoint"}
    if isinstance(role, str) and role.strip().lower() in endpoint_roles:
        return True
    role_like_terms = ("网元", "端口", "服务", "隧道", "设备", "链路", "光纤")
    return any(term in mention.surface for term in role_like_terms)


def _mention_ids(lexer_trace: LexerTrace) -> tuple[str, ...]:
    counters: dict[str, int] = {}
    mention_ids: list[str] = []
    for mention in lexer_trace.mentions:
        explicit_id = mention.metadata.get("mention_id") if isinstance(mention.metadata, dict) else None
        if isinstance(explicit_id, str) and explicit_id:
            mention_ids.append(explicit_id)
            continue
        base = _stable_id_part(mention.canonical_id or mention.surface)
        counters[base] = counters.get(base, 0) + 1
        mention_ids.append(f"m_{base}_{counters[base]}")
    return tuple(mention_ids)


def _candidate_refs(mention: Any) -> tuple[str, ...]:
    metadata = mention.metadata if isinstance(mention.metadata, dict) else {}
    refs = metadata.get("candidate_refs")
    if isinstance(refs, (list, tuple)) and refs:
        return tuple(str(item) for item in refs)
    return (str(mention.canonical_id),)


def _all_evidence_ids(candidates: tuple[ObjectCandidate, ...], lexer_trace: LexerTrace) -> set[str]:
    ids = {evidence.evidence_id for candidate in candidates for evidence in candidate.evidence}
    ids.update(signal.signal_id for signal in lexer_trace.context_signals)
    ids.update(signal.signal_id for signal in lexer_trace.shape_signals)
    return ids


def _intent_summary(intent_output: IntentOutput) -> dict[str, Any]:
    return {
        "primary": intent_output.intent.primary,
        "secondary": intent_output.intent.secondary,
    }


def _shape_summary(intent_output: IntentOutput) -> dict[str, Any]:
    keys = (
        "answer_type",
        "projection_expected",
        "relation_resolution_expected",
        "path_answer_required",
        "aggregation_functions",
        "group_by_required",
        "order_required",
        "limit_required",
        "time_grain_required",
    )
    return {key: intent_output.initial_shape[key].value for key in keys if key in intent_output.initial_shape}


def _input_context(lexer_trace: LexerTrace, intent_output: IntentOutput) -> dict[str, Any]:
    return {
        "mentions": [mention.to_dict() for mention in lexer_trace.mentions],
        "context_signals": [signal.to_dict() for signal in lexer_trace.context_signals],
        "shape_signals": [signal.to_dict() for signal in lexer_trace.shape_signals],
        "intent": _intent_summary(intent_output),
        "initial_shape": _shape_summary(intent_output),
        "planning_prompt_text": _planning_prompt_text(intent_output),
    }


def _planning_prompt_text(intent_output: IntentOutput) -> str:
    if intent_output.planning_prompt_text.strip():
        return intent_output.planning_prompt_text.strip()
    return "用户想提出一个查询问题，但意图识别阶段没有给出更具体的中文问题类型说明。请仅根据问题文本和候选片段判断后续语义规划需要关注哪些对象。"


def _candidate_list(candidates: tuple[ObjectCandidate, ...]) -> str:
    rows: list[str] = []
    for candidate in candidates:
        rows.append(f'- {candidate.candidate_id}："{candidate.surface}"。上下文：{_candidate_context(candidate)}')
    return "\n".join(rows)


def _candidate_context(candidate: ObjectCandidate) -> str:
    fragments: list[str] = []
    for evidence in candidate.evidence:
        if evidence.type == "nearby_value":
            fragments.append(f'"{evidence.text}"修饰它')
        elif evidence.type == "nearby_relation":
            fragments.append(f'附近出现路径关系词"{evidence.text}"，它可能参与路径连接')
        elif evidence.type == "nearby_attribute":
            fragments.append(f'附近出现字段"{evidence.text}"')
        elif evidence.type == "projection_marker":
            fragments.append("它位于返回字段区域附近")
        elif evidence.type == "role_surface":
            fragments.append("它表示路径里的角色对象")
        elif evidence.type == "owner_attribute":
            fragments.append(f'字段"{evidence.text}"指向该对象')
        elif evidence.type == "owner_value":
            fragments.append(f'取值"{evidence.text}"限定该对象')
        elif evidence.type == "proximal_modifier":
            fragments.append(f'上下文信号"{evidence.text}"支持它')
        elif evidence.type == "shape_signal":
            fragments.append(f'形态信号"{evidence.text}"支持它')
    return "，".join(fragments) if fragments else "无额外上下文"


def _inferred_owner_classes(mention: Any) -> tuple[tuple[str, str], ...]:
    metadata = mention.metadata if isinstance(mention.metadata, dict) else {}
    result: list[tuple[str, str]] = []
    if mention.mention_type == "ATTRIBUTE":
        for class_id in _attribute_owner_classes(mention, metadata):
            result.append((class_id, "owner_attribute"))
    elif mention.mention_type == "VALUE":
        attribute = metadata.get("constrains_field") or metadata.get("constrains_attribute")
        if isinstance(attribute, str) and "." in attribute:
            result.append((attribute.split(".", 1)[0], "owner_value"))
    return tuple((class_id, evidence_type) for class_id, evidence_type in result if class_id)


def _attribute_owner_classes(mention: Any, metadata: dict[str, Any]) -> tuple[str, ...]:
    candidate_refs = metadata.get("candidate_refs")
    if isinstance(candidate_refs, (list, tuple)) and len(candidate_refs) != 1:
        return ()
    owners: list[str] = []
    parent_object = metadata.get("parent_object")
    if isinstance(parent_object, str) and parent_object:
        owners.append(parent_object)
    belongs_to_hint = metadata.get("belongs_to_hint")
    if isinstance(belongs_to_hint, (list, tuple)):
        owners.extend(str(item) for item in belongs_to_hint if str(item) and not str(item).startswith("REL_"))
    canonical_id = str(getattr(mention, "canonical_id", "") or "")
    if "." in canonical_id:
        owners.append(canonical_id.split(".", 1)[0])
    return tuple(dict.fromkeys(owners))


def _candidate_class_id(candidate: ObjectCandidate) -> str | None:
    inferred = candidate.metadata.get("inferred_class_id")
    if isinstance(inferred, str) and inferred:
        return inferred
    if candidate.mention_type == "OBJECT":
        ref = next((item for item in candidate.candidate_refs if "." not in item), "")
        return ref or candidate.lexical_canonical_id
    return None


def _represented_classes_for_candidate(candidate: ObjectCandidate) -> tuple[str, ...]:
    if candidate.mention_type == "OBJECT":
        class_id = _candidate_class_id(candidate)
        return (class_id,) if class_id else ()
    if candidate.mention_type != "RELATION":
        return ()
    metadata = candidate.metadata if isinstance(candidate.metadata, dict) else {}
    classes: list[str] = []
    for key in ("target_class", "range_class", "range"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            classes.append(value)
    return tuple(dict.fromkeys(classes))


def _class_surface(class_id: str) -> str:
    return {
        "Service": "服务",
        "Tunnel": "隧道",
        "NetworkElement": "网元",
        "Port": "端口",
        "Protocol": "协议",
        "Fiber": "光纤",
        "Link": "链路",
    }.get(class_id, class_id)


def _input_evidence_list(candidates: tuple[ObjectCandidate, ...], lexer_trace: LexerTrace) -> str:
    rows = [
        f"{evidence.evidence_id}: type={evidence.type}, text={evidence.text}, span=[{evidence.span[0]},{evidence.span[1]}], candidate_id={candidate.candidate_id}"
        for candidate in candidates
        for evidence in candidate.evidence
    ]
    for signal in (*lexer_trace.context_signals, *lexer_trace.shape_signals):
        rows.append(
            f"{signal.signal_id}: type={signal.signal_type}, text={signal.text}, span=[{signal.span_start},{signal.span_end}]"
        )
    return "\n".join(rows)


def _stable_id_part(value: str) -> str:
    normalized = []
    for char in value:
        if char.isalnum():
            normalized.append(char.lower())
        else:
            normalized.append("_")
    return "".join(normalized).strip("_") or "mention"


def _parse_object_role_selection_response(raw_response: str) -> dict[str, Any]:
    selected_objects: list[dict[str, Any]] = []
    clarification: dict[str, Any] | None = None
    parse_error: ObjectRoleSelectionValidationError | None = None
    for line in raw_response.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("需要澄清"):
            reason = line.split("：", 1)[1].strip() if "：" in line else line.removeprefix("需要澄清").strip(" :：")
            clarification = {"reason": reason or "候选片段不足以判断。", "blocking_evidence": []}
            continue
        match = re.search(r"选择\s*(SM\d+)\s*[：:]\s*([^。\n]+)(?:。|\.)?\s*理由\s*[：:]\s*(.*)", line)
        if not match:
            parse_error = ObjectRoleSelectionValidationError(f"unrecognized object role selection line: {line}")
            break
        roles = [item.strip(" ，、,") for item in re.split(r"[、,，]", match.group(2)) if item.strip(" ，、,")]
        selected_objects.append(
            {
                "candidate_id": match.group(1),
                "roles": roles,
                "reason": match.group(3).strip(),
            }
        )
    if clarification is not None and not selected_objects:
        return {"decision": "clarify", "selected_objects": [], "clarification": clarification}
    if selected_objects:
        return {"decision": "accept", "selected_objects": selected_objects, "clarification": None}
    if parse_error is not None:
        raise parse_error
    raise ObjectRoleSelectionValidationError("object role selection output is empty")
