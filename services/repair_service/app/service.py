from __future__ import annotations

from typing import Dict, Optional, Protocol

from shared.models import IssueTicket, KRSSAnalysisRecord, KRSSIssueTicketResponse, KnowledgeRepairSuggestionRequest, PromptSnapshotResponse

from .analysis import KRSSAnalysisResult, KRSSAnalyzer
from .clients import CGSPromptSnapshotClient, KnowledgeOpsRepairApplyClient, OpenAICompatibleKRSSAnalyzer
from .config import settings
from .repository import RepairRepository, _utc_now


class PromptSnapshotFetcher(Protocol):
    async def fetch(self, id: str) -> PromptSnapshotResponse:
        ...


class KnowledgeRepairApplier(Protocol):
    async def apply(self, payload: KnowledgeRepairSuggestionRequest) -> Dict[str, object] | None:
        ...


class _DeterministicKRSSDiagnosisClient:
    async def diagnose(self, ticket: IssueTicket, prompt_snapshot: str) -> Dict[str, object]:
        del prompt_snapshot

        dimensions = ticket.evaluation.dimensions
        if dimensions.syntax_validity == "fail":
            return {
                "knowledge_types": ["cypher_syntax", "system_prompt"],
                "confidence": 0.9,
                "suggestion": "Add Cypher syntax guardrails and a system prompt rule that rejects malformed query patterns.",
                "rationale": "The failing ticket shows a syntax-validity error, so the weakest link is syntax guidance rather than business context.",
                "need_experiments": False,
                "candidate_patch_types": [],
            }

        if dimensions.schema_alignment == "fail":
            return {
                "knowledge_types": ["business_knowledge", "system_prompt"],
                "confidence": 0.88,
                "suggestion": "Add business-knowledge constraints and prompt rules that only allow graph-valid labels, relations, and properties.",
                "rationale": "The generated Cypher violates schema expectations, so KRSS should route a business-knowledge-focused repair suggestion.",
                "need_experiments": False,
                "candidate_patch_types": [],
            }

        if dimensions.question_alignment == "fail" or dimensions.result_correctness == "fail":
            return {
                "knowledge_types": ["business_knowledge", "few_shot"],
                "confidence": 0.85,
                "suggestion": "Add business-term mapping guidance and a few_shot example that matches the failed question pattern.",
                "rationale": "The query missed the intended semantics, which usually points to missing business context or missing examples.",
                "need_experiments": False,
                "candidate_patch_types": [],
            }

        return {
            "knowledge_types": ["system_prompt"],
            "confidence": 0.8,
            "suggestion": "Tighten the system prompt so future generations preserve the expected question intent and output contract.",
            "rationale": "Fallback deterministic KRSS diagnosis.",
            "need_experiments": False,
            "candidate_patch_types": [],
        }


class RepairService:
    def __init__(
        self,
        repository: RepairRepository,
        prompt_snapshot_client: PromptSnapshotFetcher,
        analyzer: KRSSAnalyzer,
        apply_client: KnowledgeRepairApplier,
    ) -> None:
        self.repository = repository
        self.prompt_snapshot_client = prompt_snapshot_client
        self.analyzer = analyzer
        self.apply_client = apply_client

    async def create_issue_ticket_response(self, issue_ticket: IssueTicket) -> KRSSIssueTicketResponse:
        existing = self.repository.get_analysis(self._analysis_id_for_ticket(issue_ticket.ticket_id))
        if existing is not None:
            return KRSSIssueTicketResponse(
                analysis_id=existing.analysis_id,
                id=existing.id,
                knowledge_repair_request=existing.knowledge_repair_request,
                knowledge_ops_response=existing.knowledge_ops_response,
                applied=existing.applied,
            )
        prompt_snapshot_response = await self.prompt_snapshot_client.fetch(issue_ticket.id)
        analysis = await self.analyzer.analyze(issue_ticket, prompt_snapshot_response.input_prompt_snapshot)
        request = analysis.to_request()
        knowledge_ops_response = await self.apply_client.apply(request)

        record = KRSSAnalysisRecord(
            analysis_id=self._analysis_id_for_ticket(issue_ticket.ticket_id),
            ticket_id=issue_ticket.ticket_id,
            id=issue_ticket.id,
            prompt_snapshot=prompt_snapshot_response.input_prompt_snapshot,
            knowledge_repair_request=request,
            knowledge_ops_response=knowledge_ops_response,
            confidence=analysis.confidence,
            rationale=analysis.rationale,
            used_experiments=analysis.used_experiments,
            created_at=_utc_now(),
            applied_at=_utc_now(),
        )
        self.repository.save_analysis(record)
        return KRSSIssueTicketResponse(
            analysis_id=record.analysis_id,
            id=record.id,
            knowledge_repair_request=record.knowledge_repair_request,
            knowledge_ops_response=record.knowledge_ops_response,
            applied=record.applied,
        )

    def get_analysis(self, analysis_id: str) -> Optional[KRSSAnalysisRecord]:
        return self.repository.get_analysis(analysis_id)

    def get_service_status(self) -> Dict[str, object]:
        return {
            "storage": settings.data_dir,
            "cgs_base_url": settings.cgs_base_url,
            "knowledge_ops_repairs_apply_url": settings.knowledge_ops_repairs_apply_url,
            "llm_enabled": settings.llm_enabled,
            "llm_model": settings.llm_model_name,
            "mode": "krss_apply",
        }

    @staticmethod
    def _analysis_id_for_ticket(ticket_id: str) -> str:
        return f"analysis-{ticket_id}"


def _build_analyzer() -> KRSSAnalyzer:
    diagnosis_client: object
    if settings.llm_enabled and settings.llm_base_url and settings.llm_api_key and settings.llm_model_name:
        diagnosis_client = OpenAICompatibleKRSSAnalyzer(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model_name,
            timeout_seconds=settings.request_timeout_seconds,
            temperature=settings.llm_temperature,
        )
    else:
        diagnosis_client = _DeterministicKRSSDiagnosisClient()

    return KRSSAnalyzer(diagnosis_client=diagnosis_client)


repair_service = RepairService(
    repository=RepairRepository(data_dir=settings.data_dir),
    prompt_snapshot_client=CGSPromptSnapshotClient(
        base_url=settings.cgs_base_url,
        timeout_seconds=settings.request_timeout_seconds,
    ),
    analyzer=_build_analyzer(),
    apply_client=KnowledgeOpsRepairApplyClient(
        apply_url=settings.knowledge_ops_repairs_apply_url,
        capture_dir=settings.knowledge_ops_repairs_apply_capture_dir,
        timeout_seconds=settings.request_timeout_seconds,
    ),
)
