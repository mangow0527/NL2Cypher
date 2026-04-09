from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

import httpx

from shared.models import IssueTicket, RepairPlanEnvelope

logger = logging.getLogger("testing_service")


class RepairServiceClient:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def submit_issue_ticket(self, ticket: IssueTicket) -> RepairPlanEnvelope:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/issue-tickets",
                json=ticket.model_dump(),
            )
            response.raise_for_status()
            return RepairPlanEnvelope.model_validate(response.json())


class LLMEvaluationClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float,
        temperature: float,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature

    async def evaluate(
        self,
        question: str,
        expected_cypher: str,
        expected_answer: Any,
        actual_cypher: str,
        actual_result: Any,
        rule_based_verdict: str,
        rule_based_dimensions: Dict[str, str],
    ) -> Optional[Dict[str, Any]]:
        system_prompt = (
            "You are a Cypher query evaluation expert for a graph database (TuGraph). "
            "You are given a natural language question, a golden (expected) Cypher query and its expected answer, "
            "and the actual generated Cypher query with its execution result. "
            "You also receive the verdict from a rule-based evaluation system.\n\n"
            "Your task is to provide a semantic assessment that goes beyond exact string matching. "
            "Consider whether the actual query semantically answers the same question, even if the Cypher syntax differs. "
            "Consider whether the actual result is semantically equivalent to the expected result, even if field order, "
            "formatting, or extra fields differ.\n\n"
            "Return JSON only with these keys:\n"
            '- "result_correctness": "pass" or "fail" — is the actual result semantically equivalent to the expected answer?\n'
            '- "question_alignment": "pass" or "fail" — does the actual query target the same semantic intent as the question?\n'
            '- "reasoning": a brief explanation of your judgment\n'
            '- "confidence": a float between 0 and 1'
        )
        user_prompt = (
            f"Question: {question}\n\n"
            f"Expected Cypher: {expected_cypher}\n"
            f"Expected Answer: {json.dumps(expected_answer, ensure_ascii=False, default=str)}\n\n"
            f"Actual Cypher: {actual_cypher}\n"
            f"Actual Result: {json.dumps(actual_result, ensure_ascii=False, default=str)}\n\n"
            f"Rule-based verdict: {rule_based_verdict}\n"
            f"Rule-based dimensions: {json.dumps(rule_based_dimensions, ensure_ascii=False)}\n\n"
            "Provide your semantic evaluation."
        )

        try:
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

            result = json.loads(content)
            logger.info(
                "LLM evaluation: result_correctness=%s, question_alignment=%s, confidence=%s",
                result.get("result_correctness"),
                result.get("question_alignment"),
                result.get("confidence"),
            )
            return result

        except Exception as exc:
            logger.warning("LLM evaluation failed: %s: %s", type(exc).__name__, exc)
            return None
