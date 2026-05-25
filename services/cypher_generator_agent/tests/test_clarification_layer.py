from __future__ import annotations

import json

import pytest

from services.cypher_generator_agent.app.api.models import QAQuestionRequest
from services.cypher_generator_agent.app.api.service import CypherGeneratorAgentService
from services.cypher_generator_agent.app.clarification_layer.errors import ClarificationNeeded
from services.cypher_generator_agent.app.clarification_layer.service import ClarificationQuestionService
from services.cypher_generator_agent.app.intent_layer.models import Intent, IntentOutput
from services.cypher_generator_agent.app.ontology_layer.assets import OntologyAssets
from services.cypher_generator_agent.app.ontology_layer.models import ValidatorTrace
from services.cypher_generator_agent.app.runtime_pipeline import OntologyGenerationPipeline
from services.cypher_generator_agent.tests.test_ontology_generation_pipeline import _pipeline as _fixture_pipeline


class _FakeClarificationSelector:
    def __init__(self, message: str = "请确认你想查询哪个对象？") -> None:
        self.message = message
        self.calls: list[dict[str, object]] = []

    def select(self, prompt_name: str, variables: dict[str, object]):
        self.calls.append({"prompt_name": prompt_name, **variables})

        class Selection:
            raw_response = self.message
            parsed = {"user_message": self.message}
            prompt_name = "clarification_wording"
            prompt_version = "v1.0.0"
            prompt_hash = "hash"
            rendered_prompt_hash = "rendered"

        return Selection()


def test_clarification_service_normalizes_preprocessing_payload_and_calls_llm() -> None:
    selector = _FakeClarificationSelector("请重新描述一个明确的查询问题。")
    service = ClarificationQuestionService(llm_selector=selector)
    exc = ClarificationNeeded(
        stage="preprocessing",
        message="question preprocessing rejected input",
        clarification={
            "source_stage": "clarity_gate",
            "reason_code": "query_intent_missing",
            "user_message": "缺少查询意图。",
            "suggested_rewrites": ["查询金牌服务使用的隧道名称"],
        },
    )

    payload = service.build(exc, original_question="Gold 服务最近有点慢，帮我看看")

    assert payload["core_question"] == "Gold 服务最近有点慢，帮我看看"
    assert payload["source_step"] == "preprocessing.clarity_gate"
    assert payload["reason_code"] == "query_intent_missing"
    assert payload["user_message"] == "请重新描述一个明确的查询问题。"
    assert selector.calls[0]["prompt_name"] == "clarification_wording"
    assert "查询金牌服务使用的隧道名称" in str(selector.calls[0]["option_list_with_ids"])


def test_clarification_service_exposes_llm_wording_as_display_question() -> None:
    selector = _FakeClarificationSelector("你想按服务到源网元，还是服务到目的网元来查询？")
    service = ClarificationQuestionService(llm_selector=selector)
    exc = ClarificationNeeded(
        stage="step_3_3",
        message="ontology path selection needs clarification",
        clarification={
            "core_question": "查询服务相关网元",
            "source_step": "step_3_3_ontology_path_selection",
            "reason_code": "ambiguous_path",
            "reason": "存在多条路径。",
            "options": ["服务到源网元", "服务到目的网元"],
        },
    )

    payload = service.build(exc, original_question="查询服务相关网元")

    assert payload["user_message"] == "你想按服务到源网元，还是服务到目的网元来查询？"
    assert payload["question_zh"] == payload["user_message"]
    assert payload["source_stage"] == "step_3_3_ontology_path_selection"
    assert payload["expected_answer_type"] == "single_choice"


