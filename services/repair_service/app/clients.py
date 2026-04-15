from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

import httpx

from shared.llm_retry import classify_retryable_error, extract_request_id, sleep_with_backoff
from shared.models import IssueTicket, KnowledgeRepairSuggestionRequest, PromptSnapshotResponse

logger = logging.getLogger("repair_service")


def _dedupe_lines(text: str) -> str:
    seen: set[str] = set()
    compacted: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        normalized = line.strip()
        if normalized and normalized in seen:
            continue
        if normalized:
            seen.add(normalized)
        if line or (compacted and compacted[-1] != ""):
            compacted.append(line)
    while compacted and compacted[-1] == "":
        compacted.pop()
    return "\n".join(compacted)


def _compact_prompt_snapshot(prompt_snapshot: str, max_chars: int = 2200) -> str:
    compacted = _dedupe_lines(prompt_snapshot.strip())
    if len(compacted) <= max_chars:
        return compacted
    head_budget = max_chars // 2
    tail_budget = max_chars - head_budget - len("\n...[prompt truncated]...\n")
    return compacted[:head_budget].rstrip() + "\n...[prompt truncated]...\n" + compacted[-tail_budget:].lstrip()


def _trim_text(value: str | None, max_chars: int) -> str | None:
    if not value:
        return value
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3].rstrip() + "..."


def _compact_json_value(value: Any, max_chars: int = 600) -> Any:
    serialized = json.dumps(value, ensure_ascii=False, default=str)
    if len(serialized) <= max_chars:
        return value
    if isinstance(value, list):
        compacted = value[:1]
    elif isinstance(value, dict):
        compacted = {key: value[key] for key in list(value)[:6]}
    else:
        compacted = str(value)
    serialized = json.dumps(compacted, ensure_ascii=False, default=str)
    if len(serialized) <= max_chars:
        return compacted
    return _trim_text(serialized, max_chars)


def _build_krss_ticket_payload(ticket: IssueTicket) -> dict[str, Any]:
    execution = ticket.actual.execution
    return {
        "ticket_id": ticket.ticket_id,
        "id": ticket.id,
        "difficulty": ticket.difficulty,
        "question": ticket.question,
        "expected": {
            "cypher": ticket.expected.cypher,
            "answer_preview": _compact_json_value(ticket.expected.answer, max_chars=320),
        },
        "actual": {
            "generated_cypher": ticket.actual.generated_cypher,
            "execution": {
                "success": execution.success,
                "row_count": execution.row_count,
                "error_message": _trim_text(execution.error_message, 240),
                "elapsed_ms": execution.elapsed_ms,
                "rows_preview": execution.rows[:1],
            },
        },
        "evaluation": {
            "verdict": ticket.evaluation.verdict,
            "dimensions": ticket.evaluation.dimensions.model_dump(mode="json"),
            "symptom": _trim_text(ticket.evaluation.symptom, 240),
            "evidence_preview": ticket.evaluation.evidence[:2],
        },
    }


