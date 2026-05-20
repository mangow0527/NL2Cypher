import asyncio
from contextlib import asynccontextmanager
from typing import Dict

from fastapi import FastAPI
from fastapi.responses import Response
import uvicorn

from .models import IntentRecognitionRequest, QAQuestionRequest, SemanticParseRequest
from .service import get_generator_status, get_workflow_service
from services.cypher_generator_agent.app.infrastructure.config import get_settings
from services.cypher_generator_agent.app.ontology_layer.intent_classification import get_hybrid_intent_recognizer
from services.cypher_generator_agent.app.runtime_pipeline import OntologyGenerationPipeline


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(get_workflow_service().retry_pending_deliveries())
    yield


app = FastAPI(title="cypher-generator-agent", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def healthcheck() -> Dict[str, str]:
    return {"status": "ok", "service": "cypher-generator-agent"}


@app.get("/api/v1/generator/status")
async def generator_status() -> Dict[str, object]:
    return get_generator_status()


@app.post("/api/v1/qa/questions", status_code=204)
async def ingest_question(request: QAQuestionRequest) -> Response:
    await get_workflow_service().ingest_question(request)
    return Response(status_code=204)


@app.post("/api/v1/intents/recognize")
async def recognize_intent(request: IntentRecognitionRequest) -> Dict[str, object]:
    result = get_hybrid_intent_recognizer().recognize(request.question)
    return result.to_dict()


@app.post("/api/v1/semantic/parse")
async def parse_semantics(request: SemanticParseRequest) -> Dict[str, object]:
    result = OntologyGenerationPipeline.from_default_resources().generate(
        request.question,
        trace_id=request.generation_run_id or request.id or "api",
    )
    return {
        "status": result.status,
        "cypher": result.cypher,
        "logical_plan": result.logical_plan.to_dict(),
        "trace": result.trace.to_dict(),
    }


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run("services.cypher_generator_agent.app.api.main:app", host=settings.host, port=settings.port, reload=False)