def test_clarification_service_extracts_shape_precheck_failure() -> None:
    selector = _FakeClarificationSelector("你想把名称绑定到服务还是隧道？")
    service = ClarificationQuestionService(llm_selector=selector)
    exc = ClarificationNeeded(
        stage="step_3_6",
        message="binding candidates are not distinguishable",
        clarification={
            "precheck_result": {
                "passed": False,
                "failures": [
                    {
                        "check": "blocking_unresolved_empty",
                        "reason_code": "AMBIGUOUS_ATTRIBUTE_BINDING",
                        "message": "名称可以属于服务或隧道。",
                        "clarification_options": [
                            {"option_id": "O1", "label": "服务名称"},
                            {"option_id": "O2", "label": "隧道名称"},
                        ],
                    }
                ],
            }
        },
    )

    payload = service.build(exc, original_question="查询服务经过的隧道，返回名称", core_question="查询服务经过的隧道，返回名称")

    assert payload["source_step"] == "step_3_6"
    assert payload["reason_code"] == "AMBIGUOUS_ATTRIBUTE_BINDING"
    assert payload["stage_params"]["failed_check"] == "blocking_unresolved_empty"
    assert payload["options"] == ["服务名称", "隧道名称"]
    assert payload["user_message"] == "你想把名称绑定到服务还是隧道？"


@pytest.mark.parametrize(
    ("source_step", "reason_code", "message", "expected_missing"),
    [
        (
            "step_3_3",
            "AMBIGUOUS_PATH",
            "多个查询对象之间缺少明确连接关系，需要确认按哪条业务关系连接",
            "用户需要确认对象之间按哪条业务关系连接。",
        ),
        (
            "step_3_5",
            "MISSING_PROJECTION_TARGET",
            "当前问题需要返回字段或对象，但未能确定具体返回内容",
            "用户需要明确要返回哪个字段或对象。",
        ),
    ],
)
def test_clarification_service_normalizes_shape_precheck_slot_failures(
    source_step: str,
    reason_code: str,
    message: str,
    expected_missing: str,
) -> None:
    selector = _FakeClarificationSelector("请补充这个查询缺少的信息。")
    service = ClarificationQuestionService(llm_selector=selector)
    exc = ClarificationNeeded(
        stage="step_3_6",
        message=message,
        clarification={
            "source_step": source_step,
            "precheck_result": {
                "passed": False,
                "failures": [
                    {
                        "check": "shape_projection_consistency" if reason_code == "MISSING_PROJECTION_TARGET" else "no_cartesian_product",
                        "reason_code": reason_code,
                        "message": message,
                    }
                ],
            },
        },
    )

    payload = service.build(exc, original_question="查询服务相关信息")

    assert payload["source_step"] == source_step
    assert payload["reason_code"] == reason_code
    assert payload["missing_information"] == expected_missing
    assert selector.calls[0]["missing_information"] == expected_missing


def test_clarification_service_passes_no_option_reason_to_wording_llm() -> None:
    selector = _FakeClarificationSelector("请直接补充你最终想查询的对象或字段。")
    service = ClarificationQuestionService(llm_selector=selector)
    exc = ClarificationNeeded(
        stage="step_3_6",
        message="projection target cannot be inferred",
        clarification={
            "source_step": "step_3_5",
            "reason_code": "MISSING_PROJECTION_TARGET",
            "reason": "当前问题需要返回字段或对象，但没有可安全列出的固定候选。",
            "no_option_reason": "当前 logical plan 没有可作为返回目标的本体节点或字段候选。",
        },
    )

    payload = service.build(exc, original_question="查询相关信息")

    assert payload["options"] == []
    assert payload["expected_answer_type"] == "free_text"
    assert payload["no_option_reason"] == "当前 logical plan 没有可作为返回目标的本体节点或字段候选。"
    assert selector.calls[0]["option_list_with_ids"] == "无"
    assert selector.calls[0]["no_option_reason"] == payload["no_option_reason"]


