from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from services.cypher_generator_agent.app.api.main import parse_semantics
from services.cypher_generator_agent.app.api.models import SemanticParseRequest
from services.cypher_generator_agent.app.core import pipeline as pipeline_module
from services.cypher_generator_agent.app.core.pipeline import run_pipeline
from services.cypher_generator_agent.app.core.result import ClarificationRequest
from services.cypher_generator_agent.app.decomposition.models import (
    QuestionDecompositionClarification,
    QuestionDecompositionFailure,
)
from services.cypher_generator_agent.app.infrastructure.config import get_settings
from services.cypher_generator_agent.app.understanding.models import GroundedUnderstandingFailure


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"

EXPECTED_STAGES = [
    "graph_model_loader",
    "input_clarification_gate",
    "question_decomposer",
    "candidate_retrieval",
    "literal_resolver",
    "grounded_understanding",
    "semantic_binder",
    "semantic_validator",
    "dsl_builder",
    "dsl_parser",
    "cypher_compiler",
    "cypher_self_validation",
    "output",
]


def test_gold_service_question_generates_single_hop_cypher() -> None:
    output = run_pipeline(
        question="Gold 服务使用了哪些隧道",
        qa_id="gq-001",
        generation_run_id="run-gq-001",
    )

    assert output.status == "generated"
    assert output.cypher is not None
    assert "MATCH (svc:Service)-[:SERVICE_USES_TUNNEL]->(tun:Tunnel)" in output.cypher
    assert "svc.quality_of_service = 'Gold'" in output.cypher
    assert "$quality_of_service" not in output.cypher
    assert "RETURN tun.id AS tunnel_id" in output.cypher
    assert output.trace["semantic_model"]["name"] == "network_schema_v10"
    assert _compiler_parameters(output.trace)["quality_of_service"] == "Gold"
    assert "svc.quality_of_service = $quality_of_service" in _compiler_template(output.trace)
    assert _compiler_executable(output.trace) == output.cypher
    assert _stage_names(output.trace) == EXPECTED_STAGES
    assert "db_connection" not in _all_keys(output.trace)
    assert "execution_result" not in _all_keys(output.trace)


def test_multi_property_service_projection_uses_each_requested_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_decompose(question: str) -> dict[str, Any]:
        return {
            "schema_version": "question_decomposition_v1",
            "result_type": "decomposition",
            "original_question": question,
            "intent_type": "list",
            "output_shape": "rows",
            "target_concepts": ["服务", "ID", "名称", "元素类型", "服务质量等级", "带宽", "时延"],
            "relation_phrases": [],
            "literal_candidates": [],
            "literal_requests": [],
            "substantive_terms": [
                _decomp_term("服务", "projection"),
                _decomp_term("ID", "projection", attached_to="服务"),
                _decomp_term("名称", "projection", attached_to="服务"),
                _decomp_term("元素类型", "projection", attached_to="服务"),
                _decomp_term("服务质量等级", "projection", attached_to="服务"),
                _decomp_term("带宽", "projection", attached_to="服务"),
                _decomp_term("时延", "projection", attached_to="服务"),
            ],
            "stopword_terms": ["查询", "所有", "的", "和"],
            "modality_terms": [],
            "time_terms": [],
            "unparsed_terms": [],
            "coverage": {
                "substantive_terms": {"total": 7, "covered": 7, "uncovered": []},
                "stopword_terms": {"ignored": ["查询", "所有", "的", "和"]},
                "modality_terms": {"warning_only": []},
                "time_terms": {"covered": [], "unresolved": []},
                "unparsed_terms": {"unresolved": []},
                "projection_terms": {
                    "required": ["ID", "名称", "元素类型", "服务质量等级", "带宽", "时延"],
                    "covered": [],
                    "uncovered": ["ID", "名称", "元素类型", "服务质量等级", "带宽", "时延"],
                },
            },
        }

    monkeypatch.setattr(pipeline_module, "_mock_decompose", fake_decompose)

    output = run_pipeline(
        question="查询所有服务的 ID、名称、元素类型、服务质量等级、带宽和时延",
        qa_id="qa_9cfa692813d5",
        generation_run_id="run-qa_9cfa692813d5",
    )

    assert output.status == "generated"
    assert output.dsl is not None
    assert [item["property"]["name"] for item in output.dsl["projection"]["items"]] == [
        "id",
        "name",
        "elem_type",
        "quality_of_service",
        "bandwidth",
        "latency",
    ]
    assert "RETURN svc.id AS service_id" in output.cypher
    assert "svc.name AS service_name" in output.cypher
    assert "svc.elem_type AS service_elem_type" in output.cypher
    assert "svc.quality_of_service AS service_quality_of_service" in output.cypher
    assert "svc.bandwidth AS service_bandwidth" in output.cypher
    assert "svc.latency AS service_latency" in output.cypher


def test_input_clarification_gate_short_circuits_deictic_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(question: str) -> dict[str, object]:
        raise AssertionError(f"decomposer should not receive ambiguous input: {question}")

    monkeypatch.setattr(pipeline_module, "_mock_decompose", fail_if_called)

    output = run_pipeline(
        question="它最近 down 了吗",
        qa_id="input-gate",
        generation_run_id="run-input-gate",
    )

    assert output.status == "clarification_required"
    assert output.clarification is not None
    assert "它" in output.clarification.question
    assert output.cypher is None
    assert output.dsl is None
    assert _stage_names(output.trace) == ["graph_model_loader", "input_clarification_gate", "output"]


def test_pipeline_semantic_artifacts_can_be_overridden_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CYPHER_GENERATOR_AGENT_GRAPH_MODEL_PATH",
        str(FIXTURE_DIR / "network_topology_graph_model.yaml"),
    )
    monkeypatch.setenv(
        "CYPHER_GENERATOR_AGENT_VALUE_INDEX_PATH",
        str(FIXTURE_DIR / "value_index.json"),
    )
    get_settings.cache_clear()

    try:
        output = run_pipeline(
            question="Gold 服务使用了哪些隧道",
            qa_id="settings-override",
            generation_run_id="run-settings-override",
        )
    finally:
        get_settings.cache_clear()

    assert output.status == "generated"
    assert output.trace["semantic_model"]["name"] == "network_topology"
    assert _compiler_parameters(output.trace)["quality_of_service"] == "GOLD"


