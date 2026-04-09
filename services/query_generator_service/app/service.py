from __future__ import annotations

from shared.knowledge import build_knowledge_context, build_schema_hint_from_tags, select_knowledge_tags
from shared.models import (
    CypherGenerationRequest,
    EvaluationSubmissionRequest,
    GenerationContext,
    QAQuestionRequest,
    QueryGeneratorRepairReceipt,
    QueryQuestionResponse,
    RepairPlan,
)
from shared.tugraph import TuGraphClient

from .clients import (
    HeuristicCypherGenerator,
    OpenAICompatibleCypherGenerator,
    QwenGeneratorClient,
    TestingServiceClient,
)
from .config import settings
from .repository import QueryGeneratorRepository


class QueryWorkflowService:
    def __init__(
        self,
        generator_client: QwenGeneratorClient,
        testing_client: TestingServiceClient,
        tugraph_client: TuGraphClient,
        repository: QueryGeneratorRepository,
    ) -> None:
        self.generator_client = generator_client
        self.testing_client = testing_client
        self.tugraph_client = tugraph_client
        self.repository = repository

    async def ingest_question(self, request: QAQuestionRequest) -> QueryQuestionResponse:
        self.repository.upsert_question(id=request.id, question=request.question, status="received_question")
        self.repository.update_question_status(request.id, "generating_cypher")

        knowledge_tags = select_knowledge_tags(request.question)
        knowledge_context = build_knowledge_context(knowledge_tags)
        generation = await self.generator_client.generate(
            CypherGenerationRequest(
                context=GenerationContext(
                    id=request.id,
                    question=request.question,
                    schema_hint=build_schema_hint_from_tags(knowledge_tags),
                    attempt=1,
                    knowledge_context=knowledge_context,
                )
            )
        )

        self.repository.update_question_status(request.id, "querying_tugraph")
        execution = await self.tugraph_client.execute(generation.cypher)

        self.repository.update_question_status(request.id, "submitted_for_evaluation")
        submission_response = await self.testing_client.submit(
            payload=EvaluationSubmissionRequest(
                id=request.id,
                question=request.question,
                generated_cypher=generation.cypher,
                execution=execution,
                knowledge_context=knowledge_context,
            )
        )

        final_status = "completed"
        self.repository.update_question_status(request.id, final_status)
        self.repository.save_generation_run(
            id=request.id,
            question=request.question,
            generated_cypher=generation.cypher,
            execution=execution,
            knowledge_context=knowledge_context,
            evaluation_status=submission_response.status,
        )
        run = self.repository.get_generation_run(request.id)
        if run is None:
            raise RuntimeError(f"Failed to persist generation run for id={request.id}")
        return run

    def get_run(self, id: str) -> QueryQuestionResponse | None:
        return self.repository.get_generation_run(id)

    def accept_repair_plan(self, plan: RepairPlan) -> QueryGeneratorRepairReceipt:
        self.repository.save_repair_plan_receipt(plan)
        return QueryGeneratorRepairReceipt(status="accepted", plan_id=plan.plan_id, id=plan.id)


repository = QueryGeneratorRepository(data_dir=settings.data_dir)
llm_generator = None
if (
    settings.llm_enabled
    and settings.llm_provider == "openai_compatible"
    and settings.llm_base_url
    and settings.llm_api_key
    and settings.llm_model
):
    llm_generator = OpenAICompatibleCypherGenerator(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout_seconds=settings.request_timeout_seconds,
        temperature=settings.llm_temperature,
    )

workflow_service = QueryWorkflowService(
    generator_client=QwenGeneratorClient(
        heuristic_generator=HeuristicCypherGenerator(model_name=settings.qwen_model_name),
        llm_generator=llm_generator,
    ),
    testing_client=TestingServiceClient(
        base_url=settings.testing_service_url,
        timeout_seconds=settings.request_timeout_seconds,
    ),
    tugraph_client=TuGraphClient(
        base_url=settings.tugraph_url,
        username=settings.tugraph_username,
        password=settings.tugraph_password,
        graph=settings.tugraph_graph,
        mock_mode=settings.mock_tugraph,
    ),
    repository=repository,
)


async def test_tugraph_connection() -> dict:
    execution = await workflow_service.tugraph_client.test_connection()
    return {
        "mode": "mock" if workflow_service.tugraph_client.mock_mode else "real",
        "graph": workflow_service.tugraph_client.graph,
        "base_url": workflow_service.tugraph_client.base_url,
        "success": execution.success,
        "execution": execution.model_dump(),
    }


def get_generator_status() -> dict:
    return {
        "llm_enabled": settings.llm_enabled,
        "llm_provider": settings.llm_provider,
        "llm_base_url": settings.llm_base_url,
        "llm_model": settings.llm_model,
        "llm_configured": bool(
            settings.llm_enabled
            and settings.llm_base_url
            and settings.llm_api_key
            and settings.llm_model
        ),
        "active_mode": "llm" if llm_generator is not None else "heuristic_fallback",
        "tugraph_graph": settings.tugraph_graph,
        "storage": settings.data_dir,
        "knowledge_package": "default-network-schema:v1",
    }