def test_clarification_service_marks_optionful_context_without_no_option_reason() -> None:
    selector = _FakeClarificationSelector("你想返回服务、隧道还是网元？")
    service = ClarificationQuestionService(llm_selector=selector)
    exc = ClarificationNeeded(
        stage="step_3_6",
        message="projection target cannot be inferred",
        clarification={
            "source_step": "step_3_5",
            "precheck_result": {
                "passed": False,
                "failures": [
                    {
                        "check": "shape_projection_consistency",
                        "reason_code": "MISSING_PROJECTION_TARGET",
                        "message": "当前问题需要返回字段或对象，但未能确定具体返回内容",
                        "clarification_options": [
                            {"option_id": "N1", "label": "返回 Service 对象"},
                            {"option_id": "N2", "label": "返回 Tunnel 对象"},
                        ],
                    }
                ],
            },
        },
    )

    payload = service.build(exc, original_question="查询服务相关信息")

    assert payload["options"] == ["返回 Service 对象", "返回 Tunnel 对象"]
    assert payload["no_option_reason"] is None
    assert selector.calls[0]["no_option_reason"] == "不适用，已提供固定选项。"


def test_clarification_service_converts_candidate_intents_to_options() -> None:
    selector = _FakeClarificationSelector("你想查询记录明细，还是统计数量？")
    service = ClarificationQuestionService(llm_selector=selector)
    exc = ClarificationNeeded(
        stage="step_2",
        message="intent recognition needs clarification",
        clarification={
            "source_step": "step_2_intent_shape",
            "reason_code": "intent_ambiguous",
            "reason": "当前问题可能对应多个答案形态。",
            "candidate_intents": [
                {"primary": "record_retrieval_query", "secondary": "related_record_query"},
                {"primary": "metric_query", "secondary": "count_metric_query"},
            ],
        },
    )

    payload = service.build(exc, original_question="查询服务情况")

    assert payload["options"] == [
        "record_retrieval_query / related_record_query",
        "metric_query / count_metric_query",
    ]
    assert payload["no_option_reason"] is None
    assert selector.calls[0]["no_option_reason"] == "不适用，已提供固定选项。"


def test_clarification_service_normalizes_metric_target_clarification() -> None:
    selector = _FakeClarificationSelector("请明确要统计哪类对象。")
    service = ClarificationQuestionService(llm_selector=selector)
    exc = ClarificationNeeded(
        stage="step_3_6",
        message="metric query has no ontology node to count",
        clarification={
            "source_step": "step_3_6",
            "reason_code": "MISSING_METRIC_TARGET",
            "reason": "当前问题是统计类查询，但未能确定要统计的对象。",
        },
    )

    payload = service.build(exc, original_question="统计数量")

    assert payload["source_step"] == "step_3_6"
    assert payload["reason_code"] == "MISSING_METRIC_TARGET"
    assert payload["missing_information"] == "用户需要明确要统计服务、隧道、网元、端口或其他对象。"
    assert selector.calls[0]["missing_information"] == payload["missing_information"]


@pytest.mark.asyncio
async def test_api_uses_unified_clarification_wording_for_outgoing_report() -> None:
    class Pipeline:
        def generate(self, question: str, *, trace_id: str = "runtime"):
            raise ClarificationNeeded(
                stage="step_3_3",
                message="ontology path selection needs clarification",
                clarification={
                    "core_question": question,
                    "source_step": "step_3_3_ontology_path_selection",
                    "reason_code": "ambiguous_path",
                    "reason": "存在多条路径。",
                    "options": ["服务使用隧道的源网元", "服务经过路径上的网元"],
                },
                partial_trace={
                    "schema_version": "cga_trace_v2",
                    "trace_profile": "ontology",
                    "trace_id": trace_id,
                    "preprocessing": {"core_question": question},
                    "lexer": {"mentions": [{"surface": "服务"}]},
                    "intent": {"intent": {"primary": "record_retrieval_query"}},
                },
            )

    class TestingClient:
        def __init__(self) -> None:
            self.failure_payload = None

        async def submit(self, payload):
            raise AssertionError("clarification should not submit generated cypher")

        async def submit_generation_failure(self, payload):
            self.failure_payload = payload
            return {"ok": True}

    selector = _FakeClarificationSelector("你说的网元是隧道源网元，还是路径经过的网元？")
    testing_client = TestingClient()
    service = CypherGeneratorAgentService(
        testing_client=testing_client,
        pipeline=Pipeline(),  # type: ignore[arg-type]
        clarification_service=ClarificationQuestionService(llm_selector=selector),
    )

    result = await service.ingest_question(QAQuestionRequest(id="q1", question="查询服务相关网元"))

    assert result.generation_status == "clarification_required"
    clarification = testing_client.failure_payload.clarification
    assert clarification["source_step"] == "step_3_3_ontology_path_selection"
    assert clarification["core_question"] == "查询服务相关网元"
    assert clarification["user_message"] == "你说的网元是隧道源网元，还是路径经过的网元？"
    snapshot = json.loads(testing_client.failure_payload.input_prompt_snapshot)
    assert snapshot["schema_version"] == "cga_trace_v2"
    assert snapshot["trace_profile"] == "ontology"
    assert snapshot["generation_status"] == "clarification_required"
    assert snapshot["clarification"]["user_message"] == clarification["user_message"]
    assert snapshot["preprocessing"]["core_question"] == "查询服务相关网元"
    assert snapshot["lexer"]["mentions"][0]["surface"] == "服务"
    assert snapshot["intent"]["intent"]["primary"] == "record_retrieval_query"


