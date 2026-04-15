from __future__ import annotations

import logging
from functools import lru_cache
from typing import Dict, Optional, Protocol

from shared.models import IssueTicket, KRSSAnalysisRecord, KRSSIssueTicketResponse, KnowledgeRepairSuggestionRequest, PromptSnapshotResponse

from .analysis import KRSSAnalyzer
from .clients import CGSPromptSnapshotClient, KnowledgeOpsRepairApplyClient, OpenAICompatibleKRSSAnalyzer
from .config import Settings, get_settings
from .repository import RepairRepository, _utc_now

logger = logging.getLogger("repair_service")


class PromptSnapshotFetcher(Protocol):
    async def fetch(self, id: str) -> PromptSnapshotResponse:
        ...


class KnowledgeRepairApplier(Protocol):
    async def apply(self, payload: KnowledgeRepairSuggestionRequest) -> Dict[str, object] | None:
        ...


class RepairService:
    def __init__(
        self,
        repository: RepairRepository,
        prompt_snapshot_client: PromptSnapshotFetcher,
        analyzer: KRSSAnalyzer,
        apply_client: KnowledgeRepairApplier,
        settings: Optional[Settings] = None,
    ) -> None:
        self.repository = repository
        self.prompt_snapshot_client = prompt_snapshot_client
        self.analyzer = analyzer
        self.apply_client = apply_client
        self.settings = settings

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
        settings = self.settings or get_settings()
        return {
            "storage": settings.data_dir,
            "cgs_base_url": settings.cgs_base_url,
            "knowledge_ops_repairs_apply_url": settings.knowledge_ops_repairs_apply_url,
            "llm_enabled": settings.llm_enabled,
            "llm_model": settings.llm_model_name,
            "llm_configured": True,
            "mode": "krss_apply",
            "diagnosis_mode": "llm",
        }

    @staticmethod
    def _analysis_id_for_ticket(ticket_id: str) -> str:
        return f"analysis-{ticket_id}"


def _build_analyzer(settings: Settings) -> KRSSAnalyzer:
    return KRSSAnalyzer(
        diagnosis_client=OpenAICompatibleKRSSAnalyzer(
            base_url=settings.llm_base_url or "",
            api_key=settings.llm_api_key or "",
            model=settings.llm_model_name or "",
            timeout_seconds=settings.request_timeout_seconds,
            temperature=settings.llm_temperature,
            max_retries=settings.llm_max_retries,
            retry_base_delay_seconds=settings.llm_retry_base_delay_seconds,
        )
    )


def build_repair_service(settings: Settings) -> RepairService:
    return RepairService(
        repository=RepairRepository(data_dir=settings.data_dir),
        prompt_snapshot_client=CGSPromptSnapshotClient(
            base_url=settings.cgs_base_url,
            timeout_seconds=settings.request_timeout_seconds,
        ),
        analyzer=_build_analyzer(settings),
        apply_client=KnowledgeOpsRepairApplyClient(
            apply_url=settings.knowledge_ops_repairs_apply_url,
            capture_dir=settings.knowledge_ops_repairs_apply_capture_dir,
            timeout_seconds=settings.request_timeout_seconds,
        ),
        settings=settings,
    )


@lru_cache(maxsize=1)
def get_repair_service() -> RepairService:
    return build_repair_service(get_settings())
