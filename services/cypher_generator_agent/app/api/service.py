from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from typing import Dict, Optional, Protocol
from uuid import uuid4

from .models import (
    CgaGenerationNonSuccessReport,
    GeneratedCypherSubmissionRequest,
    GenerationRunResult,
    QAQuestionRequest,
)
from services.cypher_generator_agent.app.core.result import GenerationOutput
from services.cypher_generator_agent.app.infrastructure.clients import TestingAgentClient
from services.cypher_generator_agent.app.infrastructure.config import get_settings
from services.cypher_generator_agent.app.observability.trace import GraphTraceRecord


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
            submission_status="submitted_to_testing",
        )

    async def submit_generation_output(
        self,
        *,
        qa_id: str,
        question: str,
        generation_run_id: str,
        output: GenerationOutput,
    ) -> Dict[str, object]:
        payload = build_testing_agent_payload(
            qa_id=qa_id,
            question=question,
            generation_run_id=generation_run_id,
            output=output,
        )
        if isinstance(payload, GeneratedCypherSubmissionRequest):
            return await self.testing_client.submit(payload)
        return await self.testing_client.submit_generation_failure(payload)


def build_io_stub_trace(*, question: str, trace_id: str, qa_id: Optional[str] = None) -> Dict[str, object]:
    input_payload = {"id": qa_id, "question": question} if qa_id is not None else {"question": question}
    return {
        "schema_version": "cga_io_stub_v1",
        "trace_id": trace_id,
        "input": input_payload,
        "output": {"generated_cypher": ""},
        "internal_flow": {},
    }


def build_graph_trace_skeleton(
    *,
    question: str,
    trace_id: str,
    status: str,
    qa_id: Optional[str] = None,
) -> Dict[str, object]:
    started_at = datetime.now(timezone.utc).isoformat()
    trace = {
        "trace_schema_version": "cga_graph_trace_v1",
        "trace_id": trace_id,
        "question_id": qa_id or trace_id,
        "generation_run_id": trace_id,
        "source_question": question,
        "started_at": started_at,
        "finished_at": started_at,
        "final_status": status,
        "semantic_model": {},
        "stages": [],
        "final_outputs": {"user_visible_notices": []},
    }
    return trace


def build_semantic_parse_stub_output(*, question: str, trace_id: str, qa_id: Optional[str] = None) -> GenerationOutput:
    failure = {
        "reason": "unsupported_query_shape",
        "message": "Graph-native Cypher generation is not implemented in the IR-00 stub.",
        "suggested_rewrites": [],
    }
    trace = build_graph_trace_skeleton(
        qa_id=qa_id,
        question=question,
        trace_id=trace_id,
        status="unsupported_query_shape",
    )
    trace["final_outputs"]["failure"] = failure
    return GenerationOutput(
        status="unsupported_query_shape",
        trace=trace,
        failure=failure,
    )


def build_testing_agent_payload(
    *,
    qa_id: str,
    question: str,
    generation_run_id: str,
    output: GenerationOutput,
) -> GeneratedCypherSubmissionRequest | CgaGenerationNonSuccessReport:
    trace = _validated_graph_trace(
        output,
        qa_id=qa_id,
        question=question,
        generation_run_id=generation_run_id,
    )
    snapshot = json.dumps(trace.model_dump(mode="json", exclude_none=False), ensure_ascii=False, indent=2)
    if output.status == "generated":
        return GeneratedCypherSubmissionRequest(
            id=qa_id,
            question=question,
            generation_run_id=generation_run_id,
            generated_cypher=output.cypher or "",
            input_prompt_snapshot=snapshot,
        )

    failure_reason = None if output.failure is None else output.failure.reason
    clarification = None if output.clarification is None else output.clarification.model_dump(mode="json")
    return CgaGenerationNonSuccessReport(
        id=qa_id,
        question=question,
        generation_run_id=generation_run_id,
        generation_status=output.status,
        failure_reason=failure_reason,
        clarification=clarification,
        parsed_cypher=None,
        input_prompt_snapshot=snapshot,
        gate_passed=False,
    )


def _validated_graph_trace(
    output: GenerationOutput,
    *,
    qa_id: str,
    question: str,
    generation_run_id: str,
) -> GraphTraceRecord:
    trace = GraphTraceRecord.model_validate(output.trace)
    if trace.question_id != qa_id:
        raise ValueError(f"trace question_id {trace.question_id} does not match qa_id {qa_id}")
    if trace.generation_run_id != generation_run_id:
        raise ValueError(
            f"trace generation_run_id {trace.generation_run_id} does not match generation_run_id {generation_run_id}"
        )
    if trace.source_question != question:
        raise ValueError("trace source_question does not match submitted question")
    if trace.final_status != output.status:
        raise ValueError(f"trace final_status {trace.final_status} does not match output.status {output.status}")

    outputs = trace.final_outputs
    if outputs.user_visible_notices != output.user_visible_notices:
        raise ValueError("trace user_visible_notices does not match output.user_visible_notices")
    if output.status == "generated":
        if outputs.cypher != output.cypher:
            raise ValueError("generated trace cypher does not match output.cypher")
        if outputs.dsl != output.dsl:
            raise ValueError("generated trace DSL does not match output.dsl")
        return trace

    if output.status == "clarification_required" and output.clarification is not None:
        if outputs.clarification != output.clarification:
            raise ValueError("clarification trace payload does not match output.clarification")
        return trace

    if output.failure is not None and outputs.failure is not None:
        if outputs.failure != output.failure:
            raise ValueError("failure trace payload does not match output.failure")
    return trace


def get_generator_status() -> Dict[str, object]:
    return {
        "status": "ok",
        "pipeline": "ir12_deterministic_mvp",
        "internal_flow": {
            "semantic_parse": [
                "graph_model_loader",
                "question_decomposer",
                "candidate_retrieval",
                "literal_resolver",
                "grounded_understanding",
                "semantic_binder",
                "semantic_validator",
                "dsl_builder",
                "dsl_parser",
                "cypher_compiler",
                "cypher_self_validation",
            ]
        },
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
