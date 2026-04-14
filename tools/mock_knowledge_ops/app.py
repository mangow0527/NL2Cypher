from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field


class _PromptPackageRequest(BaseModel):
    id: str
    question: str


KnowledgeType = Literal["cypher_syntax", "few_shot", "system_prompt", "business_knowledge"]


class _ApplyRepairRequest(BaseModel):
    id: str = Field(min_length=1)
    suggestion: str = Field(min_length=1)
    knowledge_types: list[KnowledgeType]


class _RepairChange(BaseModel):
    doc_type: KnowledgeType
    section: str
    before: str
    after: str


class _ApplyRepairResponse(BaseModel):
    status: Literal["ok"] = "ok"
    changes: list[_RepairChange] = Field(default_factory=list)


_ALLOWED_KNOWLEDGE_TYPES = {"cypher_syntax", "few_shot", "system_prompt", "business_knowledge"}

app = FastAPI(title="Mock Knowledge Ops", version="1.0.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "mock_knowledge_ops"}


@app.post("/api/knowledge/rag/prompt-package")
async def prompt_package(req: _PromptPackageRequest) -> str:
    del req
    return "请只返回 JSON，且必须包含 cypher 字段。"


@app.post("/api/knowledge/repairs/apply", response_model=_ApplyRepairResponse)
async def repairs_apply(payload: _ApplyRepairRequest) -> _ApplyRepairResponse:
    knowledge_types = payload.knowledge_types or []
    out_dir = Path("data/mock_knowledge_ops")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "last_apply.json").write_text(
        json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    changes = [
        _RepairChange(doc_type=knowledge_type, section="mock", before="", after=payload.suggestion)
        for knowledge_type in knowledge_types
    ]
    return _ApplyRepairResponse(changes=changes)
