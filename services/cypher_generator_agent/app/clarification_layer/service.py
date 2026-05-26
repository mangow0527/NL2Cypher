from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.cypher_generator_agent.app.clarification_layer.errors import ClarificationNeeded
from services.cypher_generator_agent.app.infrastructure.llm_client import OpenAICompatibleCompletionClient
from services.cypher_generator_agent.app.ontology_layer.prompts import BoundedLLMSelector, PromptRegistry


@dataclass(frozen=True)
class ClarificationQuestionService:
    llm_selector: object | None = None

    @classmethod
    def from_default_resources(cls) -> "ClarificationQuestionService":
        client = OpenAICompatibleCompletionClient.from_environment()
        if client is None:
            return cls()
        return cls(llm_selector=BoundedLLMSelector(registry=PromptRegistry.default(), client=client))

    def build(
        self,
        exc: ClarificationNeeded,
        *,
        original_question: str,
        core_question: str | None = None,
    ) -> dict[str, Any]:
        raw = dict(exc.clarification)
        failure = _primary_failure(raw)
        source_step = _source_step(exc.stage, raw)
        reason_code = _reason_code(raw, failure)
        reason = _reason(raw, failure, exc.message)
        options = _options(raw, failure)
        trace_context = _trace_context(
            exc.partial_trace,
            raw,
            failure,
            reason_code,
            original_question=_core_question(raw, core_question, original_question),
        )
        if not options:
            options = list(trace_context.get("options", []))
        binding_question = _binding_suggested_question(raw, failure, options, reason_code)
        no_option_reason = _no_option_reason(raw, failure, options, reason_code)
        normalized = {
            "core_question": _core_question(raw, core_question, original_question),
            "source_step": source_step,
            "reason_code": reason_code,
            "reason": reason,
            "missing_information": trace_context.get("missing_information") or _missing_information(raw, reason_code),
            "business_context": trace_context.get("business_context") or "无额外业务上下文。",
            "failure_focus": _binding_failure_focus(raw, failure, options, reason_code) or trace_context.get("failure_focus") or reason,
            "suggested_question": binding_question or trace_context.get("suggested_question") or "",
            "stage_params": _stage_params(raw, failure, trace_context),
            "options": options,
            "no_option_reason": no_option_reason,
            "raw_clarification": raw,
        }
        wording = self._wording(normalized)
        normalized["user_message"] = wording["user_message"]
        normalized["question_zh"] = wording["user_message"]
        normalized["source_stage"] = source_step
        normalized["expected_answer_type"] = "single_choice" if normalized["options"] else "free_text"
        if wording.get("llm_raw_output") is not None:
            normalized["llm_raw_output"] = wording["llm_raw_output"]
        if wording.get("llm_prompt_name") is not None:
            normalized["llm_prompt_name"] = wording["llm_prompt_name"]
        if wording.get("llm_user_message_rejected") is not None:
            normalized["llm_user_message_rejected"] = wording["llm_user_message_rejected"]
        return normalized

    def _wording(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.llm_selector is None:
            return {"user_message": _fallback_user_message(payload)}
        result = self.llm_selector.select(
            "clarification_wording",
            {
                "question": payload["core_question"],
                "source_step": payload["source_step"],
                "reason_code": payload["reason_code"],
                "failure_reason": payload["reason"],
                "missing_information": payload["missing_information"],
                "business_context": payload["business_context"],
                "failure_focus": payload["failure_focus"],
                "suggested_question": payload["suggested_question"] or "无",
                "stage_params": _format_stage_params(payload["stage_params"]),
                "option_list_with_ids": _option_lines(payload["options"]),
                "no_option_reason": payload["no_option_reason"] or "不适用，已提供固定选项。",
            },
        )
        parsed = getattr(result, "parsed", None)
        user_message = ""
        if isinstance(parsed, dict):
            user_message = str(parsed.get("user_message") or "").strip()
        if not user_message:
            user_message = str(getattr(result, "raw_response", "")).strip()
        if _is_unhelpful_wording(user_message) and payload.get("suggested_question"):
            return {
                "user_message": str(payload["suggested_question"]),
                "llm_raw_output": getattr(result, "raw_response", None),
                "llm_prompt_name": getattr(result, "prompt_name", None),
                "llm_user_message_rejected": user_message,
            }
        if _is_misaligned_binding_wording(user_message, payload) and payload.get("suggested_question"):
            return {
                "user_message": str(payload["suggested_question"]),
                "llm_raw_output": getattr(result, "raw_response", None),
                "llm_prompt_name": getattr(result, "prompt_name", None),
                "llm_user_message_rejected": user_message,
            }
        return {
            "user_message": user_message or _fallback_user_message(payload),
            "llm_raw_output": getattr(result, "raw_response", None),
            "llm_prompt_name": getattr(result, "prompt_name", None),
        }


def _primary_failure(payload: dict[str, Any]) -> dict[str, Any]:
    precheck = payload.get("precheck_result")
    if isinstance(precheck, dict):
        failures = precheck.get("failures")
        if isinstance(failures, list):
            for item in failures:
                if isinstance(item, dict):
                    return dict(item)
    return {}


def _source_step(stage: str, payload: dict[str, Any]) -> str:
    source_step = payload.get("source_step")
    if isinstance(source_step, str) and source_step:
        return source_step
    source_stage = payload.get("source_stage")
    if isinstance(source_stage, str) and source_stage:
        return f"{stage}.{source_stage}"
    return stage


def _reason_code(payload: dict[str, Any], failure: dict[str, Any]) -> str:
    for value in (payload.get("reason_code"), failure.get("reason_code"), failure.get("type")):
        if isinstance(value, str) and value:
            return value
    return "CLARIFICATION_REQUIRED"


def _reason(payload: dict[str, Any], failure: dict[str, Any], fallback: str) -> str:
    for value in (payload.get("reason"), failure.get("message"), payload.get("user_message"), fallback):
        if isinstance(value, str) and value:
            return value
    return "当前信息不足，需要用户补充。"


def _missing_information(payload: dict[str, Any], reason_code: str) -> str:
    value = payload.get("missing_information")
    if isinstance(value, str) and value:
        return value
    return {
        "intent_not_identified": "用户需要明确想查询明细、路径、统计、对比还是其他答案形态。",
        "missing_object_candidate": "用户需要明确后续语义规划要关注的对象。",
        "ambiguous_path": "用户需要确认对象之间按哪条业务关系连接。",
        "AMBIGUOUS_PATH": "用户需要确认对象之间按哪条业务关系连接。",
        "AMBIGUOUS_COREFERENCE": "用户需要确认两个对象是否指向同一个业务对象。",
        "AMBIGUOUS_ATTRIBUTE_BINDING": "用户需要确认字段或条件属于哪个对象。",
        "ambiguous_attribute_binding": "用户需要确认字段或条件属于哪个对象。",
        "invalid_llm_binding": "用户需要确认字段或条件属于哪个对象。",
        "MISSING_PROJECTION_TARGET": "用户需要明确要返回哪个字段或对象。",
        "MISSING_METRIC_TARGET": "用户需要明确要统计服务、隧道、网元、端口或其他对象。",
        "SEMANTIC_ATTRIBUTE_OWNER_INVALID": "用户需要确认非法属性应改为查询哪个相关对象的属性。",
    }.get(reason_code, "用户需要补充当前缺失的判断信息。")


def _binding_suggested_question(
    payload: dict[str, Any],
    failure: dict[str, Any],
    options: list[str],
    reason_code: str,
) -> str:
    if not options or not _is_attribute_binding_reason(reason_code):
        return ""
    surface = _binding_surface(payload, failure, options)
    owners = _binding_option_owners(options)
    if surface and len(owners) == 2:
        return f"你想把“{surface}”理解为{owners[0]}的{surface}，还是{owners[1]}的{surface}？"
    if surface and len(owners) > 2:
        owner_text = "、".join(owners[:-1]) + f"还是{owners[-1]}"
        return f"你想把“{surface}”绑定到哪个对象：{owner_text}？"
    if len(options) == 2:
        return f"你想选择“{options[0]}”，还是“{options[1]}”？"
    return f"你想选择哪一种字段含义：{'、'.join(options)}？"


def _binding_failure_focus(
    payload: dict[str, Any],
    failure: dict[str, Any],
    options: list[str],
    reason_code: str,
) -> str:
    if not options or not _is_attribute_binding_reason(reason_code):
        return ""
    surface = _binding_surface(payload, failure, options)
    owners = _binding_option_owners(options)
    if surface and owners:
        return f"字段“{surface}”可能属于多个对象：{'、'.join(owners)}。"
    return "字段或条件存在多个可选归属对象。"


def _is_attribute_binding_reason(reason_code: str) -> bool:
    normalized = reason_code.strip().lower()
    return normalized in {"invalid_llm_binding", "ambiguous_attribute_binding"}


def _binding_surface(payload: dict[str, Any], failure: dict[str, Any], options: list[str]) -> str:
    for value in (payload.get("surface"), failure.get("surface")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    for option in options:
        if "的" in option:
            surface = option.rsplit("的", 1)[-1].strip()
            if surface:
                return surface
        if "->" in option:
            surface = option.split("->", 1)[0].strip()
            if surface:
                return surface
    return ""


def _binding_option_owners(options: list[str]) -> list[str]:
    owners: list[str] = []
    for option in options:
        owner = ""
        if "的" in option:
            owner = option.split("的", 1)[0].strip()
        elif "->" in option:
            right = option.split("->", 1)[1].strip()
            owner = _class_label(right.split(".", 1)[0].strip())
        if owner and owner not in owners:
            owners.append(owner)
    return owners


def _stage_params(
    payload: dict[str, Any],
    failure: dict[str, Any],
    trace_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stage_params = payload.get("stage_params")
    if isinstance(stage_params, dict):
        result = dict(stage_params)
    else:
        result = {}
    if failure:
        result.setdefault("failed_check", failure.get("check"))
        result.setdefault("invalid_element", failure.get("attribute") or failure.get("edge") or failure.get("node"))
    for key in ("blocking_evidence", "candidate_intents", "failed_fields"):
        if key in payload:
            result.setdefault(key, payload[key])
    if trace_context:
        for key in ("failed_relations", "recommended_business_path"):
            if trace_context.get(key):
                result.setdefault(key, trace_context[key])
    return {key: value for key, value in result.items() if value is not None}


def _options(payload: dict[str, Any], failure: dict[str, Any]) -> list[str]:
    values = payload.get("options")
    if not values:
        values = payload.get("suggested_rewrites")
    if not values:
        values = payload.get("candidate_intents")
    if not values:
        values = failure.get("clarification_options")
    if not values:
        values = failure.get("options")
    if not isinstance(values, list):
        return []
    options: list[str] = []
    for item in values:
        label = _option_label(item)
        if label and label not in options:
            options.append(label)
    return options


def _no_option_reason(
    payload: dict[str, Any],
    failure: dict[str, Any],
    options: list[str],
    reason_code: str,
) -> str | None:
    if options:
        return None
    for value in (payload.get("no_option_reason"), failure.get("no_option_reason")):
        if isinstance(value, str) and value:
            return value
    return {
        "object_role_llm_unavailable": "当前环境缺少对象角色选择 LLM，无法列出可靠固定选项。",
        "object_role_validation_failed": "对象角色选择结果未通过校验，无法列出可靠固定选项。",
        "path_selection_validation_failed": "路径选择结果未通过校验，无法列出可靠固定选项。",
        "MISSING_METRIC_TARGET": "当前 logical plan 中没有可统计的本体对象。",
        "SEMANTIC_ATTRIBUTE_OWNER_INVALID": "语义校验失败项没有提供可安全替换的固定候选。",
        "CLARIFICATION_REQUIRED": "当前澄清来源没有提供固定候选。",
    }.get(reason_code, "当前澄清来源没有提供固定候选。")


def _option_label(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        intent_label = _intent_option_label(item)
        if intent_label:
            return intent_label
        for key in ("label", "summary", "description", "text", "option_id"):
            value = item.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def _intent_option_label(item: dict[str, Any]) -> str:
    primary = item.get("primary")
    secondary = item.get("secondary")
    if isinstance(primary, str) and isinstance(secondary, str) and primary and secondary:
        return f"{primary} / {secondary}"
    if isinstance(primary, str) and primary:
        return primary
    if isinstance(secondary, str) and secondary:
        return secondary
    return ""


def _core_question(payload: dict[str, Any], core_question: str | None, original_question: str) -> str:
    value = payload.get("core_question")
    if isinstance(value, str) and value:
        return value
    if core_question:
        return core_question
    return original_question


def _format_stage_params(stage_params: dict[str, Any]) -> str:
    if not stage_params:
        return "无"
    return "\n".join(f"- {key}: {value}" for key, value in stage_params.items())


def _option_lines(options: list[str]) -> str:
    if not options:
        return "无"
    return "\n".join(f"O{index}: {option}" for index, option in enumerate(options, start=1))


def _fallback_user_message(payload: dict[str, Any]) -> str:
    suggested_question = payload.get("suggested_question")
    if isinstance(suggested_question, str) and suggested_question:
        return suggested_question
    options = payload.get("options")
    if isinstance(options, list) and options:
        return f"{payload['reason']}请确认：{'、'.join(str(item) for item in options)}。"
    return f"{payload['reason']}请补充说明。"


def _trace_context(
    partial_trace: dict[str, Any],
    payload: dict[str, Any],
    failure: dict[str, Any],
    reason_code: str,
    *,
    original_question: str,
) -> dict[str, Any]:
    if not isinstance(partial_trace, dict) or not partial_trace:
        return {}
    failed_checks = _failed_checks(payload, failure, partial_trace)
    failed_relations = _failed_relations(failed_checks)
    mentions = _lexer_mentions(partial_trace)
    selected_segments = _selected_path_segments(partial_trace)
    recommended_path = _recommended_path(selected_segments, failed_relations)
    suspicious_mentions = _mentions_for_relations(mentions, failed_relations)

    lines: list[str] = [f"用户原问题：{original_question}"]
    mention_lines = _mention_context_lines(mentions, failed_relations)
    if mention_lines:
        lines.append("系统识别到的业务片段：")
        lines.extend(mention_lines)
    selected_lines = _selected_path_lines(selected_segments)
    if selected_lines:
        lines.append("当前已选择的业务连接：")
        lines.extend(selected_lines)
    failure_focus = _failure_focus(failed_checks, suspicious_mentions)
    if failure_focus:
        lines.append(f"当前失败点：{failure_focus}")
    if recommended_path:
        lines.append(f"可优先确认的业务路径：{recommended_path}")

    context: dict[str, Any] = {
        "business_context": "\n".join(lines),
        "failure_focus": failure_focus or "",
        "failed_relations": list(failed_relations),
    }
    if recommended_path:
        context["recommended_business_path"] = recommended_path
        context["suggested_question"] = f"你是想按“{recommended_path}”这条业务路径查询吗？"
        if reason_code.startswith("SEMANTIC_") or reason_code == "SEMANTIC_VALIDATION_FAILED":
            context["missing_information"] = "用户需要确认系统当前理解的业务连接路径是否正确。"
            context["options"] = [
                f"按 {recommended_path} 查询",
                _negative_path_option(suspicious_mentions),
            ]
    return context


def _failed_checks(
    payload: dict[str, Any],
    failure: dict[str, Any],
    partial_trace: dict[str, Any],
) -> list[dict[str, Any]]:
    values = payload.get("failed_checks")
    if isinstance(values, list):
        return [dict(item) for item in values if isinstance(item, dict)]
    if failure:
        return [dict(failure)]
    validator = partial_trace.get("validator")
    if isinstance(validator, dict):
        checks = validator.get("checks")
        if isinstance(checks, list):
            return [
                dict(item)
                for item in checks
                if isinstance(item, dict) and item.get("accepted") is False
            ]
    return []


def _failed_relations(failed_checks: list[dict[str, Any]]) -> tuple[str, ...]:
    relations: list[str] = []
    for check in failed_checks:
        value = check.get("relation") or check.get("edge")
        if isinstance(value, str) and value and value not in relations:
            relations.append(value)
    return tuple(relations)


def _lexer_mentions(partial_trace: dict[str, Any]) -> list[dict[str, Any]]:
    lexer = partial_trace.get("lexer")
    if not isinstance(lexer, dict):
        return []
    mentions = lexer.get("mentions")
    if not isinstance(mentions, list):
        return []
    return [dict(item) for item in mentions if isinstance(item, dict)]


def _mentions_for_relations(mentions: list[dict[str, Any]], relation_ids: tuple[str, ...]) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    relation_set = set(relation_ids)
    for mention in mentions:
        relation_id = _mention_relation_id(mention)
        if relation_id in relation_set:
            matched.append(mention)
    return matched


def _mention_context_lines(mentions: list[dict[str, Any]], failed_relations: tuple[str, ...]) -> list[str]:
    lines: list[str] = []
    failed_set = set(failed_relations)
    for mention in mentions:
        surface = str(mention.get("surface") or "").strip()
        mention_type = str(mention.get("mention_type") or "").strip()
        canonical_id = str(mention.get("canonical_id") or "").strip()
        if not surface or mention_type not in {"OBJECT", "RELATION"}:
            continue
        if mention_type == "OBJECT":
            label = f"{_class_label(canonical_id)}对象"
            lines.append(f"- “{surface}” -> {label}")
            continue
        relation_id = _mention_relation_id(mention)
        relation_label = _relation_label(relation_id or canonical_id)
        endpoint_label = _mention_join_path_label(mention)
        failed_note = "，这是当前失败点，可能需要用户确认" if relation_id in failed_set else ""
        if endpoint_label:
            lines.append(f"- “{surface}” -> {relation_label}（{endpoint_label}）{failed_note}")
        else:
            lines.append(f"- “{surface}” -> {relation_label}{failed_note}")
    return lines


def _mention_relation_id(mention: dict[str, Any]) -> str:
    canonical_id = str(mention.get("canonical_id") or "")
    if canonical_id.startswith("REL_"):
        return canonical_id.removeprefix("REL_")
    metadata = mention.get("metadata")
    if isinstance(metadata, dict):
        join_path = metadata.get("join_path")
        if isinstance(join_path, list) and join_path:
            first = join_path[0]
            if isinstance(first, dict) and isinstance(first.get("edge"), str):
                return str(first["edge"])
    return canonical_id


def _mention_join_path_label(mention: dict[str, Any]) -> str:
    metadata = mention.get("metadata")
    if not isinstance(metadata, dict):
        return ""
    join_path = metadata.get("join_path")
    if not isinstance(join_path, list) or not join_path:
        return ""
    labels: list[str] = []
    for item in join_path:
        if not isinstance(item, dict):
            continue
        from_class = item.get("from")
        to_class = item.get("to")
        edge = item.get("edge")
        if isinstance(from_class, str) and isinstance(to_class, str) and isinstance(edge, str):
            labels.append(f"{_class_label(from_class)} -> {_class_label(to_class)}")
    return "；".join(labels)


def _selected_path_segments(partial_trace: dict[str, Any]) -> list[dict[str, Any]]:
    path_selection = partial_trace.get("ontology_path_selection")
    if not isinstance(path_selection, dict):
        return []
    candidate_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    candidates = path_selection.get("candidate_paths")
    if isinstance(candidates, list):
        for candidate in candidates:
            if (
                isinstance(candidate, dict)
                and isinstance(candidate.get("request_id"), str)
                and isinstance(candidate.get("path_id"), str)
            ):
                candidate_by_key[(str(candidate["request_id"]), str(candidate["path_id"]))] = candidate
    request_by_id: dict[str, dict[str, Any]] = {}
    requests = path_selection.get("path_requests")
    if isinstance(requests, list):
        for request in requests:
            if isinstance(request, dict) and isinstance(request.get("request_id"), str):
                request_by_id[str(request["request_id"])] = request
    selected = path_selection.get("selected_paths")
    if not isinstance(selected, list):
        return []
    segments: list[dict[str, Any]] = []
    for item in selected:
        if not isinstance(item, dict):
            continue
        request_id = str(item.get("request_id") or "")
        path_id = str(item.get("path_id") or "")
        candidate = candidate_by_key.get((request_id, path_id), {})
        request = request_by_id.get(request_id, {})
        chain = item.get("relation_chain") or candidate.get("relation_chain") or []
        if not isinstance(chain, list):
            chain = []
        from_class = candidate.get("from_class") or request.get("from_class")
        to_class = candidate.get("to_class") or request.get("to_class")
        relation_chain = [str(value) for value in chain if isinstance(value, str) and value]
        if isinstance(from_class, str) and isinstance(to_class, str) and relation_chain:
            segments.append(
                {
                    "from_class": from_class,
                    "to_class": to_class,
                    "relation_chain": relation_chain,
                }
            )
    return segments


def _selected_path_lines(segments: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for segment in segments:
        relation_text = " -> ".join(_relation_label(item) for item in segment["relation_chain"])
        lines.append(
            f"- {_class_label(segment['from_class'])} -> "
            f"{relation_text} -> {_class_label(segment['to_class'])}"
        )
    return lines


def _recommended_path(segments: list[dict[str, Any]], failed_relations: tuple[str, ...]) -> str:
    failed_set = set(failed_relations)
    usable = [segment for segment in segments if not failed_set.intersection(segment["relation_chain"])]
    if not usable:
        return ""
    chain: list[str] = []
    last_class = ""
    for segment in usable:
        from_class = str(segment["from_class"])
        to_class = str(segment["to_class"])
        relations = [str(item) for item in segment["relation_chain"]]
        if not chain:
            chain.append(_class_label(from_class))
        elif last_class and from_class != last_class:
            continue
        chain.extend(_relation_phrase(item) for item in relations)
        last_class = to_class
    if len(chain) < 2:
        return ""
    return " -> ".join(chain)


def _failure_focus(
    failed_checks: list[dict[str, Any]],
    suspicious_mentions: list[dict[str, Any]],
) -> str:
    if suspicious_mentions:
        mention = suspicious_mentions[0]
        surface = str(mention.get("surface") or "")
        relation_id = _mention_relation_id(mention)
        return f"系统把“{surface}”理解成“{_relation_label(relation_id)}”，但这条关系没有通过当前查询校验。"
    if failed_checks:
        first = failed_checks[0]
        relation = first.get("relation") or first.get("edge")
        check = first.get("check")
        if isinstance(relation, str):
            return f"关系“{_relation_label(relation)}”没有通过 {check} 校验。"
    return ""


def _negative_path_option(suspicious_mentions: list[dict[str, Any]]) -> str:
    if suspicious_mentions:
        surface = str(suspicious_mentions[0].get("surface") or "").strip()
        if surface:
            return f"不是，请重新说明“{surface}”指哪种业务关系"
    return "不是，请重新说明要按哪条业务关系连接"


def _is_unhelpful_wording(message: str) -> bool:
    text = message.strip()
    if not text:
        return True
    generic_markers = (
        "缺失的条件信息",
        "当前缺失",
        "缺失信息",
        "判断当前",
        "当前信息不足",
        "补充说明",
        "补充这个查询缺少的信息",
    )
    return any(marker in text for marker in generic_markers)


def _is_misaligned_binding_wording(message: str, payload: dict[str, Any]) -> bool:
    text = message.strip()
    if not text or not _is_attribute_binding_reason(str(payload.get("reason_code") or "")):
        return False
    options = payload.get("options")
    if not isinstance(options, list) or not options:
        return False
    surface = _binding_surface(payload, {}, [str(option) for option in options])
    asks_path = "路径" in text or "业务关系" in text or ("按" in text and "查询" in text)
    return bool(asks_path and surface and surface not in text)


def _class_label(class_id: str) -> str:
    return {
        "Service": "服务",
        "Tunnel": "隧道",
        "NetworkElement": "网元",
        "Port": "端口",
        "Fiber": "光纤",
        "Link": "链路",
        "Protocol": "协议",
    }.get(class_id, class_id)


def _relation_label(relation_id: str) -> str:
    return {
        "SERVICE_USES_TUNNEL": "服务使用隧道",
        "TUNNEL_SRC": "隧道源端网元",
        "TUNNEL_DST": "隧道宿端网元",
        "FIBER_SRC": "光纤源端口",
        "FIBER_DST": "光纤目的端口",
        "HAS_PORT": "网元拥有端口",
    }.get(relation_id.removeprefix("REL_"), relation_id.removeprefix("REL_"))


def _relation_phrase(relation_id: str) -> str:
    return {
        "SERVICE_USES_TUNNEL": "使用的隧道",
        "TUNNEL_SRC": "源端网元",
        "TUNNEL_DST": "宿端网元",
        "FIBER_SRC": "源端口",
        "FIBER_DST": "目的端口",
        "HAS_PORT": "端口",
    }.get(relation_id.removeprefix("REL_"), _relation_label(relation_id))
