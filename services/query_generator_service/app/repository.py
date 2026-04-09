from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional

from shared.models import KnowledgeContext, QueryQuestionResponse, RepairPlan, TuGraphExecutionResult


class QueryGeneratorRepository:
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
                CREATE TABLE IF NOT EXISTS qa_questions (
                    id TEXT PRIMARY KEY,
                    question TEXT NOT NULL,
                    status TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS generation_runs (
                    id TEXT PRIMARY KEY,
                    question TEXT NOT NULL,
                    generated_cypher TEXT NOT NULL,
                    execution_json TEXT NOT NULL,
                    knowledge_context_json TEXT NOT NULL,
                    evaluation_status TEXT NOT NULL,
                    finished_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS repair_plan_receipts (
                    plan_id TEXT PRIMARY KEY,
                    id TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    received_at TEXT NOT NULL
                )
                """
            )

    def upsert_question(self, *, id: str, question: str, status: str) -> None:
        now = _utc_now()
        with self._lock, self._connect() as conn:
            existing = conn.execute("SELECT question FROM qa_questions WHERE id = ?", (id,)).fetchone()
            if existing:
                if existing["question"] != question:
                    raise ValueError(f"Question conflict for id={id}")
                conn.execute(
                    "UPDATE qa_questions SET status = ?, updated_at = ? WHERE id = ?",
                    (status, now, id),
                )
                return

            conn.execute(
                "INSERT INTO qa_questions (id, question, status, received_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (id, question, status, now, now),
            )

    def get_question(self, id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM qa_questions WHERE id = ?", (id,)).fetchone()
        return dict(row) if row else None

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
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO generation_runs (
                    id, question, generated_cypher, execution_json, knowledge_context_json, evaluation_status, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    id,
                    question,
                    generated_cypher,
                    json.dumps(execution.model_dump(), ensure_ascii=False),
                    json.dumps(knowledge_context.model_dump(), ensure_ascii=False),
                    evaluation_status,
                    _utc_now(),
                ),
            )

    def get_generation_run(self, id: str) -> Optional[QueryQuestionResponse]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM generation_runs WHERE id = ?", (id,)).fetchone()
            question_row = conn.execute("SELECT * FROM qa_questions WHERE id = ?", (id,)).fetchone()
        if not row or not question_row:
            return None
        return QueryQuestionResponse(
            id=id,
            status=question_row["status"],
            question=row["question"],
            generated_cypher=row["generated_cypher"],
            execution=TuGraphExecutionResult.model_validate(json.loads(row["execution_json"])),
            knowledge_context=KnowledgeContext.model_validate(json.loads(row["knowledge_context_json"])),
            evaluation_status=row["evaluation_status"],
        )

    def update_question_status(self, id: str, status: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE qa_questions SET status = ?, updated_at = ? WHERE id = ?",
                (status, _utc_now(), id),
            )

    def save_repair_plan_receipt(self, plan: RepairPlan) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO repair_plan_receipts (plan_id, id, plan_json, received_at) VALUES (?, ?, ?, ?)",
                (plan.plan_id, plan.id, plan.model_dump_json(), _utc_now()),
            )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
