from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Awaitable, Callable
from typing import Any, Dict, List, Optional

import httpx

from shared.models import IssueTicket, KnowledgeRepairSuggestionRequest, PromptSnapshotResponse, RepairPlan


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


class OpenAICompatibleKRSSAnalyzer:
    def __init__(self, base_url: str, api_key: str, model: str, timeout_seconds: float, temperature: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature

    async def diagnose(self, ticket: IssueTicket, prompt_snapshot: str) -> Dict[str, Any]:
        system_prompt = (
            "You are the Knowledge Repair Suggestion Service for a Text2Cypher system. "
            "Diagnose which knowledge patches are most likely to fix the issue. "
            "Return JSON only with keys knowledge_types, confidence, suggestion, rationale, need_experiments, candidate_patch_types."
        )
        user_prompt = (
            f"IssueTicket: {ticket.model_dump_json()}\n"
            f"PromptSnapshot: {prompt_snapshot}\n"
            "knowledge_types and candidate_patch_types must use only: "
            "schema, cypher_syntax, few-shot, system_prompt, business_knowledge."
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
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            payload = response.json()

        content = payload["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.strip("`")
            if content.startswith("json"):
                content = content[4:].strip()

        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("KRSS diagnosis response must be a JSON object")
        return parsed


class DispatchClient:
    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds

    async def post_json(self, url: str, payload: dict) -> None:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()


class CGSPromptSnapshotClient:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def fetch(self, id: str) -> PromptSnapshotResponse:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(f"{self.base_url}/api/v1/questions/{id}/prompt")
            response.raise_for_status()
            return PromptSnapshotResponse.model_validate(response.json())


class KnowledgeOpsRepairApplyClient:
    def __init__(
        self,
        apply_url: str,
        timeout_seconds: float,
        capture_dir: Optional[str] = None,
        sleep_fn: Callable[[float], Awaitable[None]] = asyncio.sleep,
        retry_delay_seconds: float = 0.1,
    ) -> None:
        self.apply_url = apply_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.capture_dir = capture_dir
        self.sleep_fn = sleep_fn
        self.retry_delay_seconds = retry_delay_seconds

    async def apply(self, payload: KnowledgeRepairSuggestionRequest) -> None:
        self._capture_payload(payload)
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            while True:
                try:
                    response = await client.post(self.apply_url, json=payload.model_dump())
                except httpx.RequestError:
                    # Transport failures are retried the same way as non-200 responses.
                    await self.sleep_fn(self.retry_delay_seconds)
                    continue
                if response.status_code == 200:
                    return None
                await self.sleep_fn(self.retry_delay_seconds)

    def _capture_payload(self, payload: KnowledgeRepairSuggestionRequest) -> None:
        if not self.capture_dir:
            return
        try:
            capture_path = Path(self.capture_dir)
            capture_path.mkdir(parents=True, exist_ok=True)
            file_path = capture_path / f"{payload.id}.json"
            file_path.write_text(
                json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            return
