from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol, cast

from shared.models import IssueTicket, KnowledgeRepairSuggestionRequest, KnowledgeType


class KRSSDiagnosisClient(Protocol):
    async def diagnose(self, ticket: IssueTicket, prompt_snapshot: str) -> Dict[str, Any]:
        ...


ExperimentRunner = Callable[[IssueTicket, str, KnowledgeType, Dict[str, Any]], Awaitable[Dict[str, Any]]]


@dataclass(slots=True)
class KRSSAnalysisResult:
    id: str
    suggestion: str
    knowledge_types: List[KnowledgeType]
    confidence: float
    rationale: str = ""
    used_experiments: bool = False

    def to_request(self) -> KnowledgeRepairSuggestionRequest:
        return KnowledgeRepairSuggestionRequest(
            id=self.id,
            suggestion=self.suggestion,
            knowledge_types=self.knowledge_types,
        )


class KRSSAnalyzer:
    def __init__(
        self,
        diagnosis_client: KRSSDiagnosisClient,
        *,
        min_confidence_for_direct_return: float = 0.8,
        experiment_runner: Optional[ExperimentRunner] = None,
    ) -> None:
        self.diagnosis_client = diagnosis_client
        self.min_confidence_for_direct_return = min_confidence_for_direct_return
        self.experiment_runner = experiment_runner

    async def analyze(self, ticket: IssueTicket, prompt_snapshot: str) -> KRSSAnalysisResult:
        diagnosis = await self.diagnosis_client.diagnose(ticket, prompt_snapshot)

        initial_knowledge_types = self._coerce_knowledge_types(diagnosis.get("knowledge_types"))
        suggestion = str(diagnosis.get("suggestion") or diagnosis.get("rationale") or "Review and repair the missing knowledge.")
        rationale = str(diagnosis.get("rationale") or "")
        confidence = self._coerce_confidence(diagnosis.get("confidence"))
        need_experiments = bool(diagnosis.get("need_experiments"))
        candidate_patch_types = self._coerce_knowledge_types(diagnosis.get("candidate_patch_types"))

        if confidence >= self.min_confidence_for_direct_return or not need_experiments:
            return KRSSAnalysisResult(
                id=ticket.id,
                suggestion=suggestion,
                knowledge_types=initial_knowledge_types,
                confidence=confidence,
                rationale=rationale,
                used_experiments=False,
            )

        if self.experiment_runner is None or not candidate_patch_types:
            return KRSSAnalysisResult(
                id=ticket.id,
                suggestion=suggestion,
                knowledge_types=initial_knowledge_types,
                confidence=confidence,
                rationale=rationale,
                used_experiments=False,
            )

        best_patch_types: List[KnowledgeType] = []
        best_patch_metric: Optional[float] = None
        best_confidence = confidence
        best_suggestion = suggestion

        for patch_type in candidate_patch_types:
            experiment_result = await self.experiment_runner(ticket, prompt_snapshot, patch_type, diagnosis)
            if self._is_improved(experiment_result):
                patch_metric = self._coerce_patch_metric(experiment_result, fallback=confidence)
                if best_patch_metric is None or patch_metric > best_patch_metric:
                    best_patch_types = [patch_type]
                    best_patch_metric = patch_metric
                elif patch_metric == best_patch_metric:
                    best_patch_types.append(patch_type)

                best_confidence = max(best_confidence, self._coerce_confidence(experiment_result.get("confidence"), fallback=best_confidence))
                experiment_suggestion = experiment_result.get("suggestion")
                if experiment_suggestion:
                    best_suggestion = str(experiment_suggestion)

        return KRSSAnalysisResult(
            id=ticket.id,
            suggestion=best_suggestion,
            knowledge_types=best_patch_types or initial_knowledge_types,
            confidence=best_confidence,
            rationale=rationale,
            used_experiments=bool(candidate_patch_types),
        )

    def _coerce_knowledge_types(self, raw_value: Any) -> List[KnowledgeType]:
        if not isinstance(raw_value, list):
            return []

        allowed = {"schema", "cypher_syntax", "few-shot", "system_prompt", "business_knowledge"}
        knowledge_types: List[KnowledgeType] = []
        for item in raw_value:
            if isinstance(item, str) and item in allowed and item not in knowledge_types:
                knowledge_types.append(cast(KnowledgeType, item))
        return knowledge_types

    def _coerce_confidence(self, raw_value: Any, *, fallback: float = 0.0) -> float:
        try:
            confidence = float(raw_value)
        except (TypeError, ValueError):
            return fallback
        if not math.isfinite(confidence):
            return fallback
        return min(1.0, max(0.0, confidence))

    def _coerce_patch_metric(self, result: Dict[str, Any], *, fallback: float) -> float:
        confidence = self._coerce_confidence(result.get("confidence"), fallback=-1.0)
        if confidence >= 0.0:
            return confidence

        try:
            score = float(result.get("score"))
        except (TypeError, ValueError):
            return fallback
        if not math.isfinite(score):
            return fallback
        return min(1.0, max(0.0, score))

    def _is_improved(self, result: Dict[str, Any]) -> bool:
        improved = result.get("improved")
        if isinstance(improved, bool):
            return improved

        score_delta = result.get("score_delta")
        try:
            return float(score_delta) > 0.0
        except (TypeError, ValueError):
            return False
