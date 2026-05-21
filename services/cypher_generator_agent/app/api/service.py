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
from services.cypher_generator_agent.app.clarification_layer.service import ClarificationQuestionService
from services.cypher_generator_agent.app.infrastructure.clients import TestingAgentClient
from services.cypher_generator_agent.app.infrastructure.config import get_settings
from services.cypher_generator_agent.app.infrastructure.errors import OntologyGenerationError
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
        clarification_service: ClarificationQuestionService | None = None,
    ) -> None:
        self.testing_client = testing_client
        self.pipeline = pipeline or OntologyGenerationPipeline.from_default_resources()
        self.clarification_service = clarification_service or ClarificationQuestionService.from_default_resources()

    async def ingest_question(self, request: QAQuestionRequest) -> GenerationRunResult:
        generation_run_id = str(uuid4())
        try:
            result = self.pipeline.generate(request.question, trace_id=generation_run_id)
        except ClarificationNeeded as exc:
            clarification = self.clarification_service.build(exc, original_question=request.question)
            await self.testing_client.submit_generation_failure(
                CgaGenerationNonSuccessReport(
                    id=request.id,
                    question=request.question,
                    generation_run_id=generation_run_id,
                    generation_status="clarification_required",
                    input_prompt_snapshot=json.dumps(clarification, ensure_ascii=False),
                    clarification=clarification,
                )
            )
            return GenerationRunResult(
                generation_run_id=generation_run_id,
                generation_status="clarification_required",
            )
        except OntologyGenerationError as exc:
            await self.testing_client.submit_generation_failure(
                CgaGenerationNonSuccessReport(
                    id=request.id,
                    question=request.question,
                    generation_run_id=generation_run_id,
                    generation_status="service_failed",
                    input_prompt_snapshot=json.dumps(
                        {
                            "schema_version": "cga_trace_v2",
                            "trace_profile": "ontology",
                            "question": request.question,
                            "generation_run_id": generation_run_id,
                            "generation_status": "service_failed",
                            "failure": {
                                "stage": exc.stage,
                                "message": exc.message,
                                "payload": exc.payload,
                            },
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    failure_reason="semantic_contract_unaligned",
                )
            )
            return GenerationRunResult(
                generation_run_id=generation_run_id,
                generation_status="service_failed",
                reason="semantic_contract_unaligned",
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
        testing_client=TestingAgentClient(
            base_url=settings.testing_agent_url,
            timeout_seconds=settings.request_timeout_seconds,
        ),
    )
