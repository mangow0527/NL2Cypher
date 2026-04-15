from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable

import httpx


SleepFn = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class RetryDecision:
    should_retry: bool
    reason: str
    status_code: int | None = None
    body_preview: str | None = None


def extract_request_id(headers: object) -> str | None:
    if not headers:
        return None
    for key in ("x-request-id", "request-id", "x-trace-id"):
        value = getattr(headers, "get", lambda _key, _default=None: None)(key, None)
        if value:
            return str(value)
    return None


def response_body_preview(response: httpx.Response | None, limit: int = 240) -> str | None:
    if response is None:
        return None
    text = (response.text or "").strip()
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def classify_retryable_error(exc: Exception) -> RetryDecision:
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        if status_code == 429:
            return RetryDecision(
                should_retry=True,
                reason="rate_limited",
                status_code=status_code,
                body_preview=response_body_preview(exc.response),
            )
        if 500 <= status_code < 600:
            return RetryDecision(
                should_retry=True,
                reason="server_error",
                status_code=status_code,
                body_preview=response_body_preview(exc.response),
            )
        return RetryDecision(
            should_retry=False,
            reason="non_retryable_http_status",
            status_code=status_code,
            body_preview=response_body_preview(exc.response),
        )

    if isinstance(exc, httpx.TimeoutException):
        return RetryDecision(should_retry=True, reason="timeout")
    if isinstance(exc, httpx.TransportError):
        return RetryDecision(should_retry=True, reason="transport_error")

    return RetryDecision(should_retry=False, reason="non_retryable_exception")


async def sleep_with_backoff(
    *,
    sleep_fn: SleepFn = asyncio.sleep,
    base_delay_seconds: float,
    attempt_index: int,
) -> float:
    delay_seconds = base_delay_seconds * (2 ** max(0, attempt_index))
    await sleep_fn(delay_seconds)
    return delay_seconds
