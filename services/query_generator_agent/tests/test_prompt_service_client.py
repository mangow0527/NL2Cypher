import asyncio
import unittest
from unittest.mock import patch

import httpx

from services.query_generator_agent.app.clients import PromptServiceClient


class _FakeAsyncClient:
    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def post(self, url: str, json: dict[str, str]) -> httpx.Response:
        return self._response


class PromptServiceClientTest(unittest.TestCase):
    def test_fetch_prompt_reads_prompt_from_text_response(self) -> None:
        response = httpx.Response(
            status_code=200,
            headers={"content-type": "text/plain; charset=utf-8"},
            text="MATCH (n) RETURN n",
            request=httpx.Request("POST", "http://knowledge-ops/api/knowledge/rag/prompt-package"),
        )
        client = PromptServiceClient(base_url="http://knowledge-ops", timeout_seconds=5)

        with patch("services.query_generator_agent.app.clients.httpx.AsyncClient", return_value=_FakeAsyncClient(response)):
            prompt = asyncio.run(client.fetch_prompt(id="qa-1", question="查询所有节点"))

        self.assertEqual(prompt, "MATCH (n) RETURN n")


if __name__ == "__main__":
    unittest.main()
