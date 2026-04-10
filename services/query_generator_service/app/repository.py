from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from shared.models import QueryQuestionResponse, RepairPlan


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

    def next_generation_run_id(self) -> str:
        return str(uuid4())

    def get_question(self, id: str) -> Optional[Dict[str, Any]]:
        path = self._questions_dir / f"{id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save_generation_run(
        self,
        *,
        id: str,
        generation_run_id: str,
        generation_status: str,
        generated_cypher: str,
        parse_summary: str,
        guardrail_summary: str,
        raw_output_snapshot: str,
        failure_stage: str | None,
        failure_reason_summary: str | None,
        input_prompt_snapshot: str,
    ) -> None:
        record = {
            "id": id,
            "generation_run_id": generation_run_id,
            "generation_status": generation_status,
            "generated_cypher": generated_cypher,
            "parse_summary": parse_summary,
            "guardrail_summary": guardrail_summary,
            "raw_output_snapshot": raw_output_snapshot,
            "failure_stage": failure_stage,
            "failure_reason_summary": failure_reason_summary,
            "input_prompt_snapshot": input_prompt_snapshot,
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
        return QueryQuestionResponse(
            id=id,
            generation_run_id=run["generation_run_id"],
            generation_status=run["generation_status"],
            generated_cypher=run["generated_cypher"],
            parse_summary=run.get("parse_summary", ""),
            guardrail_summary=run.get("guardrail_summary", ""),
            raw_output_snapshot=run.get("raw_output_snapshot", ""),
            failure_stage=run.get("failure_stage"),
            failure_reason_summary=run.get("failure_reason_summary"),
            input_prompt_snapshot=run.get("input_prompt_snapshot", ""),
        )

    def get_generation_prompt_snapshot(self, id: str) -> Optional[Dict[str, str]]:
        run_path = self._runs_dir / f"{id}.json"
        if not run_path.exists():
            return None
        run = json.loads(run_path.read_text(encoding="utf-8"))
        return {
            "id": id,
            "input_prompt_snapshot": run.get("input_prompt_snapshot", ""),
        }

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
