from __future__ import annotations

import json
import math
from typing import Any, Dict, List

import pytest

from contracts.models import ActualAnswer, EvaluationDimensions, EvaluationSummary, ExpectedAnswer, IssueTicket
from services.repair_agent.app.analysis import KRSSAnalyzer, build_diagnosis_context


def _make_ticket() -> IssueTicket:
    return IssueTicket(
        id="q-krss-1",
        difficulty="L3",
        question="Which services use tunnel T1?",
        expected=ExpectedAnswer(cypher="MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel {name:'T1'}) RETURN s", answer=[]),
        actual=ActualAnswer(generated_cypher="MATCH (s:Service) RETURN s", execution={"success": True, "rows": [], "row_count": 0}),
        evaluation=EvaluationSummary(
            verdict="fail",
            dimensions=EvaluationDimensions(
                syntax_validity="pass",
                schema_alignment="pass",
                result_correctness="fail",
                question_alignment="fail",
            ),
            symptom="Wrong query shape",
            evidence=["The generated query ignored the tunnel relation."],
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
            "suggestion": "Add a few_shot example showing how Service connects to Tunnel.",
            "rationale": "The prompt missed a key relation pattern.",
            "need_validation": True,
            "candidate_patch_types": ["few_shot", "business_knowledge"],
        }


@pytest.mark.asyncio
async def test_krss_analyzer_returns_direct_result_for_high_confidence_llm_diagnosis():
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

    analyzer = KRSSAnalyzer(
        diagnosis_client=client,
        min_confidence_for_direct_return=0.8,
        experiment_runner=experiment_runner,
    )

    result = await analyzer.analyze(_make_ticket(), "PROMPT SNAPSHOT\nappendix: unrelated noise")

    assert result.id == "q-krss-1"
    assert result.knowledge_types == ["few_shot"]
    assert result.primary_knowledge_type == "few_shot"
    assert result.secondary_knowledge_types == ["business_knowledge"]
    assert result.candidate_patch_types == ["few_shot", "business_knowledge"]
    assert result.validation_mode == "lightweight"
    assert result.validation_result["validated_patch_types"] == ["few_shot"]
    assert result.validation_result["rejected_patch_types"] == ["business_knowledge"]
    assert result.suggestion == "Add a few_shot example showing how Service connects to Tunnel."
    assert result.confidence == pytest.approx(0.97)
    assert result.rationale == "The prompt missed a key relation pattern."
    assert result.used_experiments is True
    assert result.to_request().model_dump() == {
        "id": "q-krss-1",
        "suggestion": "Add a few_shot example showing how Service connects to Tunnel.",
        "knowledge_types": ["few_shot"],
    }
    assert client.calls[0]["question"] == "Which services use tunnel T1?"
    assert client.calls[0]["failure_diff"]["entity_or_relation_problem"] is True
    assert "appendix: unrelated noise" not in json.dumps(client.calls[0], ensure_ascii=False)
    assert experiment_calls == [
        {
            "ticket_id": "q-krss-1",
            "patch_type": "few_shot",
            "question": "Which services use tunnel T1?",
            "primary_knowledge_type": "few_shot",
        },
        {
            "ticket_id": "q-krss-1",
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
async def test_krss_analyzer_clamps_and_sanitizes_malformed_confidence_values():
    analyzer = KRSSAnalyzer(
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


def test_build_diagnosis_context_extracts_structured_failure_diff_and_relevant_fragments():
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
    assert context["failure_diff"]["entity_or_relation_problem"] is True
    assert context["failure_diff"]["return_shape_problem"] is False
    assert "unrelated noise" not in json.dumps(context, ensure_ascii=False)
    assert context["relevant_prompt_fragments"]["few_shot_fragment"]
    assert context["recent_applied_repairs"][0]["knowledge_type"] == "few_shot"