class OpenAICompatibleKRSSAnalyzer:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float,
        temperature: float,
        *,
        sleep_fn: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_retries: int = 2,
        retry_base_delay_seconds: float = 1.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.sleep_fn = sleep_fn
        self.max_retries = max_retries
        self.retry_base_delay_seconds = retry_base_delay_seconds

    async def diagnose(self, ticket: IssueTicket, prompt_snapshot: str) -> Dict[str, Any]:
        compact_prompt_snapshot = _compact_prompt_snapshot(prompt_snapshot)
        compact_ticket = _build_krss_ticket_payload(ticket)
        system_prompt = (
            "You are the Knowledge Repair Suggestion Service for a Text2Cypher system. "
            "Diagnose which knowledge patches are most likely to fix the issue. "
            "Return JSON only with keys knowledge_types, confidence, suggestion, rationale, need_experiments, candidate_patch_types."
        )
        user_prompt = (
            f"IssueTicket: {json.dumps(compact_ticket, ensure_ascii=False)}\n"
            f"PromptSnapshot: {compact_prompt_snapshot}\n"
            "knowledge_types and candidate_patch_types must use only these formal knowledge types: "
            "cypher_syntax, few_shot, system_prompt, business_knowledge."
        )
        started = time.monotonic()
        compact_ticket_chars = len(json.dumps(compact_ticket, ensure_ascii=False, default=str))
        logger.warning(
            "llm_call_started target=%s qa_id=%s ticket_id=%s model=%s base_url=%s prompt_chars=%s compact_prompt_chars=%s compact_ticket_chars=%s",
            "repair.krss_diagnosis",
            ticket.id,
            ticket.ticket_id,
            self.model,
            self.base_url,
            len(prompt_snapshot),
            len(compact_prompt_snapshot),
            compact_ticket_chars,
            extra={
                "target": "repair.krss_diagnosis",
                "qa_id": ticket.id,
                "ticket_id": ticket.ticket_id,
                "model": self.model,
                "base_url": self.base_url,
                "prompt_chars": len(prompt_snapshot),
                "compact_prompt_chars": len(compact_prompt_snapshot),
                "compact_ticket_chars": compact_ticket_chars,
            },
        )
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            for attempt in range(self.max_retries + 1):
                try:
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
                    break
                except Exception as exc:
                    elapsed_ms = int((time.monotonic() - started) * 1000)
                    retry = classify_retryable_error(exc)
                    is_last_attempt = attempt >= self.max_retries
                    if retry.should_retry and not is_last_attempt:
                        delay_seconds = await sleep_with_backoff(
                            sleep_fn=self.sleep_fn,
                            base_delay_seconds=self.retry_base_delay_seconds,
                            attempt_index=attempt,
                        )
                        logger.warning(
                            "llm_call_retry target=%s qa_id=%s ticket_id=%s model=%s base_url=%s attempt=%s elapsed_ms=%s retry_reason=%s status_code=%s retry_delay_seconds=%s body_preview=%s",
                            "repair.krss_diagnosis",
                            ticket.id,
                            ticket.ticket_id,
                            self.model,
                            self.base_url,
                            attempt + 1,
                            elapsed_ms,
                            retry.reason,
                            retry.status_code,
                            delay_seconds,
                            retry.body_preview,
                            extra={
                                "target": "repair.krss_diagnosis",
                                "qa_id": ticket.id,
                                "ticket_id": ticket.ticket_id,
                                "model": self.model,
                                "base_url": self.base_url,
                                "attempt": attempt + 1,
                                "elapsed_ms": elapsed_ms,
                                "retry_reason": retry.reason,
                                "status_code": retry.status_code,
                                "retry_delay_seconds": delay_seconds,
                                "body_preview": retry.body_preview,
                            },
                        )
                        continue
                    logger.warning(
                        "llm_call_failed target=%s qa_id=%s ticket_id=%s model=%s base_url=%s elapsed_ms=%s attempts=%s retry_reason=%s status_code=%s body_preview=%s error=%s",
                        "repair.krss_diagnosis",
                        ticket.id,
                        ticket.ticket_id,
                        self.model,
                        self.base_url,
                        elapsed_ms,
                        attempt + 1,
                        retry.reason,
                        retry.status_code,
                        retry.body_preview,
                        str(exc),
                        extra={
                            "target": "repair.krss_diagnosis",
                            "qa_id": ticket.id,
                            "ticket_id": ticket.ticket_id,
                            "model": self.model,
                            "base_url": self.base_url,
                            "elapsed_ms": elapsed_ms,
                            "attempts": attempt + 1,
                            "retry_reason": retry.reason,
                            "status_code": retry.status_code,
                            "body_preview": retry.body_preview,
                            "error": str(exc),
                        },
                    )
                    raise

        content = payload["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.strip("`")
            if content.startswith("json"):
                content = content[4:].strip()

        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("KRSS diagnosis response must be a JSON object")
        elapsed_ms = int((time.monotonic() - started) * 1000)
        request_id = extract_request_id(getattr(response, "headers", None))
        logger.warning(
            "llm_call_succeeded target=%s qa_id=%s ticket_id=%s model=%s base_url=%s elapsed_ms=%s request_id=%s",
            "repair.krss_diagnosis",
            ticket.id,
            ticket.ticket_id,
            self.model,
            self.base_url,
            elapsed_ms,
            request_id,
            extra={
                "target": "repair.krss_diagnosis",
                "qa_id": ticket.id,
                "ticket_id": ticket.ticket_id,
                "model": self.model,
                "base_url": self.base_url,
                "elapsed_ms": elapsed_ms,
                "request_id": request_id,
            },
        )
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
