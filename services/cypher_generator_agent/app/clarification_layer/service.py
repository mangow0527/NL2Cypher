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
        no_option_reason = _no_option_reason(raw, failure, options, reason_code)
        normalized = {
            "core_question": _core_question(raw, core_question, original_question),
            "source_step": source_step,
            "reason_code": reason_code,
            "reason": reason,
            "missing_information": _missing_information(raw, reason_code),
            "stage_params": _stage_params(raw, failure),
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
        "MISSING_PROJECTION_TARGET": "用户需要明确要返回哪个字段或对象。",
        "MISSING_METRIC_TARGET": "用户需要明确要统计服务、隧道、网元、端口或其他对象。",
        "SEMANTIC_ATTRIBUTE_OWNER_INVALID": "用户需要确认非法属性应改为查询哪个相关对象的属性。",
    }.get(reason_code, "用户需要补充当前缺失的判断信息。")


def _stage_params(payload: dict[str, Any], failure: dict[str, Any]) -> dict[str, Any]:
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
    options = payload.get("options")
    if isinstance(options, list) and options:
        return f"{payload['reason']}请确认：{'、'.join(str(item) for item in options)}。"
    return f"{payload['reason']}请补充说明。"
