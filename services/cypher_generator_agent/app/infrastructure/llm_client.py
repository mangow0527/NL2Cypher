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

    def generate_structured(
        self,
        *,
        prompt: str,
        schema_name: str,
        schema: Mapping[str, Any],
        attempt: int,
    ) -> Mapping[str, Any]:
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
                            "content": _schema_bound_prompt(
                                prompt=prompt,
                                schema_name=schema_name,
                                schema=schema,
                                attempt=attempt,
                            ),
                        }
                    ],
                },
            )
            response.raise_for_status()

        content = _response_content(response.json())
        payload = json.loads(_strip_json_fence(content))
        if not isinstance(payload, Mapping):
            raise ValueError("structured LLM response must be a JSON object")
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
            "Return exactly one JSON object. Do not return markdown or prose.",
            f"Schema name: {schema_name}",
            f"Attempt: {attempt}",
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
