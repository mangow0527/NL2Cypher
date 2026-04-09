from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from shared.models import KnowledgeContext, QueryQuestionResponse, RepairPlan, TuGraphExecutionResult


class QueryGeneratorRepository:
    def __init__(self, data_dir: str) -> None:
        self._questions_dir = Path(data_dir) / "questions"
        self._runs_dir = Path(data_dir) / "generation_runs"
        self._receipts_dir = Path(data_dir) / "repair_plan_receipts"
        self._questions_dir.mkdir(parents=True, exist_ok=True)
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        self._receipts_dir.mkdir(parents=True, exist_ok=True)

    def upsert_question(self, *, id: str, question: str, status: str) -> None:
        path = self._questions_dir / f"{id}.json"
        now = _utc_now()
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing["question"] != question:
                raise ValueError(f"Question conflict for id={id}")
            existing["status"] = status
            existing["updated_at"] = now
            path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
            return
        record = {"id": id, "question": question, "status": status, "received_at": now, "updated_at": now}
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_question(self, id: str) -> Optional[Dict[str, Any]]:
        path = self._questions_dir / f"{id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save_generation_run(
        self,
        *,
        id: str,
        question: str,
        generated_cypher: str,
        execution: TuGraphExecutionResult,
        knowledge_context: KnowledgeContext,
        evaluation_status: str,
    ) -> None:
        record = {
            "id": id,
            "question": question,
            "generated_cypher": generated_cypher,
            "execution": execution.model_dump(),
            "knowledge_context": knowledge_context.model_dump(),
            "evaluation_status": evaluation_status,
            "finished_at": _utc_now(),
        }
        path = self._runs_dir / f"{id}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_generation_run(self, id: str) -> Optional[QueryQuestionResponse]:
        run_path = self._runs_dir / f"{id}.json"
        question_path = self._questions_dir / f"{id}.json"
        if not run_path.exists() or not question_path.exists():
            return None
        run = json.loads(run_path.read_text(encoding="utf-8"))
        question = json.loads(question_path.read_text(encoding="utf-8"))
        return QueryQuestionResponse(
            id=id,
            status=question["status"],
            question=run["question"],
            generated_cypher=run["generated_cypher"],
            execution=TuGraphExecutionResult.model_validate(run["execution"]),
            knowledge_context=KnowledgeContext.model_validate(run["knowledge_context"]),
            evaluation_status=run["evaluation_status"],
        )

    def update_question_status(self, id: str, status: str) -> None:
        path = self._questions_dir / f"{id}.json"
        if not path.exists():
            return
        record = json.loads(path.read_text(encoding="utf-8"))
        record["status"] = status
        record["updated_at"] = _utc_now()
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    def save_repair_plan_receipt(self, plan: RepairPlan) -> None:
        record = {
            "plan_id": plan.plan_id,
            "id": plan.id,
            "plan": json.loads(plan.model_dump_json()),
            "received_at": _utc_now(),
        }
        path = self._receipts_dir / f"{plan.plan_id}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
