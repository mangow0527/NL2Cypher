from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import httpx

from shared.models import IssueTicket, RepairPlan


class OpenAICompatibleRepairPlanner:
    def __init__(self, base_url: str, api_key: str, model: str, timeout_seconds: float, temperature: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature

    async def refine(self, issue_ticket: IssueTicket, candidate_plan: RepairPlan) -> Optional[Dict[str, Any]]:
        system_prompt = (
            "You are a repair planner for a Text2Cypher system. "
            "Refine the candidate repair plan but keep it grounded in the given issue ticket and counterfactual evidence. "
            "Return JSON only with keys root_cause, confidence, analysis_summary, actions."
        )
        user_prompt = (
            f"IssueTicket: {issue_ticket.model_dump_json()}\n"
            f"CandidatePlan: {candidate_plan.model_dump_json()}\n"
            "Actions must keep target_service within query_generator_service, knowledge_ops_service, qa_generation_service."
        )
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "temperature": self.temperature,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
            )
            response.raise_for_status()
            payload = response.json()

        content = payload["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.strip("`")
            if content.startswith("json"):
                content = content[4:].strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None


class DispatchClient:
    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds

    async def post_json(self, url: str, payload: dict) -> None:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
