from __future__ import annotations

from typing import Any, Dict, List

import pytest

from contracts.models import ActualAnswer, EvaluationDimensions, EvaluationSummary, ExpectedAnswer, IssueTicket
from services.repair_agent.app.analysis import KRSSAnalyzer


def _make_ticket() -> IssueTicket:
    return IssueTicket(
        id="q-krss-2",
        difficulty="L4",
        question="Show services impacted by protocol BGP on link L1.",
        expected=ExpectedAnswer(cypher="MATCH (s:Service) RETURN s", answer=[]),
        actual=ActualAnswer(generated_cypher="MATCH (p:Protocol) RETURN p", execution={"success": True, "rows": [], "row_count": 0}),
        evaluation=EvaluationSummary(
            verdict="fail",
            dimensions=EvaluationDimensions(
                syntax_validity="pass",
                schema_alignment="fail",
                result_correctness="fail",
                question_alignment="pass",
            ),
            symptom="Schema path was incomplete",
            evidence=["The query focused on Protocol but skipped Link and Service traversal."],
        ),
    )


class _LowConfidenceDiagnosisClient:
    async def diagnose(self, context: Dict[str, Any]) -> Dict[str, Any]:
        assert context["question"] == "Show services impacted by protocol BGP on link L1."
        return {
            "primary_knowledge_type": "business_knowledge",
            "secondary_knowledge_types": ["few_shot"],
            "confidence": 0.41,
            "suggestion": "Strengthen graph traversal guidance for Link, Protocol, and Service reasoning.",
            "rationale": "The failure could come from several missing knowledge layers.",
            "need_validation": True,
            "candidate_patch_types": ["business_knowledge", "few_shot"],
        }


@pytest.mark.asyncio
async def test_krss_analyzer_narrows_knowledge_types_using_minimal_patch_experiments():
    experiment_calls: List[str] = []

    async def experiment_runner(ticket: IssueTicket, context: Dict[str, Any], patch_type: str, diagnosis: Dict[str, Any]) -> Dict[str, Any]:
        assert ticket.id == "q-krss-2"
        assert context["failure_diff"]["entity_or_relation_problem"] is True
        assert diagnosis["confidence"] == 0.41
        experiment_calls.append(patch_type)
        if patch_type == "business_knowledge":
            return {"improved": True, "confidence": 0.88}
        if patch_type == "few_shot":
            return {"improved": True, "confidence": 0.66}
        return {"improved": False, "confidence": 0.2}

    analyzer = KRSSAnalyzer(
        diagnosis_client=_LowConfidenceDiagnosisClient(),
        min_confidence_for_direct_return=0.8,
        experiment_runner=experiment_runner,
    )

    result = await analyzer.analyze(_make_ticket(), "PROMPT SNAPSHOT")

    assert result.id == "q-krss-2"
    assert result.used_experiments is True
    assert result.knowledge_types == ["business_knowledge"]
    assert result.primary_knowledge_type == "business_knowledge"
    assert result.secondary_knowledge_types == ["few_shot"]
    assert result.candidate_patch_types == ["business_knowledge", "few_shot"]
    assert result.validation_mode == "lightweight"
    assert result.validation_result["validated_patch_types"] == ["business_knowledge", "few_shot"]
    assert result.suggestion == "Strengthen graph traversal guidance for Link, Protocol, and Service reasoning."
    assert result.confidence == pytest.approx(0.88)
    assert result.rationale == "The failure could come from several missing knowledge layers."
    assert result.to_request().model_dump() == {
        "id": "q-krss-2",
        "suggestion": "Strengthen graph traversal guidance for Link, Protocol, and Service reasoning.",
        "knowledge_types": ["business_knowledge"],
    }
    assert experiment_calls == ["business_knowledge", "few_shot"]


@pytest.mark.asyncio
async def test_krss_analyzer_prefers_only_the_best_improved_patch_type():
    async def experiment_runner(ticket: IssueTicket, context: Dict[str, Any], patch_type: str, diagnosis: Dict[str, Any]) -> Dict[str, Any]:
        assert ticket.id == "q-krss-2"
        assert context["question"] == "Show services impacted by protocol BGP on link L1."
        assert diagnosis["confidence"] == 0.41
        if patch_type == "few_shot":
            return {"improved": True, "confidence": 0.89}
        return {"improved": False, "confidence": 0.1}

    analyzer = KRSSAnalyzer(
        diagnosis_client=_LowConfidenceDiagnosisClient(),
        min_confidence_for_direct_return=0.8,
        experiment_runner=experiment_runner,
    )

    result = await analyzer.analyze(_make_ticket(), "PROMPT SNAPSHOT")

    assert result.used_experiments is True
    assert result.knowledge_types == ["few_shot"]
    assert result.confidence == pytest.approx(0.89)
    assert result.validation_result["validated_patch_types"] == ["few_shot"]
    assert result.validation_result["rejected_patch_types"] == ["business_knowledge"]
