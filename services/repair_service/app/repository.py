from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Optional

from shared.models import RepairPlan


class RepairRepository:
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
                CREATE TABLE IF NOT EXISTS repair_plans (
                    plan_id TEXT PRIMARY KEY,
                    ticket_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    root_cause TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dispatch_outbox (
                    plan_id TEXT NOT NULL,
                    target_service TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    dispatch_status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def save_plan(self, plan: RepairPlan) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO repair_plans (plan_id, ticket_id, id, root_cause, plan_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (plan.plan_id, plan.ticket_id, plan.id, plan.root_cause, plan.model_dump_json(), _utc_now()),
            )

    def save_outbox(self, plan_id: str, target_service: str, payload_json: str, dispatch_status: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO dispatch_outbox (plan_id, target_service, payload_json, dispatch_status, created_at) VALUES (?, ?, ?, ?, ?)",
                (plan_id, target_service, payload_json, dispatch_status, _utc_now()),
            )

    def get_plan(self, plan_id: str) -> Optional[RepairPlan]:
        with self._connect() as conn:
            row = conn.execute("SELECT plan_json FROM repair_plans WHERE plan_id = ?", (plan_id,)).fetchone()
        if not row:
            return None
        return RepairPlan.model_validate_json(row["plan_json"])


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
