from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import httpx


class OpenAICompatibleStructuredLLMClient:
    provider = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float,
        timeout_seconds: float,
    ) -> None:
        if not base_url.strip():
            raise ValueError("base_url is required")
        if not api_key.strip():
            raise ValueError("api_key is required")
        if not model.strip():
            raise ValueError("model is required")

        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds
        self.last_call_trace: dict[str, Any] | None = None

    def generate_structured(
        self,
        *,
        prompt: str,
        schema_name: str,
        schema: Mapping[str, Any],
        attempt: int,
    ) -> Mapping[str, Any]:
        prompt_markdown = _schema_bound_prompt(
            prompt=prompt,
            schema_name=schema_name,
            schema=schema,
            attempt=attempt,
        )
        self.last_call_trace = None
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "temperature": self.temperature,
                    "enable_thinking": False,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt_markdown,
                        }
                    ],
                },
            )
            response.raise_for_status()

        content = _response_content(response.json())
        self.last_call_trace = {
            "schema_name": schema_name,
            "attempt": attempt,
            "model": self.model,
            "prompt": prompt_markdown,
            "raw_output": content,
            "status": "success",
        }
        payload = json.loads(_strip_json_fence(content))
        if not isinstance(payload, Mapping):
            raise ValueError("structured LLM response must be a JSON object")
        return payload


class TracedStructuredLLMClient:
    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.trace_calls: list[dict[str, Any]] = []

    @property
    def provider(self) -> str:
        return str(getattr(self.inner, "provider", "unknown"))

    def generate_structured(
        self,
        *,
        prompt: str,
        schema_name: str,
        schema: Mapping[str, Any],
        attempt: int,
    ) -> Mapping[str, Any]:
        prompt_markdown = _schema_bound_prompt(
            prompt=prompt,
            schema_name=schema_name,
            schema=schema,
            attempt=attempt,
        )
        call: dict[str, Any] = {
            "call_id": f"{schema_name}-attempt-{attempt}",
            "schema_name": schema_name,
            "attempt": attempt,
            "provider": self.provider,
            "model": getattr(self.inner, "model", None),
            "prompt": prompt_markdown,
            "raw_output": "",
            "parsed_output": None,
            "status": "running",
            "error": None,
        }
        try:
            payload = self.inner.generate_structured(
                prompt=prompt,
                schema_name=schema_name,
                schema=schema,
                attempt=attempt,
            )
        except Exception as exc:
            inner_trace = getattr(self.inner, "last_call_trace", None)
            if isinstance(inner_trace, Mapping):
                call["model"] = inner_trace.get("model") or call["model"]
                call["prompt"] = inner_trace.get("prompt") or call["prompt"]
                call["raw_output"] = inner_trace.get("raw_output") or ""
            call["status"] = "failed"
            call["error"] = {
                "type": exc.__class__.__name__,
                "message": str(exc),
            }
            self.trace_calls.append(call)
            raise

        inner_trace = getattr(self.inner, "last_call_trace", None)
        if isinstance(inner_trace, Mapping):
            call["model"] = inner_trace.get("model") or call["model"]
            call["prompt"] = inner_trace.get("prompt") or call["prompt"]
            call["raw_output"] = inner_trace.get("raw_output") or ""
        if not call["raw_output"]:
            call["raw_output"] = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        call["parsed_output"] = dict(payload)
        call["status"] = "success"
        self.trace_calls.append(call)
        return payload


def _schema_bound_prompt(
    *,
    prompt: str,
    schema_name: str,
    schema: Mapping[str, Any],
    attempt: int,
) -> str:
    return "\n".join(
        [
            prompt,
            "",
            "只返回一个 JSON 对象。不要返回 Markdown，不要返回解释性文字。",
            f"Schema 名称：{schema_name}",
            f"第 {attempt} 次尝试。",
            "JSON Schema:",
            json.dumps(schema, ensure_ascii=False, sort_keys=True),
        ]
    )


def _response_content(payload: Mapping[str, Any]) -> str:
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("LLM response missing choices[0].message.content") from exc
    if not isinstance(content, str) or not content.strip():
        raise ValueError("LLM response content must be non-empty text")
    return content.strip()


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if not lines:
        return stripped
    if lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()
