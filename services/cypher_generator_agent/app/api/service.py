from __future__ import annotations

import json
from functools import lru_cache
from typing import Dict, Protocol
from uuid import uuid4

from .models import (
    CgaGenerationNonSuccessReport,
    GeneratedCypherSubmissionRequest,
    GenerationRunResult,
    QAQuestionRequest,
)
from services.cypher_generator_agent.app.clarification_layer.errors import ClarificationNeeded
from services.cypher_generator_agent.app.infrastructure.clients import TestingAgentClient
from services.cypher_generator_agent.app.infrastructure.config import get_settings
from services.cypher_generator_agent.app.runtime_pipeline import OntologyGenerationPipeline


class GeneratedCypherSubmitter(Protocol):
    async def submit(self, payload: GeneratedCypherSubmissionRequest) -> Dict[str, object]:
        ...

    async def submit_generation_failure(self, payload: CgaGenerationNonSuccessReport) -> Dict[str, object]:
        ...


class CypherGeneratorAgentService:
    def __init__(
        self,
        *,
        testing_client: GeneratedCypherSubmitter,
        pipeline: OntologyGenerationPipeline | None = None,
    ) -> None:
        self.testing_client = testing_client
        self.pipeline = pipeline or OntologyGenerationPipeline.from_default_resources()

    async def ingest_question(self, request: QAQuestionRequest) -> GenerationRunResult:
        generation_run_id = str(uuid4())
        try:
            result = self.pipeline.generate(request.question, trace_id=generation_run_id)
        except ClarificationNeeded as exc:
            await self.testing_client.submit_generation_failure(
                CgaGenerationNonSuccessReport(
                    id=request.id,
                    question=request.question,
                    generation_run_id=generation_run_id,
                    generation_status="clarification_required",
                    input_prompt_snapshot=json.dumps(exc.clarification, ensure_ascii=False),
                    clarification=exc.clarification,
                )
            )
            return GenerationRunResult(
                generation_run_id=generation_run_id,
                generation_status="clarification_required",
            )

        snapshot = json.dumps(result.trace.to_dict(), ensure_ascii=False, indent=2)
        await self.testing_client.submit(
            GeneratedCypherSubmissionRequest(
                id=request.id,
                question=request.question,
                generation_run_id=generation_run_id,
                generated_cypher=result.cypher,
                input_prompt_snapshot=snapshot,
            )
        )
        return GenerationRunResult(
            generation_run_id=generation_run_id,
            generation_status="submitted_to_testing",
        )

    async def retry_pending_deliveries(self) -> None:
        return None


def get_generator_status() -> Dict[str, object]:
    settings = get_settings()
    return {
        "status": "ok",
        "pipeline": "runtime_pipeline",
        "data_dir": settings.data_dir,
    }


@lru_cache(maxsize=1)
def get_workflow_service() -> CypherGeneratorAgentService:
    settings = get_settings()
    return CypherGeneratorAgentService(
        testing_client=TestingAgentClient(base_url=settings.testing_agent_url),
    )
