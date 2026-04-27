from __future__ import annotations

import json
import math
from typing import Any, Dict, List

import pytest

from services.repair_agent.app.analysis import RepairAnalyzer, build_diagnosis_context
from services.testing_agent.app.models import (
    ActualPayload,
    EvaluationSummary,
    ExecutionAccuracy,
    ExecutionResult,
    GLEUSignal,
    GrammarMetric,
    IssueTicket,
    JaroWinklerSimilaritySignal,
    PrimaryMetrics,
    SecondarySignals,
    SemanticCheck,
    StrictCheck,
    ExpectedPayload,
    GenerationEvidence,
)


def _make_ticket() -> IssueTicket:
    return IssueTicket(
        ticket_id="ticket-repair-1",
        id="q-repair-1",
        difficulty="L3",
        question="Which services use tunnel T1?",
        expected=ExpectedPayload(
            cypher="MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel {name:'T1'}) RETURN s",
            answer=[],
        ),
        actual=ActualPayload(
            generated_cypher="MATCH (s:Service) RETURN s",
            execution=ExecutionResult(success=True, rows=[], row_count=0, error_message=None, elapsed_ms=12),
        ),
        evaluation=EvaluationSummary(
            verdict="fail",
            primary_metrics=PrimaryMetrics(
                grammar=GrammarMetric(score=1, parser_error=None, message=None),
                execution_accuracy=ExecutionAccuracy(
                    score=0,
                    reason="not_equivalent",
                    strict_check=StrictCheck(
                        status="fail",
                        message="The generated query ignored the tunnel relation.",
                        order_sensitive=False,
                        expected_row_count=1,
                        actual_row_count=0,
                        evidence=None,
                    ),
                    semantic_check=SemanticCheck(
                        status="fail",
                        message="The query intent is not equivalent.",
                        raw_output=None,
                    ),
                ),
            ),
            secondary_signals=SecondarySignals(
                gleu=GLEUSignal(score=0.41, tokenizer="whitespace", min_n=1, max_n=4),
                jaro_winkler_similarity=JaroWinklerSimilaritySignal(
                    score=0.78,
                    normalization="lightweight",
                    library="jellyfish",
                ),
            ),
        ),
        generation_evidence=GenerationEvidence(
            generation_run_id="run-repair-1",
            attempt_no=1,
            input_prompt_snapshot="PROMPT SNAPSHOT",
        ),
    )


