from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from pydantic import BaseModel


class _PromptPackageRequest(BaseModel):
    id: str
    question: str


app = FastAPI(title="Mock Knowledge Ops", version="1.0.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "mock_knowledge_ops"}


@app.post("/api/knowledge/rag/prompt-package")
async def prompt_package(req: _PromptPackageRequest) -> str:
    del req
    return "请只返回 JSON，且必须包含 cypher 字段。"


@app.post("/api/knowledge/repairs/apply")
async def repairs_apply(request: Request) -> dict:
    payload = await request.json()
    out_dir = Path("data/mock_knowledge_ops")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "last_apply.json").write_text(str(payload), encoding="utf-8")
    return {"ok": True}
