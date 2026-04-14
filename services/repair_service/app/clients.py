from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

import httpx

from shared.models import IssueTicket, KnowledgeRepairSuggestionRequest, PromptSnapshotResponse

logger = logging.getLogger("repair_service")


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
            "knowledge_types and candidate_patch_types must use only these formal knowledge types: "
            "cypher_syntax, few_shot, system_prompt, business_knowledge."
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

class CGSPromptSnapshotClient:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def fetch(self, id: str) -> PromptSnapshotResponse:
        started = time.monotonic()
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            try:
                response = await client.get(f"{self.base_url}/api/v1/questions/{id}/prompt")
            except Exception as exc:
                elapsed_ms = int((time.monotonic() - started) * 1000)
                logger.warning(
                    "outbound_call_failed",
                    extra={
                        "target": "cgs.prompt_snapshot",
                        "qa_id": id,
                        "elapsed_ms": elapsed_ms,
                        "error": str(exc),
                    },
                )
                raise
            response.raise_for_status()
            elapsed_ms = int((time.monotonic() - started) * 1000)
            logger.info(
                "outbound_call_ok",
                extra={
                    "target": "cgs.prompt_snapshot",
                    "qa_id": id,
                    "status_code": response.status_code,
                    "elapsed_ms": elapsed_ms,
                },
            )
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

    async def apply(self, payload: KnowledgeRepairSuggestionRequest) -> Dict[str, Any] | None:
        self._capture_payload(payload)
        started = time.monotonic()
        attempts = 0
        request_payload = payload.model_dump(mode="json")
        knowledge_types = request_payload.get("knowledge_types", []) or []
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            while True:
                attempts += 1
                try:
                    response = await client.post(self.apply_url, json=request_payload)
                except httpx.RequestError:
                    elapsed_ms = int((time.monotonic() - started) * 1000)
                    logger.warning(
                        "outbound_call_failed",
                        extra={
                            "target": "knowledge_ops.repairs_apply",
                            "analysis_id": payload.id,
                            "knowledge_types": knowledge_types,
                            "attempt": attempts,
                            "elapsed_ms": elapsed_ms,
                            "error": "transport_error",
                        },
                    )
                    # Transport failures are retried the same way as non-200 responses.
                    await self.sleep_fn(self.retry_delay_seconds)
                    continue
                if response.status_code == 200:
                    elapsed_ms = int((time.monotonic() - started) * 1000)
                    logger.info(
                        "outbound_call_ok",
                        extra={
                            "target": "knowledge_ops.repairs_apply",
                            "analysis_id": payload.id,
                            "knowledge_types": knowledge_types,
                            "attempts": attempts,
                            "status_code": response.status_code,
                            "elapsed_ms": elapsed_ms,
                        },
                    )
                    try:
                        return response.json()
                    except Exception:
                        return {"raw": response.text}
                if 400 <= response.status_code < 500:
                    elapsed_ms = int((time.monotonic() - started) * 1000)
                    logger.warning(
                        "outbound_call_failed",
                        extra={
                            "target": "knowledge_ops.repairs_apply",
                            "analysis_id": payload.id,
                            "knowledge_types": knowledge_types,
                            "attempts": attempts,
                            "status_code": response.status_code,
                            "elapsed_ms": elapsed_ms,
                            "error": "non_retryable_4xx",
                        },
                    )
                    response.raise_for_status()
                logger.warning(
                    "outbound_call_retry",
                    extra={
                        "target": "knowledge_ops.repairs_apply",
                        "analysis_id": payload.id,
                        "knowledge_types": knowledge_types,
                        "attempt": attempts,
                        "status_code": response.status_code,
                    },
                )
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
