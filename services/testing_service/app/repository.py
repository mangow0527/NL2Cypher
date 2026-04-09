from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from shared.models import EvaluationSubmissionRequest, IssueTicket, QAGoldenRequest


class TestingRepository:
    def __init__(self, data_dir: str) -> None:
        self._goldens_dir = Path(data_dir) / "goldens"
        self._submissions_dir = Path(data_dir) / "submissions"
        self._tickets_dir = Path(data_dir) / "issue_tickets"
        self._goldens_dir.mkdir(parents=True, exist_ok=True)
        self._submissions_dir.mkdir(parents=True, exist_ok=True)
        self._tickets_dir.mkdir(parents=True, exist_ok=True)

    def save_golden(self, request: QAGoldenRequest) -> None:
        path = self._goldens_dir / f"{request.id}.json"
        now = _utc_now()
        answer_json = json.dumps(request.answer, ensure_ascii=False)
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if (
                existing["golden_cypher"] != request.cypher
                or existing["golden_answer_json"] != answer_json
                or existing["difficulty"] != request.difficulty
            ):
                raise ValueError(f"Golden answer conflict for id={request.id}")
            existing["updated_at"] = now
            path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
            return
        record = {
            "id": request.id,
            "golden_cypher": request.cypher,
            "golden_answer_json": answer_json,
            "difficulty": request.difficulty,
            "received_at": now,
            "updated_at": now,
        }
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    def save_submission(self, request: EvaluationSubmissionRequest, status: str) -> None:
        path = self._submissions_dir / f"{request.id}.json"
        now = _utc_now()
        execution_json = request.execution.model_dump_json()
        knowledge_json = request.knowledge_context.model_dump_json()
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if (
                existing["question"] != request.question
                or existing["generated_cypher"] != request.generated_cypher
                or existing["execution_json"] != execution_json
                or existing["knowledge_context_json"] != knowledge_json
            ):
                raise ValueError(f"Submission conflict for id={request.id}")
            existing["status"] = status
            existing["updated_at"] = now
            path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
            return
        record = {
            "id": request.id,
            "question": request.question,
            "generated_cypher": request.generated_cypher,
            "execution_json": execution_json,
            "knowledge_context_json": knowledge_json,
            "status": status,
            "received_at": now,
            "updated_at": now,
        }
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_golden(self, id: str) -> Optional[Dict[str, Any]]:
        path = self._goldens_dir / f"{id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def get_submission(self, id: str) -> Optional[Dict[str, Any]]:
        path = self._submissions_dir / f"{id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save_issue_ticket(self, ticket: IssueTicket) -> None:
        record = {
            "ticket_id": ticket.ticket_id,
            "id": ticket.id,
            "ticket_json": ticket.model_dump_json(),
            "created_at": _utc_now(),
        }
        path = self._tickets_dir / f"{ticket.ticket_id}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        self.mark_submission_status(ticket.id, "issue_ticket_created")

    def mark_submission_status(self, id: str, status: str) -> None:
        path = self._submissions_dir / f"{id}.json"
        if not path.exists():
            return
        record = json.loads(path.read_text(encoding="utf-8"))
        record["status"] = status
        record["updated_at"] = _utc_now()
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_issue_ticket(self, ticket_id: str) -> Optional[IssueTicket]:
        path = self._tickets_dir / f"{ticket_id}.json"
        if not path.exists():
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
        return IssueTicket.model_validate_json(record["ticket_json"])


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
