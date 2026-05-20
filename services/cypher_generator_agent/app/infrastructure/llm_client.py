from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx


class OpenAICompatibleCompletionClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 60.0,
        temperature: float = 0.0,
        enable_thinking: bool | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.enable_thinking = enable_thinking
        self.max_tokens = max_tokens

    @classmethod
    def from_environment(cls) -> "OpenAICompatibleCompletionClient | None":
        enabled = os.getenv("CYPHER_GENERATOR_AGENT_LLM_ENABLED", "true").strip().lower()
        if enabled in {"0", "false", "no"}:
            return None
        base_url = _first_env("CYPHER_GENERATOR_AGENT_LLM_BASE_URL", "OPENAI_BASE_URL")
        api_key = _first_env("CYPHER_GENERATOR_AGENT_LLM_API_KEY", "OPENAI_API_KEY")
        model = _first_env("CYPHER_GENERATOR_AGENT_LLM_MODEL", "OPENAI_MODEL")
        if not base_url or not api_key or not model:
            return None
        return cls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout_seconds=float(os.getenv("CYPHER_GENERATOR_AGENT_LLM_TIMEOUT_SECONDS", "60")),
            temperature=float(os.getenv("CYPHER_GENERATOR_AGENT_LLM_TEMPERATURE", "0")),
            enable_thinking=_optional_bool_env("CYPHER_GENERATOR_AGENT_LLM_ENABLE_THINKING")
            if _first_env("CYPHER_GENERATOR_AGENT_LLM_ENABLE_THINKING") is not None
            else _default_enable_thinking_for_model(model),
            max_tokens=_optional_int_env("CYPHER_GENERATOR_AGENT_LLM_MAX_TOKENS"),
        )

    def complete(self, prompt: str) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if self.enable_thinking is not None:
            payload["enable_thinking"] = self.enable_thinking
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        with httpx.Client(timeout=self.timeout_seconds, trust_env=False) as client:
            response = client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        response.raise_for_status()
        payload = response.json()
        return str(payload["choices"][0]["message"]["content"])


def _first_env(*names: str) -> str | None:
    dotenv = _read_dotenv()
    for name in names:
        value = os.getenv(name) or dotenv.get(name)
        if value:
            return value
    return None


def _optional_bool_env(name: str) -> bool | None:
    value = _first_env(name)
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


def _optional_int_env(name: str) -> int | None:
    value = _first_env(name)
    if value is None:
        return None
    return int(value)


def _default_enable_thinking_for_model(model: str) -> bool | None:
    normalized = model.strip().lower()
    if normalized.startswith("qwen3-") and "-vl-" not in normalized and not normalized.endswith("-thinking"):
        return False
    return None


def _read_dotenv() -> dict[str, str]:
    path = Path.cwd() / ".env"
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values
