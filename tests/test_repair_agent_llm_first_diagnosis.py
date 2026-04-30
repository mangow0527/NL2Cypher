from __future__ import annotations

from typing import Any, Dict

import pytest

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
)
from services.repair_agent.app.analysis import RepairAnalyzer


def _make_ticket() -> IssueTicket:
    return IssueTicket(
        ticket_id="ticket-repair-2",
        id="q-repair-2",
        difficulty="L4",
        question="Show services impacted by protocol BGP on link L1.",
        expected=ExpectedPayload(cypher="MATCH (s:Service) RETURN s", answer=[]),
        actual=ActualPayload(
            generated_cypher="MATCH (p:Protocol) RETURN p",
            execution=ExecutionResult(success=True, rows=[], row_count=0),
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
                        message="Schema path was incomplete",
                        order_sensitive=False,
                        expected_row_count=0,
                        actual_row_count=0,
                    ),
                    semantic_check=SemanticCheck(
                        status="fail",
                        message="The query focused on Protocol but skipped Link and Service traversal.",
                        raw_output=None,
                    ),
                ),
            ),
            secondary_signals=SecondarySignals(
                gleu=GLEUSignal(score=0.44, tokenizer="whitespace", min_n=1, max_n=4),
                jaro_winkler_similarity=JaroWinklerSimilaritySignal(
                    score=0.71,
                    normalization="lightweight",
                    library="jellyfish",
                ),
            ),
        ),
        generation_evidence={"generation_run_id": "run-repair-2", "attempt_no": 1, "input_prompt_snapshot": "PROMPT SNAPSHOT"},
    )


class _LowConfidenceDiagnosisClient:
    async def diagnose(self, context: Dict[str, Any]) -> Dict[str, Any]:
        assert context["question"] == "Show services impacted by protocol BGP on link L1."
        return {
            "repairable": True,
            "non_repairable_reason": "",
            "primary_knowledge_type": "business_knowledge",
            "secondary_knowledge_types": ["few_shot"],
            "confidence": 0.41,
            "suggestion": "Strengthen graph traversal guidance for Link, Protocol, and Service reasoning.",
            "rationale": "The failure could come from several missing knowledge layers.",
        }


@pytest.mark.asyncio
async def test_repair_agent_analyzer_uses_llm_primary_type_without_extra_validation():
    analyzer = RepairAnalyzer(
        diagnosis_client=_LowConfidenceDiagnosisClient(),
    )

    result = await analyzer.analyze(_make_ticket(), "PROMPT SNAPSHOT")

    assert result.id == "q-repair-2"
    assert result.knowledge_types == ["business_knowledge"]
    assert result.primary_knowledge_type == "business_knowledge"
    assert result.secondary_knowledge_types == ["few_shot"]
    assert result.suggestion == "Strengthen graph traversal guidance for Link, Protocol, and Service reasoning."
    assert result.confidence == pytest.approx(0.41)
    assert result.rationale == "The failure could come from several missing knowledge layers."
    assert result.to_request().model_dump() == {
        "id": "q-repair-2",
        "suggestion": "Strengthen graph traversal guidance for Link, Protocol, and Service reasoning.",
        "knowledge_types": ["business_knowledge"],
    }


@pytest.mark.asyncio
async def test_repair_agent_analyzer_preserves_secondary_types_as_supporting_diagnosis_only():
    analyzer = RepairAnalyzer(
        diagnosis_client=_LowConfidenceDiagnosisClient(),
    )

    result = await analyzer.analyze(_make_ticket(), "PROMPT SNAPSHOT")

    assert result.knowledge_types == ["business_knowledge"]
    assert result.secondary_knowledge_types == ["few_shot"]
    assert result.confidence == pytest.approx(0.41)
