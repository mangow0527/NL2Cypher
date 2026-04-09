from __future__ import annotations

import json
from typing import Dict, Optional

from shared.evaluation import evaluate_submission
from shared.models import (
    ActualAnswer,
    EvaluationSubmissionRequest,
    EvaluationSubmissionResponse,
    ExpectedAnswer,
    IssueTicket,
    QAGoldenRequest,
    QAGoldenResponse,
)

from .clients import RepairServiceClient
from .config import settings
from .repository import TestingRepository


class EvaluationService:
    def __init__(self, repository: TestingRepository, repair_client: RepairServiceClient) -> None:
        self.repository = repository
        self.repair_client = repair_client

    async def ingest_golden(self, request: QAGoldenRequest) -> QAGoldenResponse:
        self.repository.save_golden(request)
        submission = self.repository.get_submission(request.id)
        if submission is None:
            return QAGoldenResponse(id=request.id, status="received_golden_only")
        return await self._evaluate_ready_pair(request.id)

    async def ingest_submission(self, request: EvaluationSubmissionRequest) -> EvaluationSubmissionResponse:
        golden = self.repository.get_golden(request.id)
        status = "ready_to_evaluate" if golden else "waiting_for_golden"
        self.repository.save_submission(request, status=status)
        if golden is None:
            return EvaluationSubmissionResponse(id=request.id, status="waiting_for_golden")
        return await self._evaluate_ready_pair(request.id)

    async def _evaluate_ready_pair(self, id: str) -> EvaluationSubmissionResponse | QAGoldenResponse:
        golden = self.repository.get_golden(id)
        submission = self.repository.get_submission(id)
        if not golden or not submission:
            raise RuntimeError(f"Expected both golden and submission before evaluating id={id}")

        evaluation = evaluate_submission(
            question=submission["question"],
            expected_cypher=golden["golden_cypher"],
            expected_answer=json.loads(golden["golden_answer_json"]),
            actual_cypher=submission["generated_cypher"],
            execution=_parse_execution(submission["execution_json"]),
            loaded_knowledge_tags=json.loads(submission["knowledge_context_json"])["loaded_knowledge_tags"],
        )

        if evaluation.verdict == "pass":
            self.repository.mark_submission_status(id, "passed")
            return EvaluationSubmissionResponse(id=id, status="passed", verdict=evaluation.verdict)

        ticket = IssueTicket(
            id=id,
            difficulty=golden["difficulty"],
            question=submission["question"],
            expected=ExpectedAnswer(cypher=golden["golden_cypher"], answer=json.loads(golden["golden_answer_json"])),
            actual=ActualAnswer(
                generated_cypher=submission["generated_cypher"],
                execution=_parse_execution(submission["execution_json"]),
            ),
            knowledge_context=json.loads(submission["knowledge_context_json"]),
            evaluation=evaluation,
        )
        self.repository.save_issue_ticket(ticket)
        await self.repair_client.submit_issue_ticket(ticket)
        return EvaluationSubmissionResponse(
            id=id,
            status="issue_ticket_created",
            issue_ticket_id=ticket.ticket_id,
            verdict=evaluation.verdict,
        )

    def get_evaluation_status(self, id: str) -> Dict[str, object]:
        golden = self.repository.get_golden(id)
        submission = self.repository.get_submission(id)
        return {
            "id": id,
            "has_golden": golden is not None,
            "has_submission": submission is not None,
            "golden": golden,
            "submission": submission,
        }

    def get_issue_ticket(self, ticket_id: str) -> Optional[IssueTicket]:
        return self.repository.get_issue_ticket(ticket_id)

    def get_service_status(self) -> Dict[str, object]:
        return {
            "storage": settings.db_path,
            "repair_service_url": settings.repair_service_url,
            "mode": "evaluation_router",
        }


repository = TestingRepository(db_path=settings.db_path)
validation_service = EvaluationService(
    repository=repository,
    repair_client=RepairServiceClient(
        base_url=settings.repair_service_url,
        timeout_seconds=settings.request_timeout_seconds,
    ),
)


def _parse_execution(payload: str):
    from shared.models import TuGraphExecutionResult

    return TuGraphExecutionResult.model_validate_json(payload)
