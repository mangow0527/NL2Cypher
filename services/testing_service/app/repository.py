from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional

from shared.models import EvaluationSubmissionRequest, IssueTicket, QAGoldenRequest


class TestingRepository:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS qa_goldens (
                    id TEXT PRIMARY KEY,
                    golden_cypher TEXT NOT NULL,
                    golden_answer_json TEXT NOT NULL,
                    difficulty TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS evaluation_submissions (
                    id TEXT PRIMARY KEY,
                    question TEXT NOT NULL,
                    generated_cypher TEXT NOT NULL,
                    execution_json TEXT NOT NULL,
                    knowledge_context_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS issue_tickets (
                    ticket_id TEXT PRIMARY KEY,
                    id TEXT NOT NULL,
                    ticket_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def save_golden(self, request: QAGoldenRequest) -> None:
        now = _utc_now()
        with self._lock, self._connect() as conn:
            existing = conn.execute("SELECT golden_cypher, golden_answer_json, difficulty FROM qa_goldens WHERE id = ?", (request.id,)).fetchone()
            payload = json.dumps(request.answer, ensure_ascii=False)
            if existing:
                if (
                    existing["golden_cypher"] != request.cypher
                    or existing["golden_answer_json"] != payload
                    or existing["difficulty"] != request.difficulty
                ):
                    raise ValueError(f"Golden answer conflict for id={request.id}")
                conn.execute(
                    "UPDATE qa_goldens SET updated_at = ? WHERE id = ?",
                    (now, request.id),
                )
                return

            conn.execute(
                "INSERT INTO qa_goldens (id, golden_cypher, golden_answer_json, difficulty, received_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (request.id, request.cypher, payload, request.difficulty, now, now),
            )

    def save_submission(self, request: EvaluationSubmissionRequest, status: str) -> None:
        now = _utc_now()
        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT question, generated_cypher, execution_json, knowledge_context_json FROM evaluation_submissions WHERE id = ?",
                (request.id,),
            ).fetchone()
            execution_json = request.execution.model_dump_json()
            knowledge_json = request.knowledge_context.model_dump_json()
            if existing:
                if (
                    existing["question"] != request.question
                    or existing["generated_cypher"] != request.generated_cypher
                    or existing["execution_json"] != execution_json
                    or existing["knowledge_context_json"] != knowledge_json
                ):
                    raise ValueError(f"Submission conflict for id={request.id}")
                conn.execute(
                    "UPDATE evaluation_submissions SET status = ?, updated_at = ? WHERE id = ?",
                    (status, now, request.id),
                )
                return

            conn.execute(
                """
                INSERT INTO evaluation_submissions (
                    id, question, generated_cypher, execution_json, knowledge_context_json, status, received_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (request.id, request.question, request.generated_cypher, execution_json, knowledge_json, status, now, now),
            )

    def get_golden(self, id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM qa_goldens WHERE id = ?", (id,)).fetchone()
        return dict(row) if row else None

    def get_submission(self, id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM evaluation_submissions WHERE id = ?", (id,)).fetchone()
        return dict(row) if row else None

    def save_issue_ticket(self, ticket: IssueTicket) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO issue_tickets (ticket_id, id, ticket_json, created_at) VALUES (?, ?, ?, ?)",
                (ticket.ticket_id, ticket.id, ticket.model_dump_json(), _utc_now()),
            )
            conn.execute(
                "UPDATE evaluation_submissions SET status = ?, updated_at = ? WHERE id = ?",
                ("issue_ticket_created", _utc_now(), ticket.id),
            )

    def mark_submission_status(self, id: str, status: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE evaluation_submissions SET status = ?, updated_at = ? WHERE id = ?",
                (status, _utc_now(), id),
            )

    def get_issue_ticket(self, ticket_id: str) -> Optional[IssueTicket]:
        with self._connect() as conn:
            row = conn.execute("SELECT ticket_json FROM issue_tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
        if not row:
            return None
        return IssueTicket.model_validate_json(row["ticket_json"])


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