class _HighConfidenceDiagnosisClient:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    async def diagnose(self, context: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append(context)
        return {
            "primary_knowledge_type": "few_shot",
            "secondary_knowledge_types": ["business_knowledge"],
            "confidence": 0.93,
            "suggestion": "Add a few-shot example showing how Service connects to Tunnel.",
            "rationale": "The prompt missed a key relation pattern.",
            "need_validation": True,
            "candidate_patch_types": ["few_shot", "business_knowledge"],
        }


@pytest.mark.asyncio
async def test_repair_analyzer_runs_llm_first_and_optional_validation():
    client = _HighConfidenceDiagnosisClient()
    experiment_calls: List[Dict[str, Any]] = []

    async def experiment_runner(ticket: IssueTicket, context: Dict[str, Any], patch_type: str, diagnosis: Dict[str, Any]) -> Dict[str, Any]:
        experiment_calls.append(
            {
                "ticket_id": ticket.id,
                "patch_type": patch_type,
                "question": context["question"],
                "primary_knowledge_type": diagnosis["primary_knowledge_type"],
            }
        )
        if patch_type == "few_shot":
            return {"improved": True, "confidence": 0.97, "reason": "few_shot best explains the failure diff"}
        return {"improved": False, "confidence": 0.12, "reason": "business knowledge already present"}

    analyzer = RepairAnalyzer(
        diagnosis_client=client,
        min_confidence_for_direct_return=0.8,
        experiment_runner=experiment_runner,
    )

    result = await analyzer.analyze(_make_ticket(), "PROMPT SNAPSHOT\nappendix: unrelated noise")

    assert result.id == "q-repair-1"
    assert result.knowledge_types == ["few_shot"]
    assert result.primary_knowledge_type == "few_shot"
    assert result.secondary_knowledge_types == ["business_knowledge"]
    assert result.candidate_patch_types == ["few_shot", "business_knowledge"]
    assert result.validation_mode == "lightweight"
    assert result.validation_result["validated_patch_types"] == ["few_shot"]
    assert result.validation_result["rejected_patch_types"] == ["business_knowledge"]
    assert result.suggestion == "Add a few-shot example showing how Service connects to Tunnel."
    assert result.confidence == pytest.approx(0.97)
    assert result.rationale == "The prompt missed a key relation pattern."
    assert result.used_experiments is True
    assert result.to_request().model_dump() == {
        "id": "q-repair-1",
        "suggestion": "Add a few-shot example showing how Service connects to Tunnel.",
        "knowledge_types": ["few_shot"],
    }
    assert client.calls[0]["question"] == "Which services use tunnel T1?"
    assert client.calls[0]["failure_diff"]["entity_or_relation_problem"] is True
    assert client.calls[0]["evaluation_summary"]["verdict"] == "fail"
    assert "appendix: unrelated noise" not in json.dumps(client.calls[0], ensure_ascii=False)
    assert experiment_calls == [
        {
            "ticket_id": "q-repair-1",
            "patch_type": "few_shot",
            "question": "Which services use tunnel T1?",
            "primary_knowledge_type": "few_shot",
        },
        {
            "ticket_id": "q-repair-1",
            "patch_type": "business_knowledge",
            "question": "Which services use tunnel T1?",
            "primary_knowledge_type": "few_shot",
        },
    ]


class _MalformedConfidenceDiagnosisClient:
    async def diagnose(self, context: Dict[str, Any]) -> Dict[str, Any]:
        assert context["question"] == "Which services use tunnel T1?"
        return {
            "primary_knowledge_type": "bad_type",
            "secondary_knowledge_types": ["unknown_type"],
            "confidence": float("nan"),
            "suggestion": "Keep the repair guidance focused on the tunnel relation.",
            "rationale": "Bad confidence payload should not leak through.",
            "need_validation": False,
        }


@pytest.mark.asyncio
async def test_repair_analyzer_clamps_and_sanitizes_malformed_confidence_values():
    analyzer = RepairAnalyzer(
        diagnosis_client=_MalformedConfidenceDiagnosisClient(),
        min_confidence_for_direct_return=0.8,
    )

    result = await analyzer.analyze(_make_ticket(), "PROMPT SNAPSHOT")

    assert math.isfinite(result.confidence)
    assert result.confidence == pytest.approx(0.0)
    assert result.knowledge_types == ["system_prompt"]
    assert result.primary_knowledge_type == "system_prompt"
    assert result.secondary_knowledge_types == []
    assert result.validation_mode == "disabled"
    assert result.suggestion == "Keep the repair guidance focused on the tunnel relation."
    assert result.to_request().model_dump()["knowledge_types"] == ["system_prompt"]


def test_build_diagnosis_context_uses_formal_testing_contract_and_internal_failure_diff():
    context = build_diagnosis_context(
        _make_ticket(),
        """SYSTEM: Return valid graph traversals only.
Business mapping: tunnel T1 means tunnel name.
Few-shot: MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel) RETURN s
Recent repair: Added tunnel relation example.
appendix: unrelated noise
""",
        recent_applied_repairs=[
            {"knowledge_type": "few_shot", "suggestion": "Added tunnel traversal example"},
        ],
    )

    assert context["question"] == "Which services use tunnel T1?"
    assert context["sql_pair"]["expected_cypher"].startswith("MATCH (s:Service)")
    assert context["evaluation_summary"]["verdict"] == "fail"
    assert context["evaluation_summary"]["primary_metrics"]["grammar"]["score"] == 1
    assert context["failure_diff"]["entity_or_relation_problem"] is True
    assert context["failure_diff"]["return_shape_problem"] is False
    assert "entity_or_relation" in context["failure_diff"]["missing_or_wrong_clauses"]
    assert "unrelated noise" not in json.dumps(context, ensure_ascii=False)
    assert context["relevant_prompt_fragments"]["few_shot_fragment"]
    assert context["recent_applied_repairs"][0]["knowledge_type"] == "few_shot"


def test_build_diagnosis_context_includes_compact_full_prompt_evidence_for_structured_chinese_prompt():
    prompt_snapshot = """
## 角色定义
你是图查询生成器，只能输出 Cypher。
## 输出格式
- 返回 JSON 对象，字段包括 cypher、reasoning_summary。
## 知识片段
- 协议版本需要通过 (:ProtocolVersion)<-[:HAS_VERSION]-(:Protocol) 匹配。
appendix: 这段调试噪声不应进入诊断上下文
""".strip()

    context = build_diagnosis_context(_make_ticket(), prompt_snapshot)

    serialized_context = json.dumps(context, ensure_ascii=False)
    assert context["prompt_evidence"]
    assert "角色定义" in context["prompt_evidence"]
    assert "协议版本需要通过" in context["prompt_evidence"]
    assert "输出格式" in context["prompt_evidence"]
    assert "调试噪声" not in serialized_context
    assert all(not value for value in context["relevant_prompt_fragments"].values())
