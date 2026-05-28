from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from services.cypher_generator_agent.app.infrastructure.llm_client import (
    OpenAICompatibleStructuredLLMClient,
)


def test_openai_compatible_client_posts_schema_bound_json_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, Any]] = []

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(
            self,
            url: str,
            *,
            headers: dict[str, str],
            json: dict[str, Any],
        ) -> httpx.Response:
            requests.append({"url": url, "headers": headers, "json": json, "timeout": self.timeout})
            return httpx.Response(
                200,
                headers={"x-request-id": "req-123"},
                json={
                    "choices": [
                        {
                            "message": {
                                "content": '{"schema_version":"question_decomposition_v1","intent_type":"list"}'
                            }
                        }
                    ]
                },
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(httpx, "Client", FakeClient)

    client = OpenAICompatibleStructuredLLMClient(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1/",
        api_key="test-key",
        model="qwen3-32b",
        temperature=0.1,
        timeout_seconds=12.0,
    )

    result = client.generate_structured(
        prompt="Decompose this question.",
        schema_name="question_decomposition_v1",
        schema={"type": "object", "required": ["schema_version"]},
        attempt=2,
    )

    assert result == {"schema_version": "question_decomposition_v1", "intent_type": "list"}
    request = requests[0]
    assert request["url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer test-key"
    assert request["json"]["model"] == "qwen3-32b"
    assert request["json"]["temperature"] == 0.1
    assert request["json"]["enable_thinking"] is False
    assert request["json"]["response_format"] == {"type": "json_object"}
    assert request["json"]["messages"][0]["role"] == "user"
    assert "Decompose this question." in request["json"]["messages"][0]["content"]
    assert "question_decomposition_v1" in request["json"]["messages"][0]["content"]
    assert "只返回一个 JSON 对象" in request["json"]["messages"][0]["content"]
    assert "不要返回 Markdown" in request["json"]["messages"][0]["content"]
    assert "Schema 名称" in request["json"]["messages"][0]["content"]
    assert "第 2 次尝试" in request["json"]["messages"][0]["content"]
    assert "Return exactly one JSON object" not in request["json"]["messages"][0]["content"]
    assert '"required": ["schema_version"]' in request["json"]["messages"][0]["content"]
    assert request["timeout"] == 12.0


def test_openai_compatible_client_strips_markdown_json_fences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, **_: Any) -> httpx.Response:
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "```json\n{\"ok\": true}\n```"}}]},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(httpx, "Client", FakeClient)

    client = OpenAICompatibleStructuredLLMClient(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="qwen3-32b",
        temperature=0.1,
        timeout_seconds=12.0,
    )

    assert client.generate_structured(prompt="p", schema_name="s", schema={}, attempt=1) == {"ok": True}


def test_openai_compatible_client_rejects_non_object_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, **_: Any) -> httpx.Response:
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": json.dumps(["not", "object"])}}]},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(httpx, "Client", FakeClient)
    client = OpenAICompatibleStructuredLLMClient(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="qwen3-32b",
        temperature=0.1,
        timeout_seconds=12.0,
    )

    with pytest.raises(ValueError, match="structured LLM response must be a JSON object"):
        client.generate_structured(prompt="p", schema_name="s", schema={}, attempt=1)
