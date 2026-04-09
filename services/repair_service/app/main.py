from pathlib import Path
from typing import Dict

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from .config import settings
from .schemas import IssueTicket, RepairPlan, RepairPlanEnvelope
from .service import repair_service

app = FastAPI(title="Repair Service", version="1.0.0")
ui_dir = Path(__file__).parent / "ui"
app.mount("/ui", StaticFiles(directory=ui_dir), name="repair-ui")


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/console")


@app.get("/console", include_in_schema=False)
async def console() -> FileResponse:
    return FileResponse(ui_dir / "index.html")


@app.get("/health")
async def healthcheck() -> Dict[str, str]:
    return {"status": "ok", "service": "repair_service"}


@app.get("/api/v1/status")
async def service_status() -> Dict[str, object]:
    return repair_service.get_service_status()


@app.post("/api/v1/issue-tickets", response_model=RepairPlanEnvelope)
async def create_repair_plan(issue_ticket: IssueTicket) -> RepairPlanEnvelope:
    return await repair_service.create_plan(issue_ticket)


@app.get("/api/v1/repair-plans/{plan_id}", response_model=RepairPlan)
async def get_repair_plan(plan_id: str) -> RepairPlan:
    plan = repair_service.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"No repair plan found for plan_id={plan_id}")
    return plan


if __name__ == "__main__":
    uvicorn.run("services.repair_service.app.main:app", host=settings.host, port=settings.port, reload=False)
