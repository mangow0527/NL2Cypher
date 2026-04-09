from __future__ import annotations

import httpx

from shared.models import IssueTicket, RepairPlanEnvelope


class RepairServiceClient:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def submit_issue_ticket(self, ticket: IssueTicket) -> RepairPlanEnvelope:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/issue-tickets",
                json=ticket.model_dump(),
            )
            response.raise_for_status()
            return RepairPlanEnvelope.model_validate(response.json())
