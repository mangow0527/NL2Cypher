from __future__ import annotations

import json
from functools import lru_cache
from typing import Dict, Optional, Protocol
from uuid import uuid4

from .models import (
    GeneratedCypherSubmissionRequest,
    GenerationRunResult,
    QAQuestionRequest,
)
from services.cypher_generator_agent.app.infrastructure.clients import TestingAgentClient
from services.cypher_generator_agent.app.infrastructure.config import get_settings


class GeneratedCypherSubmitter(Protocol):
    async def submit(self, payload: GeneratedCypherSubmissionRequest) -> Dict[str, object]:
        ...


class CypherGeneratorAgentService:
    def __init__(
        self,
        *,
        testing_client: GeneratedCypherSubmitter,
    ) -> None:
        self.testing_client = testing_client

    async def ingest_question(self, request: QAQuestionRequest) -> GenerationRunResult:
        generation_run_id = str(uuid4())
        snapshot = build_io_stub_trace(
            qa_id=request.id,
            question=request.question,
            trace_id=generation_run_id,
        )
        await self.testing_client.submit(
            GeneratedCypherSubmissionRequest(
                id=request.id,
                question=request.question,
                generation_run_id=generation_run_id,
                generated_cypher="",
                input_prompt_snapshot=json.dumps(snapshot, ensure_ascii=False, indent=2),
            )
        )
        return GenerationRunResult(
            generation_run_id=generation_run_id,
            generation_status="submitted_to_testing",
        )


def build_io_stub_trace(*, question: str, trace_id: str, qa_id: Optional[str] = None) -> Dict[str, object]:
    input_payload = {"id": qa_id, "question": question} if qa_id is not None else {"question": question}
    return {
        "schema_version": "cga_io_stub_v1",
        "trace_id": trace_id,
        "input": input_payload,
        "output": {"generated_cypher": ""},
        "internal_flow": {},
    }


def get_generator_status() -> Dict[str, object]:
    return {
        "status": "ok",
        "pipeline": "io_stub",
        "internal_flow": {},
    }


@lru_cache(maxsize=1)
def get_workflow_service() -> CypherGeneratorAgentService:
    settings = get_settings()
    return CypherGeneratorAgentService(
        testing_client=TestingAgentClient(
            base_url=settings.testing_agent_url,
            timeout_seconds=settings.request_timeout_seconds,
        ),
    )