def test_pipeline_can_use_real_llm_mode_with_openai_compatible_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeStructuredClient:
        provider = "openai_compatible"

        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []
            self.responses = [
                {
                    "schema_version": "question_decomposition_v1",
                    "result_type": "decomposition",
                    "intent_type": "list",
                    "original_question": "Gold 服务使用了哪些隧道",
                    "target_concepts": ["服务", "隧道"],
                    "relation_phrases": ["使用隧道"],
                    "literal_candidates": [
                        {"text": "Gold", "kind_hint": "enum_or_name", "attached_to": "服务"}
                    ],
                    "substantive_terms": [
                        _decomp_term("Gold", "filter", attached_to="服务"),
                        _decomp_term("服务", "path"),
                        _decomp_term("使用", "path"),
                        _decomp_term("隧道", "projection"),
                    ],
                    "stopword_terms": [],
                    "modality_terms": [],
                    "time_terms": [],
                    "unparsed_terms": [],
                    "output_shape": "rows",
                },
                {
                    "schema_version": "grounded_understanding_v1",
                    "status": "grounded",
                    "query_shape": "single_hop",
                    "selected_bindings": [
                        _grounded_binding("source", "vertex", "Service"),
                        _grounded_binding("target", "vertex", "Tunnel"),
                        _grounded_binding("relation", "edge", "SERVICE_USES_TUNNEL", direction="forward"),
                        _grounded_binding(
                            "filter_property",
                            "property",
                            "Service.quality_of_service",
                            semantic_name="quality_of_service",
                            owner="Service",
                        ),
                    ],
                    "selected_literals": [
                        {
                            "schema_version": "literal_resolver_result_v1",
                            "raw_literal": "Gold",
                            "resolved": True,
                            "resolved_value": "Gold",
                            "normalized_value": "Gold",
                            "match_type": "exact",
                            "confidence": 1.0,
                            "expected_vertex": "Service",
                            "expected_edge": None,
                            "expected_property": "quality_of_service",
                            "evidence": [
                                {"source": "property.valid_values", "matched": "Gold", "target": "Gold"}
                            ],
                            "alternatives": [],
                            "requires_user_choice": False,
                            "value_index_miss": False,
                            "error_code": None,
                        }
                    ],
                    "filters": [
                        {
                            "owner": "Service",
                            "property": "quality_of_service",
                            "operator": "=",
                            "raw_literal": "Gold",
                        }
                    ],
                    "projection": [
                        {
                            "semantic_type": "property",
                            "owner": "Tunnel",
                            "name": "id",
                            "alias": "tunnel_id",
                        }
                    ],
                    "coverage": {
                        "substantive_terms": {
                            "total": 4,
                            "covered": 4,
                            "uncovered": [],
                        },
                        "stopword_terms": {"ignored": []},
                        "modality_terms": {"warning_only": []},
                        "time_terms": {"covered": [], "unresolved": []},
                        "unparsed_terms": {"unresolved": []},
                    },
                    "unsupported": None,
                    "confidence": 0.93,
                },
            ]

        def generate_structured(
            self,
            *,
            prompt: str,
            schema_name: str,
            schema: dict[str, Any],
            attempt: int,
        ) -> dict[str, Any]:
            self.calls.append(
                {
                    "prompt": prompt,
                    "schema_name": schema_name,
                    "schema": schema,
                    "attempt": attempt,
                }
            )
            return self.responses.pop(0)

    fake_client = FakeStructuredClient()
    monkeypatch.setenv("CYPHER_GENERATOR_AGENT_LLM_ENABLED", "true")
    monkeypatch.setenv("CYPHER_GENERATOR_AGENT_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("CYPHER_GENERATOR_AGENT_LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("CYPHER_GENERATOR_AGENT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("CYPHER_GENERATOR_AGENT_LLM_MODEL", "qwen3-32b")
    get_settings.cache_clear()
    monkeypatch.setattr(
        pipeline_module,
        "_structured_llm_client_from_settings",
        lambda settings: fake_client,
    )

    try:
        output = run_pipeline(
            question="Gold 服务使用了哪些隧道",
            qa_id="real-llm-mode",
            generation_run_id="run-real-llm-mode",
        )
    finally:
        get_settings.cache_clear()

    assert output.status == "generated"
    assert len(fake_client.calls) == 1
    assert [call["schema_name"] for call in fake_client.calls] == ["question_decomposition_v1"]
    assert output.trace["semantic_model"]["name"] == "network_schema_v10"
    assert _compiler_parameters(output.trace)["quality_of_service"] == "Gold"
    decomposer_stage = next(
        stage for stage in output.trace["stages"] if stage["stage"] == "question_decomposer"
    )
    llm_calls = decomposer_stage["output_ref"]["value"]["llm_calls"]
    assert llm_calls[0]["stage"] == "question_decomposer"
    assert llm_calls[0]["schema_name"] == "question_decomposition_v1"
    assert "返回且只返回一个 JSON 对象" in llm_calls[0]["prompt"]
    assert '图原生 Cypher 生成流水线中的"问题结构化拆解器"' in llm_calls[0]["prompt"]
    assert "两条" + "正交的分类轴" not in llm_calls[0]["prompt"]
    assert "substantive_terms 的 slot 取值" in llm_calls[0]["prompt"]
    assert "示例 3:含时间、近似、聚合" in llm_calls[0]["prompt"]
    assert "Return exactly one JSON object" not in llm_calls[0]["prompt"]
    assert "JSON Schema:" in llm_calls[0]["prompt"]
    assert '"intent_type": "list"' in llm_calls[0]["raw_output"]


def test_llm_literal_kind_hint_outside_contract_is_schema_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeStructuredClient:
        provider = "openai_compatible"

        def generate_structured(
            self,
            *,
            prompt: str,
            schema_name: str,
            schema: dict[str, Any],
            attempt: int,
        ) -> dict[str, Any]:
            return {
                "schema_version": "question_decomposition_v1",
                "result_type": "decomposition",
                "intent_type": "list",
                "original_question": "Gold 服务使用了哪些隧道",
                "target_concepts": ["服务", "隧道"],
                "relation_phrases": ["使用了"],
                "literal_candidates": [
                    {"text": "Gold", "kind_hint": "service", "attached_to": "服务"}
                ],
                "substantive_terms": [
                    _decomp_term("Gold", "filter", attached_to="服务"),
                    _decomp_term("服务", "path"),
                    _decomp_term("使用", "path"),
                    _decomp_term("隧道", "projection"),
                ],
                "stopword_terms": ["了", "哪些"],
                "modality_terms": [],
                "time_terms": [],
                "unparsed_terms": [],
                "output_shape": "rows",
            }

    fake_client = FakeStructuredClient()
    monkeypatch.setenv("CYPHER_GENERATOR_AGENT_LLM_ENABLED", "true")
    monkeypatch.setenv("CYPHER_GENERATOR_AGENT_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("CYPHER_GENERATOR_AGENT_LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("CYPHER_GENERATOR_AGENT_LLM_API_KEY", "test-key")
    get_settings.cache_clear()
    monkeypatch.setattr(
        pipeline_module,
        "_structured_llm_client_from_settings",
        lambda settings: fake_client,
    )
    try:
        output = run_pipeline(
            question="Gold 服务使用了哪些隧道",
            qa_id="llm-kind-hint-schema-invalid",
            generation_run_id="run-llm-kind-hint-schema-invalid",
        )
    finally:
        get_settings.cache_clear()

    assert output.status == "generation_failed"
    assert output.failure is not None
    assert output.failure.reason == "question_decomposer_schema_invalid"


def test_llm_enum_literal_with_qualifier_prefers_enum_property_over_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeStructuredClient:
        provider = "openai_compatible"

        def generate_structured(
            self,
            *,
            prompt: str,
            schema_name: str,
            schema: dict[str, Any],
            attempt: int,
        ) -> dict[str, Any]:
            return {
                "schema_version": "question_decomposition_v1",
                "result_type": "decomposition",
                "intent_type": "list",
                "original_question": "Gold级别的服务都使用了哪些隧道",
                "target_concepts": ["服务", "隧道"],
                "relation_phrases": ["使用了"],
                "literal_candidates": [
                    {"text": "Gold级别", "kind_hint": "enum_or_name", "attached_to": "服务"}
                ],
                "substantive_terms": [
                    _decomp_term("Gold级别", "filter", attached_to="服务"),
                    _decomp_term("服务", "path"),
                    _decomp_term("使用", "path"),
                    _decomp_term("隧道", "projection"),
                ],
                "stopword_terms": ["都", "哪些"],
                "modality_terms": [],
                "time_terms": [],
                "unparsed_terms": [],
                "output_shape": "rows",
            }

    def fake_grounded_stage(
        trace: object,
        *,
        decomposition: dict[str, Any],
        retrieval_result: object,
        literal_results: list[object],
        settings: object,
        llm_client: object | None,
        attempt_no: int,
        registry: object | None = None,
        repair_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        literal = literal_results[0].model_dump(mode="json")
        assert literal["raw_literal"] == "Gold级别"
        assert literal["resolved_value"] == "Gold"
        assert literal["expected_property"] == "quality_of_service"
        return {
            "schema_version": "grounded_understanding_v1",
            "status": "grounded",
            "query_shape": "single_hop",
            "selected_bindings": [
                _grounded_binding("source", "vertex", "Service"),
                _grounded_binding("target", "vertex", "Tunnel"),
                _grounded_binding("relation", "edge", "SERVICE_USES_TUNNEL", direction="forward"),
                _grounded_binding(
                    "filter_property",
                    "property",
                    "Service.quality_of_service",
                    semantic_name="quality_of_service",
                    owner="Service",
                ),
            ],
            "selected_literals": [literal],
            "filters": [
                {
                    "owner": "Service",
                    "property": "quality_of_service",
                    "operator": "=",
                    "raw_literal": "Gold级别",
                }
            ],
            "projection": [
                {"semantic_type": "property", "owner": "Tunnel", "name": "id", "alias": "tunnel_id"}
            ],
            "coverage": {
                "substantive_terms": {"total": 4, "covered": 4, "uncovered": []},
                "stopword_terms": {"ignored": ["都", "哪些"]},
                "modality_terms": {"warning_only": []},
                "time_terms": {"covered": [], "unresolved": []},
                "unparsed_terms": {"unresolved": []},
            },
            "unsupported": None,
            "confidence": 0.93,
        }

    monkeypatch.setenv("CYPHER_GENERATOR_AGENT_LLM_ENABLED", "true")
    monkeypatch.setenv("CYPHER_GENERATOR_AGENT_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("CYPHER_GENERATOR_AGENT_LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("CYPHER_GENERATOR_AGENT_LLM_API_KEY", "test-key")
    get_settings.cache_clear()
    monkeypatch.setattr(
        pipeline_module,
        "_structured_llm_client_from_settings",
        lambda settings: FakeStructuredClient(),
    )
    monkeypatch.setattr(pipeline_module, "_run_grounded_understanding_stage", fake_grounded_stage)

    try:
        output = run_pipeline(
            question="Gold级别的服务都使用了哪些隧道",
            qa_id="llm-gold-qualifier",
            generation_run_id="run-llm-gold-qualifier",
        )
    finally:
        get_settings.cache_clear()

    assert output.status == "generated"
    assert _compiler_parameters(output.trace)["quality_of_service"] == "Gold"


def test_decomposition_slot_normalization_uses_attachment_and_classifier_without_prompt_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeStructuredClient:
        provider = "openai_compatible"

        def generate_structured(
            self,
            *,
            prompt: str,
            schema_name: str,
            schema: dict[str, Any],
            attempt: int,
        ) -> dict[str, Any]:
            return {
                "schema_version": "question_decomposition_v1",
                "result_type": "decomposition",
                "intent_type": "count",
                "original_question": "有多少台防火墙",
                "target_concepts": ["防火墙"],
                "relation_phrases": [],
                "literal_candidates": [],
                "substantive_terms": [
                    _decomp_term("多少", "projection"),
                    _decomp_term("台", "projection"),
                    _decomp_term("防火墙", "projection"),
                ],
                "stopword_terms": ["有"],
                "modality_terms": [],
                "time_terms": [],
                "unparsed_terms": [],
                "output_shape": "scalar",
            }

    def fake_grounded_stage(
        trace: object,
        *,
        decomposition: dict[str, Any],
        retrieval_result: object,
        literal_results: list[object],
        settings: object,
        llm_client: object | None,
        attempt_no: int,
        registry: object | None = None,
        repair_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        candidate_ids = {f"{item.semantic_type}:{item.semantic_id}" for item in retrieval_result.candidates}
        assert "vertex:NetworkElement" in candidate_ids
        literal = literal_results[0].model_dump(mode="json")
        assert literal["resolved_value"] == "firewall"
        assert literal["expected_vertex"] == "NetworkElement"
        return {
            "schema_version": "grounded_understanding_v1",
            "status": "grounded",
            "query_shape": "metric_aggregate",
            "selected_bindings": [
                _grounded_binding("target_vertex", "vertex", "NetworkElement"),
                _grounded_binding(
                    "filter_property",
                    "property",
                    "NetworkElement.elem_type",
                    semantic_name="elem_type",
                    owner="NetworkElement",
                ),
            ],
            "selected_literals": [literal],
            "filters": [{"property": "NetworkElement.elem_type", "value": "firewall"}],
            "projection": [],
            "group_by": [],
            "measures": [{"function": "count", "vertex": "NetworkElement"}],
            "coverage": {
                "substantive_terms": {"total": 3, "covered": 3, "uncovered": []},
                "stopword_terms": {"ignored": []},
                "modality_terms": {"warning_only": []},
                "time_terms": {"covered": [], "unresolved": []},
                "unparsed_terms": {"unresolved": []},
            },
            "unsupported": None,
            "confidence": 0.93,
        }

    monkeypatch.setenv("CYPHER_GENERATOR_AGENT_LLM_ENABLED", "true")
    monkeypatch.setenv("CYPHER_GENERATOR_AGENT_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("CYPHER_GENERATOR_AGENT_LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("CYPHER_GENERATOR_AGENT_LLM_API_KEY", "test-key")
    get_settings.cache_clear()
    monkeypatch.setattr(
        pipeline_module,
        "_structured_llm_client_from_settings",
        lambda settings: FakeStructuredClient(),
    )
    monkeypatch.setattr(pipeline_module, "_run_grounded_understanding_stage", fake_grounded_stage)

    try:
        output = run_pipeline(
            question="有多少台防火墙",
            qa_id="slot-normalization",
            generation_run_id="run-slot-normalization",
        )
    finally:
        get_settings.cache_clear()

    assert output.status == "generated"
    assert "count(ne.id)" in output.cypher
    assert _compiler_parameters(output.trace)["elem_type"] == "firewall"


def test_value_synonym_candidate_becomes_literal_request_when_llm_omits_literal_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeStructuredClient:
        provider = "openai_compatible"

        def generate_structured(
            self,
            *,
            prompt: str,
            schema_name: str,
            schema: dict[str, Any],
            attempt: int,
        ) -> dict[str, Any]:
            return {
                "schema_version": "question_decomposition_v1",
                "result_type": "decomposition",
                "intent_type": "count",
                "original_question": "有多少台防火墙",
                "target_concepts": ["防火墙"],
                "relation_phrases": [],
                "literal_candidates": [],
                "substantive_terms": [
                    _decomp_term("多少", "projection"),
                    _decomp_term("台", "projection"),
                    _decomp_term("防火墙", "projection"),
                ],
                "stopword_terms": ["有"],
                "modality_terms": [],
                "time_terms": [],
                "unparsed_terms": [],
                "output_shape": "scalar",
            }

    fake_client = FakeStructuredClient()
    monkeypatch.setenv("CYPHER_GENERATOR_AGENT_LLM_ENABLED", "true")
    monkeypatch.setenv("CYPHER_GENERATOR_AGENT_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("CYPHER_GENERATOR_AGENT_LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("CYPHER_GENERATOR_AGENT_LLM_API_KEY", "test-key")
    get_settings.cache_clear()
    monkeypatch.setattr(
        pipeline_module,
        "_structured_llm_client_from_settings",
        lambda settings: fake_client,
    )

    try:
        output = run_pipeline(
            question="有多少台防火墙",
            qa_id="value-candidate-literal",
            generation_run_id="run-value-candidate-literal",
        )
    finally:
        get_settings.cache_clear()

    assert output.status == "generated"
    assert "WHERE ne.elem_type = 'firewall'" in output.cypher
    assert "$elem_type" not in output.cypher
    assert "WHERE ne.elem_type = $elem_type" in _compiler_template(output.trace)
    assert _compiler_parameters(output.trace)["elem_type"] == "firewall"


def test_llm_vertex_lookup_without_filter_or_projection_uses_selected_literal_and_default_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeStructuredClient:
        provider = "openai_compatible"

        def __init__(self) -> None:
            self.responses = [
                {
                    "schema_version": "question_decomposition_v1",
                    "result_type": "decomposition",
                    "intent_type": "list",
                    "original_question": "当前 down 的端口有哪些",
                    "target_concepts": ["端口"],
                    "relation_phrases": [],
                    "literal_candidates": [
                        {"text": "down", "kind_hint": "enum_or_name", "attached_to": "端口"}
                    ],
                    "substantive_terms": [
                        _decomp_term("down", "filter", attached_to="端口"),
                        _decomp_term("端口", "projection"),
                    ],
                    "stopword_terms": ["有哪些"],
                    "modality_terms": [],
                    "time_terms": ["当前"],
                    "unparsed_terms": [],
                    "output_shape": "rows",
                },
                {
                    "schema_version": "grounded_understanding_v1",
                    "status": "grounded",
                    "query_shape": "vertex_lookup",
                    "selected_bindings": [
                        _grounded_binding("target_vertex", "vertex", "Port"),
                        _grounded_binding(
                            "filter_property",
                            "property",
                            "Port.status",
                            semantic_name="status",
                            owner="Port",
                        ),
                    ],
                    "selected_literals": [],
                    "filters": [],
                    "projection": [],
                    "coverage": {
                        "substantive_terms": {"total": 2, "covered": 2, "uncovered": []},
                        "stopword_terms": {"ignored": ["有哪些"]},
                        "modality_terms": {"warning_only": []},
                        "time_terms": {"covered": [], "unresolved": []},
                        "unparsed_terms": {"unresolved": []},
                    },
                    "unsupported": None,
                    "confidence": 0.92,
                },
            ]

        def generate_structured(
            self,
            *,
            prompt: str,
            schema_name: str,
            schema: dict[str, Any],
            attempt: int,
        ) -> dict[str, Any]:
            if schema_name == "grounded_understanding_v1":
                self.responses[0]["selected_literals"] = [
                    result
                    for result in _latest_literal_resolver_results
                ]
            return self.responses.pop(0)

    _latest_literal_resolver_results: list[dict[str, Any]] = []
    original_run_grounded = pipeline_module._run_grounded_understanding_stage

    def capture_literals(*args: Any, **kwargs: Any) -> Any:
        _latest_literal_resolver_results[:] = [
            result.model_dump(mode="json")
            for result in kwargs["literal_results"]
        ]
        return original_run_grounded(*args, **kwargs)

    fake_client = FakeStructuredClient()
    monkeypatch.setenv("CYPHER_GENERATOR_AGENT_LLM_ENABLED", "true")
    monkeypatch.setenv("CYPHER_GENERATOR_AGENT_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("CYPHER_GENERATOR_AGENT_LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("CYPHER_GENERATOR_AGENT_LLM_API_KEY", "test-key")
    get_settings.cache_clear()
    monkeypatch.setattr(
        pipeline_module,
        "_structured_llm_client_from_settings",
        lambda settings: fake_client,
    )
    monkeypatch.setattr(pipeline_module, "_run_grounded_understanding_stage", capture_literals)

    try:
        output = run_pipeline(
            question="当前 down 的端口有哪些",
            qa_id="llm-vertex-lookup-defaults",
            generation_run_id="run-llm-vertex-lookup-defaults",
        )
    finally:
        get_settings.cache_clear()

    assert output.status == "generated"
    assert output.cypher == "MATCH (port:Port)\nWHERE port.status = 'down'\nRETURN port.id AS port_id"
    assert _compiler_template(output.trace) == "MATCH (port:Port)\nWHERE port.status = $status\nRETURN port.id AS port_id"
    assert _compiler_parameters(output.trace)["status"] == "down"


def test_llm_repair_loop_regrounds_after_repairable_validator_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeStructuredClient:
        provider = "openai_compatible"

        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []
            self.responses = [
                {
                    "schema_version": "question_decomposition_v1",
                    "result_type": "decomposition",
                    "intent_type": "list",
                    "original_question": "Gold 服务使用了哪些隧道",
                    "target_concepts": ["服务", "隧道"],
                    "relation_phrases": ["使用隧道"],
                    "literal_candidates": [
                        {"text": "Gold", "kind_hint": "enum_or_name", "attached_to": "服务"}
                    ],
                    "substantive_terms": [
                        _decomp_term("Gold", "filter", attached_to="服务"),
                        _decomp_term("服务", "path"),
                        _decomp_term("使用", "path"),
                        _decomp_term("隧道", "projection"),
                    ],
                    "stopword_terms": [],
                    "modality_terms": [],
                    "time_terms": [],
                    "unparsed_terms": [],
                    "output_shape": "rows",
                },
                _grounded_service_tunnel_payload(direction="backward"),
                _grounded_service_tunnel_payload(direction="forward"),
            ]

        def generate_structured(
            self,
            *,
            prompt: str,
            schema_name: str,
            schema: dict[str, Any],
            attempt: int,
        ) -> dict[str, Any]:
            self.calls.append(
                {
                    "prompt": prompt,
                    "schema_name": schema_name,
                    "schema": schema,
                    "attempt": attempt,
                }
            )
            return self.responses.pop(0)

    fake_client = FakeStructuredClient()
    monkeypatch.setenv("CYPHER_GENERATOR_AGENT_LLM_ENABLED", "true")
    monkeypatch.setenv("CYPHER_GENERATOR_AGENT_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("CYPHER_GENERATOR_AGENT_LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("CYPHER_GENERATOR_AGENT_LLM_API_KEY", "test-key")
    get_settings.cache_clear()
    monkeypatch.setattr(
        pipeline_module,
        "_structured_llm_client_from_settings",
        lambda settings: fake_client,
    )
    monkeypatch.setattr(
        pipeline_module,
        "_deterministic_grounding_from_slots",
        lambda **kwargs: None,
    )

    try:
        output = run_pipeline(
            question="Gold 服务使用了哪些隧道",
            qa_id="llm-repair-loop",
            generation_run_id="run-llm-repair-loop",
        )
    finally:
        get_settings.cache_clear()

    assert output.status == "generated"
    assert output.cypher is not None
    assert "SERVICE_USES_TUNNEL" in output.cypher
    assert [call["schema_name"] for call in fake_client.calls] == [
        "question_decomposition_v1",
        "grounded_understanding_v1",
        "grounded_understanding_v1",
    ]
    assert "edge_endpoint_mismatch" in fake_client.calls[2]["prompt"]
    assert _stage_names(output.trace).count("grounded_understanding") == 2
    assert _stage_names(output.trace).count("repair_controller") == 1


def test_tunnel_path_question_generates_named_path_pattern_cypher() -> None:
    output = run_pipeline(
        question="隧道 tun-mpls-001 经过哪些设备",
        qa_id="gq-003",
        generation_run_id="run-gq-003",
    )

    assert output.status == "generated"
    assert output.cypher is not None
    assert output.cypher == (
        "MATCH (t:Tunnel {id: 'tun-mpls-001'})-[p:PATH_THROUGH]->(ne:NetworkElement)\n"
        "RETURN ne AS device, p.hop_order AS hop\n"
        "ORDER BY p.hop_order ASC"
    )
    assert _compiler_parameters(output.trace) == {"tunnel_id": "tun-mpls-001"}
    assert "MATCH (t:Tunnel {id: $tunnel_id})" in _compiler_template(output.trace)
    assert _compiler_executable(output.trace) == output.cypher
    assert output.dsl is not None
    assert output.dsl["query_shape"] == "named_path_pattern"
    assert output.dsl["operations"][0]["path_pattern_name"] == "tunnel_full_path"
    assert _stage_names(output.trace) == EXPECTED_STAGES


def test_coverage_failure_does_not_emit_cypher_or_dsl() -> None:
    output = run_pipeline(
        question="2024 年收入增长情况",
        qa_id="coverage-failure",
        generation_run_id="run-coverage-failure",
    )

    assert output.status == "clarification_required"
    assert output.cypher is None
    assert output.dsl is None
    assert output.failure is None
    assert output.clarification is not None
    assert "收入" in output.clarification.question
    assert output.trace["final_outputs"]["clarification"]["question"] == output.clarification.question
    assert output.trace["final_outputs"]["cypher"] is None
    assert output.trace["final_outputs"]["dsl"] is None
    assert _stage_names(output.trace)[-3:] == ["semantic_validator", "repair_controller", "output"]


def test_generated_output_includes_user_visible_assumption_notices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_decompose = pipeline_module._mock_decompose

    def modality_decompose(question: str) -> dict[str, object]:
        payload = original_decompose("全网有多少台防火墙")
        payload["original_question"] = question
        payload["literal_candidates"] = [
            {"text": "防火墙", "kind_hint": "enum_or_name", "attached_to": "设备"}
        ]
        payload["substantive_terms"] = [
            _decomp_term("多少", "projection"),
            _decomp_term("防火墙", "projection"),
        ]
        payload["coverage"] = {
            "substantive_terms": {"total": 2, "covered": 2, "uncovered": []},
            "stopword_terms": {"ignored": []},
            "modality_terms": {"warning_only": ["大概"]},
            "time_terms": {"covered": [], "unresolved": []},
            "unparsed_terms": {"unresolved": []},
        }
        return payload

    monkeypatch.setattr(pipeline_module, "_mock_decompose", modality_decompose)

    output = run_pipeline(
        question="大概有多少防火墙",
        qa_id="assumption-notice",
        generation_run_id="run-assumption-notice",
    )

    assert output.status == "generated"
    assert output.user_visible_notices == ["问题中的“大概”没有被解释为查询约束。"]
    assert output.trace["final_outputs"]["user_visible_notices"] == output.user_visible_notices


def test_unsupported_query_shape_from_validator_returns_unsupported_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unsupported_understanding(
        decomposition: dict[str, object],
        literal_results: list[object],
    ) -> dict[str, object]:
        return {
            "query_shape": "shortest_path",
            "selected_vertices": ["Service"],
            "projection": [{"semantic_type": "vertex", "name": "Service"}],
        }

    monkeypatch.setattr(pipeline_module, "_mock_understand", unsupported_understanding)

    output = run_pipeline(
        question="Gold 服务使用了哪些隧道",
        qa_id="unsupported-shape",
        generation_run_id="run-unsupported-shape",
    )

    assert output.status == "unsupported_query_shape"
    assert output.cypher is None
    assert output.dsl is None
    assert output.failure is not None
    assert output.failure.reason == "unsupported_query_shape"
    assert _stage_names(output.trace)[-3:] == ["semantic_validator", "repair_controller", "output"]


def test_unresolved_literal_stops_before_dsl_or_cypher_generation() -> None:
    output = run_pipeline(
        question="Platinum 服务使用了哪些隧道",
        qa_id="literal-unresolved",
        generation_run_id="run-literal-unresolved",
    )

    assert output.status == "clarification_required"
    assert output.cypher is None
    assert output.dsl is None
    assert output.failure is None
    assert output.clarification is not None
    assert "Platinum" in output.clarification.question
    assert _stage_names(output.trace) == [
        "graph_model_loader",
        "input_clarification_gate",
        "question_decomposer",
        "candidate_retrieval",
        "literal_resolver",
        "repair_controller",
        "output",
    ]


def test_self_validation_failure_records_self_validation_stage_without_final_cypher() -> None:
    output = run_pipeline(
        question="隧道 tun-mpls-001 经过哪些设备",
        qa_id="self-validation-failure",
        generation_run_id="run-self-validation-failure",
        _path_pattern_template_overrides_for_tests={
            "tunnel_full_path": (
                "MATCH (t:Tunnel {id: $tunnel_id})-[p:PATH_THROUGH]->(ne:NetworkElement)\n"
                "SET ne.name = 'bad'\n"
                "RETURN ne AS device, p.hop_order AS hop"
            )
        },
    )

    assert output.status == "generation_failed"
    assert output.cypher is None
    assert output.dsl is None
    assert output.failure is not None
    assert output.failure.reason == "cypher_readonly_violation"
    assert _stage_names(output.trace)[-3:] == ["cypher_self_validation", "repair_controller", "output"]
    self_validation_stage = output.trace["stages"][-3]
    assert self_validation_stage["status"] == "failed"
    assert self_validation_stage["output_ref"]["value"]["valid"] is False


def test_path_pattern_shape_mismatch_is_reported_by_self_validation_stage() -> None:
    output = run_pipeline(
        question="隧道 tun-mpls-001 经过哪些设备",
        qa_id="shape-mismatch",
        generation_run_id="run-shape-mismatch",
        _path_pattern_template_overrides_for_tests={
            "tunnel_full_path": (
                "MATCH (t:Tunnel {id: $tunnel_id})-[p:PATH_THROUGH]->(ne:NetworkElement)\n"
                "RETURN ne AS wrong_device, p.hop_order AS hop"
            )
        },
    )

    assert output.status == "generation_failed"
    assert output.cypher is None
    assert output.dsl is None
    assert output.failure is not None
    assert output.failure.reason == "compiler_shape_mismatch"
    assert _stage_names(output.trace)[-3:] == ["cypher_self_validation", "repair_controller", "output"]
    self_validation_stage = output.trace["stages"][-3]
    assert self_validation_stage["status"] == "failed"
    assert self_validation_stage["errors"][0]["code"] == "compiler_shape_mismatch"


def test_dsl_parser_failure_is_recorded_in_dsl_parser_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def invalid_dsl(*args: object, **kwargs: object) -> dict[str, object]:
        return {
            "schema_version": "restricted_query_dsl_v1",
            "query_id": "invalid-dsl",
            "query_shape": "single_hop_traversal",
            "bindings": {},
            "operations": [],
            "projection": {"items": []},
        }

    monkeypatch.setattr(pipeline_module.RestrictedDslBuilder, "build", invalid_dsl)

    output = run_pipeline(
        question="Gold 服务使用了哪些隧道",
        qa_id="invalid-dsl",
        generation_run_id="run-invalid-dsl",
    )

    assert output.status == "generation_failed"
    assert output.failure is not None
    assert output.failure.reason == "compiler_shape_mismatch"
    assert _stage_names(output.trace)[-2:] == ["dsl_parser", "output"]
    parser_stage = output.trace["stages"][-2]
    assert parser_stage["status"] == "failed"
    assert parser_stage["errors"][0]["type"] == "RestrictedDslValidationError"


def test_model_loader_failure_returns_service_failure_envelope(tmp_path) -> None:
    output = run_pipeline(
        question="Gold 服务使用了哪些隧道",
        qa_id="model-loader-failure",
        generation_run_id="run-model-loader-failure",
        _model_path=tmp_path / "missing-model.yaml",
    )

    assert output.status == "service_failed"
    assert output.cypher is None
    assert output.dsl is None
    assert output.failure is not None
    assert output.failure.reason == "knowledge_context_unavailable"
    assert _stage_names(output.trace) == ["graph_model_loader", "output"]
    assert output.trace["stages"][0]["status"] == "failed"


def test_decomposer_clarification_outcome_short_circuits_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def clarification_decompose(question: str) -> QuestionDecompositionClarification:
        return QuestionDecompositionClarification(
            original_question=question,
            clarification=ClarificationRequest(question="请说明“它”指的是哪个设备或服务。"),
            missing_referents=["它"],
        )

    monkeypatch.setattr(pipeline_module, "_mock_decompose", clarification_decompose)

    output = run_pipeline(
        question="请进一步说明查询对象",
        qa_id="decomposer-clarification",
        generation_run_id="run-decomposer-clarification",
    )

    assert output.status == "clarification_required"
    assert output.cypher is None
    assert output.dsl is None
    assert output.clarification is not None
    assert output.clarification.question == "请说明“它”指的是哪个设备或服务。"
    assert _stage_names(output.trace) == ["graph_model_loader", "input_clarification_gate", "question_decomposer", "output"]


def test_decomposer_failure_outcome_short_circuits_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed_decompose(question: str) -> QuestionDecompositionFailure:
        return QuestionDecompositionFailure(
            status="service_failed",
            reason="model_invocation_failed",
            message="provider timeout",
            provider="fake-llm",
            error_type="TimeoutError",
            attempts=1,
            retry_count=0,
        )

    monkeypatch.setattr(pipeline_module, "_mock_decompose", failed_decompose)

    output = run_pipeline(
        question="Gold 服务使用了哪些隧道",
        qa_id="decomposer-failure",
        generation_run_id="run-decomposer-failure",
    )

    assert output.status == "service_failed"
    assert output.failure is not None
    assert output.failure.reason == "model_invocation_failed"
    assert _stage_names(output.trace) == ["graph_model_loader", "input_clarification_gate", "question_decomposer", "output"]


def test_grounded_understanding_schema_output_is_converted_before_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def grounded_schema_understanding(
        decomposition: dict[str, object],
        literal_results: list[object],
    ) -> dict[str, object]:
        return {
            "schema_version": "grounded_understanding_v1",
            "status": "grounded",
            "query_shape": "single_hop",
            "selected_bindings": [
                _grounded_binding("source", "vertex", "Service"),
                _grounded_binding("target", "vertex", "Tunnel"),
                _grounded_binding("relation", "edge", "SERVICE_USES_TUNNEL", direction="forward"),
                _grounded_binding(
                    "filter_property",
                    "property",
                    "Service.quality_of_service",
                    semantic_name="quality_of_service",
                    owner="Service",
                ),
            ],
            "selected_literals": [
                result.model_dump(mode="json")
                for result in literal_results
            ],
            "filters": [
                {
                    "owner": "Service",
                    "property": "quality_of_service",
                    "operator": "=",
                    "raw_literal": "Gold",
                }
            ],
            "projection": [
                {"semantic_type": "property", "owner": "Tunnel", "name": "id", "alias": "tunnel_id"}
            ],
            "coverage": {
                "substantive_terms": {
                    "total": 4,
                    "covered": 4,
                    "uncovered": [],
                }
            },
            "unsupported": None,
            "confidence": 0.93,
        }

    monkeypatch.setattr(pipeline_module, "_mock_understand", grounded_schema_understanding)

    output = run_pipeline(
        question="Gold 服务使用了哪些隧道",
        qa_id="grounded-schema",
        generation_run_id="run-grounded-schema",
    )

    assert output.status == "generated"
    assert output.cypher is not None
    assert "SERVICE_USES_TUNNEL" in output.cypher
    assert _stage_names(output.trace) == EXPECTED_STAGES


def test_grounded_understanding_failure_outcome_stops_before_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed_grounding(
        decomposition: dict[str, object],
        literal_results: list[object],
    ) -> GroundedUnderstandingFailure:
        return GroundedUnderstandingFailure(
            status="generation_failed",
            reason="semantic_match_rejected",
            message="candidate_id edge:USES_TUNNEL is not present in candidate set",
            provider="fake-grounded-llm",
            error_type="CandidateBoundaryError",
            attempts=1,
            retry_count=0,
        )

    monkeypatch.setattr(pipeline_module, "_mock_understand", failed_grounding)

    output = run_pipeline(
        question="Gold 服务使用了哪些隧道",
        qa_id="grounded-failure",
        generation_run_id="run-grounded-failure",
    )

    assert output.status == "generation_failed"
    assert output.failure is not None
    assert output.failure.reason == "semantic_match_rejected"
    assert _stage_names(output.trace)[-2:] == ["grounded_understanding", "output"]


@pytest.mark.asyncio
async def test_semantic_parse_api_uses_pipeline_for_happy_path() -> None:
    result = await parse_semantics(
        SemanticParseRequest(
            id="gq-001",
            question="Gold 服务使用了哪些隧道",
            generation_run_id="run-api-gq-001",
        )
    )

    assert result["status"] == "generated"
    assert "SERVICE_USES_TUNNEL" in result["cypher"]
    assert result["trace"]["final_status"] == "generated"
    assert _stage_names(result["trace"]) == EXPECTED_STAGES


def _stage_names(trace: dict[str, object]) -> list[str]:
    return [stage["stage"] for stage in trace["stages"]]


def _compiler_parameters(trace: dict[str, object]) -> dict[str, object]:
    for stage in trace["stages"]:
        if stage["stage"] == "cypher_compiler":
            return stage["output_ref"]["value"]["parameters"]
    raise AssertionError("missing cypher_compiler stage")


def _compiler_template(trace: dict[str, object]) -> str:
    for stage in trace["stages"]:
        if stage["stage"] == "cypher_compiler":
            return stage["output_ref"]["value"]["cypher_template"]
    raise AssertionError("missing cypher_compiler stage")


def _compiler_executable(trace: dict[str, object]) -> str:
    for stage in trace["stages"]:
        if stage["stage"] == "cypher_compiler":
            return stage["output_ref"]["value"]["cypher_executable"]
    raise AssertionError("missing cypher_compiler stage")


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for item in value.values():
            keys.update(_all_keys(item))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for item in value:
            keys.update(_all_keys(item))
        return keys
    return set()


def _grounded_binding(
    role: str,
    semantic_type: str,
    semantic_id: str,
    *,
    semantic_name: str | None = None,
    owner: str | None = None,
    direction: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "role": role,
        "semantic_type": semantic_type,
        "candidate_id": f"{semantic_type}:{semantic_id}",
        "semantic_id": semantic_id,
        "semantic_name": semantic_name or semantic_id,
        "confidence": 0.95,
    }
    if owner is not None:
        payload["owner"] = owner
    if direction is not None:
        payload["direction"] = direction
    return payload


def _decomp_term(text: str, slot: str, *, attached_to: str | None = None) -> dict[str, str]:
    payload = {"text": text, "slot": slot}
    if attached_to is not None:
        payload["attached_to"] = attached_to
    return payload


def _grounded_service_tunnel_payload(*, direction: str) -> dict[str, object]:
    return {
        "schema_version": "grounded_understanding_v1",
        "status": "grounded",
        "query_shape": "single_hop",
        "selected_bindings": [
            _grounded_binding("source", "vertex", "Service"),
            _grounded_binding("target", "vertex", "Tunnel"),
            _grounded_binding("relation", "edge", "SERVICE_USES_TUNNEL", direction=direction),
            _grounded_binding(
                "filter_property",
                "property",
                "Service.quality_of_service",
                semantic_name="quality_of_service",
                owner="Service",
            ),
        ],
        "selected_literals": [
            {
                "schema_version": "literal_resolver_result_v1",
                "raw_literal": "Gold",
                "resolved": True,
                "resolved_value": "Gold",
                "normalized_value": "Gold",
                "match_type": "exact",
                "confidence": 1.0,
                "expected_vertex": "Service",
                "expected_edge": None,
                "expected_property": "quality_of_service",
                "evidence": [
                    {"source": "property.valid_values", "matched": "Gold", "target": "Gold"}
                ],
                "alternatives": [],
                "requires_user_choice": False,
                "value_index_miss": False,
                "error_code": None,
            }
        ],
        "filters": [
            {
                "owner": "Service",
                "property": "quality_of_service",
                "operator": "=",
                "raw_literal": "Gold",
            }
        ],
        "projection": [
            {"semantic_type": "property", "owner": "Tunnel", "name": "id", "alias": "tunnel_id"}
        ],
        "coverage": {
            "substantive_terms": {
                "total": 4,
                "covered": 4,
                "uncovered": [],
            },
            "stopword_terms": {"ignored": []},
            "modality_terms": {"warning_only": []},
            "time_terms": {"covered": [], "unresolved": []},
            "unparsed_terms": {"unresolved": []},
        },
        "unsupported": None,
        "confidence": 0.93,
    }
