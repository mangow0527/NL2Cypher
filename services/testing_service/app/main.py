from pathlib import Path
from typing import Dict

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from .config import settings
from .schemas import EvaluationSubmissionRequest, EvaluationSubmissionResponse, IssueTicket, QAGoldenRequest, QAGoldenResponse
from .service import validation_service

app = FastAPI(title="Testing Service", version="1.0.0")
ui_dir = Path(__file__).parent / "ui"
app.mount("/ui", StaticFiles(directory=ui_dir), name="testing-ui")


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/console")


@app.get("/console", include_in_schema=False)
async def console() -> FileResponse:
    return FileResponse(ui_dir / "index.html")


@app.get("/health")
async def healthcheck() -> Dict[str, str]:
    return {"status": "ok", "service": "testing_service"}


@app.get("/api/v1/status")
async def service_status() -> Dict[str, object]:
    return validation_service.get_service_status()


@app.post("/api/v1/qa/goldens", response_model=QAGoldenResponse)
async def ingest_golden(request: QAGoldenRequest) -> QAGoldenResponse:
    try:
        return await validation_service.ingest_golden(request)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/evaluations/submissions", response_model=EvaluationSubmissionResponse)
async def submit_evaluation(request: EvaluationSubmissionRequest) -> EvaluationSubmissionResponse:
    try:
        return await validation_service.ingest_submission(request)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/v1/evaluations/{id}")
async def get_evaluation(id: str) -> Dict[str, object]:
    return validation_service.get_evaluation_status(id)


@app.get("/api/v1/issues/{ticket_id}", response_model=IssueTicket)
async def get_issue_ticket(ticket_id: str) -> IssueTicket:
    ticket = validation_service.get_issue_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"No issue ticket found for ticket_id={ticket_id}")
    return ticket


if __name__ == "__main__":
    uvicorn.run("services.testing_service.app.main:app", host=settings.host, port=settings.port, reload=False)
