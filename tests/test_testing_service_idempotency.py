from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.models import (
    EvaluationDimensions,
    EvaluationSummary,
    KRSSIssueTicketResponse,
    KnowledgeRepairSuggestionRequest,
    TuGraphExecutionResult,
)
from services.testing_service.app.clients import RepairServiceClient
from services.testing_service.app.service import EvaluationService


@pytest.mark.asyncio
async def test_issue_ticket_id_is_stable_for_same_qa_id():
    repo = MagicMock()
    repair_client = AsyncMock(spec=RepairServiceClient)
    repair_client.submit_issue_ticket.return_value = KRSSIssueTicketResponse(
        analysis_id="analysis-ticket-qa-123",
        id="qa-123",
        knowledge_repair_request=KnowledgeRepairSuggestionRequest(
            id="analysis-ticket-qa-123",
            suggestion="test",
            knowledge_types=["system_prompt"],
        ),
        knowledge_ops_response={"ok": True},
    )
    tugraph_client = AsyncMock()
    tugraph_client.execute.return_value = TuGraphExecutionResult(
        success=False,
        rows=[],
        row_count=0,
        error_message="Syntax error",
        elapsed_ms=1,
    )

    repo.get_golden.return_value = {
        "id": "qa-123",
        "golden_cypher": "MATCH (n) RETURN n",
        "golden_answer_json": json.dumps([]),
        "difficulty": "L3",
    }
    repo.get_submission.return_value = {
        "id": "qa-123",
        "question": "test question",
        "generation_run_id": "run-1",
        "generated_cypher": "MATCHH (n) RETURN n",
        "parse_summary": "parsed_json",
        "guardrail_summary": "accepted",
        "raw_output_snapshot": "{\"cypher\":\"MATCHH\"}",
        "input_prompt_snapshot": "PROMPT",
    }

    with patch("services.testing_service.app.service.evaluate_submission") as eval_fn:
        eval_fn.return_value = EvaluationSummary(
            verdict="fail",
            dimensions=EvaluationDimensions(
                syntax_validity="fail",
                schema_alignment="pass",
                result_correctness="fail",
                question_alignment="fail",
            ),
            symptom="test",
            evidence=[],
        )
        svc = EvaluationService(repository=repo, repair_client=repair_client, tugraph_client=tugraph_client, llm_client=None)
        await svc._evaluate_ready_pair("qa-123")

    sent_ticket = repair_client.submit_issue_ticket.await_args.args[0]
    assert sent_ticket.ticket_id == "ticket-qa-123"