def test_runtime_pipeline_raises_clarification_when_intent_is_unknown() -> None:
    class UnknownIntentLayer:
        def run(self, *, core_question: str, shape_signals=()):
            return IntentOutput(
                intent=Intent(
                    primary="unknown",
                    secondary="unknown",
                    source="embedding",
                    decision="clarify",
                    confidence=0.0,
                    clarify_origin="intent_recognition",
                    clarify_reason="intent_not_identified",
                    failed_fields=("primary_intent", "secondary_intent"),
                    candidate_intents=({"primary": "record_retrieval_query", "secondary": "related_record_query"},),
                ),
                planning_prompt_text="",
                initial_shape={},
                candidates=({"id": "C1", "primary": "record_retrieval_query", "secondary": "related_record_query"},),
                rule_signals_used=(),
                diagnostics={},
            )

    class ObjectRoleSelection:
        def select(self, *args, **kwargs):
            raise AssertionError("object role selection should not run when intent is unknown")

    pipeline = OntologyGenerationPipeline(
        assets=OntologyAssets.from_default_resources(),
        intent_layer=UnknownIntentLayer(),  # type: ignore[arg-type]
        object_role_selection_service=ObjectRoleSelection(),  # type: ignore[arg-type]
    )

    with pytest.raises(ClarificationNeeded) as exc_info:
        pipeline.generate("查询服务名称", trace_id="trace-intent-clarify")

    assert exc_info.value.stage == "step_2"
    assert exc_info.value.clarification["source_step"] == "step_2_intent_shape"
    assert exc_info.value.clarification["core_question"] == "查询服务名称"
    assert exc_info.value.clarification["reason_code"] == "intent_not_identified"


def test_runtime_pipeline_raises_clarification_for_semantic_validation_failure() -> None:
    class AcceptedValidator:
        def validate(self, plan):
            return ValidatorTrace(
                accepted=False,
                checks=(
                    {
                        "check": "projection_attribute_exists",
                        "attribute": "Service.ip_address",
                        "accepted": False,
                    },
                ),
            )

    pipeline = _fixture_pipeline()
    pipeline.validator = AcceptedValidator()  # type: ignore[assignment]

    with pytest.raises(ClarificationNeeded) as exc_info:
        pipeline.generate("查询金牌服务使用的隧道名称", trace_id="trace-step-4-clarify")

    assert exc_info.value.stage == "step_4"
    assert exc_info.value.clarification["source_step"] == "step_4_semantic_validation"
    assert exc_info.value.clarification["core_question"] == "查询金牌服务使用的隧道名称"
    assert exc_info.value.clarification["reason_code"] == "SEMANTIC_ATTRIBUTE_OWNER_INVALID"
