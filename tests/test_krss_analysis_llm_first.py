from __future__ import annotations

import math
from typing import Any, Dict, List

import pytest

from shared.models import ActualAnswer, EvaluationDimensions, EvaluationSummary, ExpectedAnswer, IssueTicket
from services.repair_service.app.analysis import KRSSAnalyzer


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

    async def diagnose(self, ticket: IssueTicket, prompt_snapshot: str) -> Dict[str, Any]:
        self.calls.append({"ticket_id": ticket.id, "prompt_snapshot": prompt_snapshot})
        return {
            "knowledge_types": ["schema", "few-shot"],
            "confidence": 0.93,
            "suggestion": "Add a schema-grounded example showing how Service connects to Tunnel.",
            "rationale": "The prompt missed a key relation pattern.",
            "need_experiments": True,
            "candidate_patch_types": ["schema", "few-shot"],
        }


@pytest.mark.asyncio
async def test_krss_analyzer_returns_direct_result_for_high_confidence_llm_diagnosis():
    client = _HighConfidenceDiagnosisClient()
    experiment_calls: List[Dict[str, Any]] = []

    async def experiment_runner(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        experiment_calls.append({"args": args, "kwargs": kwargs})
        return {"improved": False}

    analyzer = KRSSAnalyzer(
        diagnosis_client=client,
        min_confidence_for_direct_return=0.8,
        experiment_runner=experiment_runner,
    )

    result = await analyzer.analyze(_make_ticket(), "PROMPT SNAPSHOT")

    assert result.id == "q-krss-1"
    assert result.knowledge_types == ["schema", "few-shot"]
    assert result.suggestion == "Add a schema-grounded example showing how Service connects to Tunnel."
    assert result.confidence == pytest.approx(0.93)
    assert result.rationale == "The prompt missed a key relation pattern."
    assert result.used_experiments is False
    assert result.to_request().model_dump() == {
        "id": "q-krss-1",
        "suggestion": "Add a schema-grounded example showing how Service connects to Tunnel.",
        "knowledge_types": ["schema", "few-shot"],
    }
    assert client.calls == [{"ticket_id": "q-krss-1", "prompt_snapshot": "PROMPT SNAPSHOT"}]
    assert experiment_calls == []


class _MalformedConfidenceDiagnosisClient:
    async def diagnose(self, ticket: IssueTicket, prompt_snapshot: str) -> Dict[str, Any]:
        assert ticket.id == "q-krss-1"
        assert prompt_snapshot == "PROMPT SNAPSHOT"
        return {
            "knowledge_types": ["schema"],
            "confidence": float("nan"),
            "suggestion": "Keep the schema hint focused on the tunnel relation.",
            "rationale": "Bad confidence payload should not leak through.",
            "need_experiments": False,
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
    assert result.knowledge_types == ["schema"]
    assert result.suggestion == "Keep the schema hint focused on the tunnel relation."
