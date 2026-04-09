from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from shared.models import RepairPlan


class RepairRepository:
    def __init__(self, data_dir: str) -> None:
        self._plans_dir = Path(data_dir) / "plans"
        self._outbox_dir = Path(data_dir) / "dispatch_outbox"
        self._plans_dir.mkdir(parents=True, exist_ok=True)
        self._outbox_dir.mkdir(parents=True, exist_ok=True)

    def save_plan(self, plan: RepairPlan) -> None:
        record = {
            "plan_id": plan.plan_id,
            "ticket_id": plan.ticket_id,
            "id": plan.id,
            "root_cause": plan.root_cause,
            "plan_json": plan.model_dump_json(),
            "created_at": _utc_now(),
        }
        path = self._plans_dir / f"{plan.plan_id}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    def save_outbox(self, plan_id: str, target_service: str, payload_json: str, dispatch_status: str) -> None:
        record = {
            "plan_id": plan_id,
            "target_service": target_service,
            "payload_json": payload_json,
            "dispatch_status": dispatch_status,
            "created_at": _utc_now(),
        }
        path = self._outbox_dir / f"{plan_id}_{target_service}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_plan(self, plan_id: str) -> Optional[RepairPlan]:
        path = self._plans_dir / f"{plan_id}.json"
        if not path.exists():
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
        return RepairPlan.model_validate_json(record["plan_json"])


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
