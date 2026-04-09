from __future__ import annotations

import json
import logging
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

from .clients import LLMEvaluationClient, RepairServiceClient
from .config import settings
from .repository import TestingRepository

logger = logging.getLogger("testing_service")


class EvaluationService:
    def __init__(
        self,
        repository: TestingRepository,
        repair_client: RepairServiceClient,
        llm_client: Optional[LLMEvaluationClient] = None,
    ) -> None:
        self.repository = repository
        self.repair_client = repair_client
        self.llm_client = llm_client

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

        execution = _parse_execution(submission["execution_json"])
        expected_answer = json.loads(golden["golden_answer_json"])
        knowledge_tags = json.loads(submission["knowledge_context_json"])["loaded_knowledge_tags"]

        evaluation = evaluate_submission(
            question=submission["question"],
            expected_cypher=golden["golden_cypher"],
            expected_answer=expected_answer,
            actual_cypher=submission["generated_cypher"],
            execution=execution,
            loaded_knowledge_tags=knowledge_tags,
        )

        if evaluation.verdict != "pass" and self.llm_client is not None:
            evaluation = await self._llm_re_evaluate(
                evaluation=evaluation,
                question=submission["question"],
                expected_cypher=golden["golden_cypher"],
                expected_answer=expected_answer,
                actual_cypher=submission["generated_cypher"],
                execution=execution,
            )

        if evaluation.verdict == "pass":
            self.repository.mark_submission_status(id, "passed")
            return EvaluationSubmissionResponse(id=id, status="passed", verdict=evaluation.verdict)

        ticket = IssueTicket(
            id=id,
            difficulty=golden["difficulty"],
            question=submission["question"],
            expected=ExpectedAnswer(cypher=golden["golden_cypher"], answer=expected_answer),
            actual=ActualAnswer(
                generated_cypher=submission["generated_cypher"],
                execution=execution,
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

    async def _llm_re_evaluate(
        self,
        evaluation,
        question: str,
        expected_cypher: str,
        expected_answer,
        actual_cypher: str,
        execution,
    ):
        logger.info("Triggering LLM re-evaluation for question: %s", question)
        llm_result = await self.llm_client.evaluate(
            question=question,
            expected_cypher=expected_cypher,
            expected_answer=expected_answer,
            actual_cypher=actual_cypher,
            actual_result=execution.rows,
            rule_based_verdict=evaluation.verdict,
            rule_based_dimensions=evaluation.dimensions.model_dump(),
        )
        if llm_result is None:
            logger.warning("LLM re-evaluation returned None, keeping rule-based verdict")
            return evaluation

        dimensions = evaluation.dimensions
        llm_result_correctness = llm_result.get("result_correctness")
        llm_question_alignment = llm_result.get("question_alignment")
        reasoning = llm_result.get("reasoning", "")
        confidence = llm_result.get("confidence", 0.0)

        if llm_result_correctness == "pass" and dimensions.result_correctness == "fail":
            dimensions.result_correctness = "pass"
            evaluation.evidence.append(f"[LLM override] result_correctness flipped to pass: {reasoning}")
            logger.info("LLM overrode result_correctness to pass (confidence=%.2f)", confidence)

        if llm_question_alignment == "pass" and dimensions.question_alignment == "fail":
            dimensions.question_alignment = "pass"
            evaluation.evidence.append(f"[LLM override] question_alignment flipped to pass: {reasoning}")
            logger.info("LLM overrode question_alignment to pass (confidence=%.2f)", confidence)

        evaluation.dimensions = dimensions
        failures = [
            dimensions.syntax_validity,
            dimensions.schema_alignment,
            dimensions.result_correctness,
            dimensions.question_alignment,
        ].count("fail")

        if failures == 0:
            evaluation.verdict = "pass"
        elif failures == 4 or dimensions.syntax_validity == "fail":
            evaluation.verdict = "fail"
        else:
            evaluation.verdict = "partial_fail"

        return evaluation

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
            "storage": settings.data_dir,
            "repair_service_url": settings.repair_service_url,
            "llm_enabled": settings.llm_enabled,
            "llm_model": settings.llm_model,
            "mode": "evaluation_router",
        }


repository = TestingRepository(data_dir=settings.data_dir)

llm_client = None
if settings.llm_enabled and settings.llm_base_url and settings.llm_api_key and settings.llm_model:
    llm_client = LLMEvaluationClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout_seconds=settings.request_timeout_seconds,
        temperature=settings.llm_temperature,
    )

validation_service = EvaluationService(
    repository=repository,
    repair_client=RepairServiceClient(
        base_url=settings.repair_service_url,
        timeout_seconds=settings.request_timeout_seconds,
    ),
    llm_client=llm_client,
)


def _parse_execution(payload: str):
    from shared.models import TuGraphExecutionResult

    return TuGraphExecutionResult.model_validate_json(payload)
