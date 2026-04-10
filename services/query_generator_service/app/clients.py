from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional, Tuple

import httpx

from shared.models import EvaluationSubmissionRequest, EvaluationSubmissionResponse, PromptFetchResponse
from shared.schema_profile import NETWORK_SCHEMA_V10_CONTEXT, NETWORK_SCHEMA_V10_HINTS

logger = logging.getLogger("query_generator")


class HeuristicCypherGenerator:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def generate_from_prompt(self, task_id: str, question_text: str, generation_prompt: str) -> Dict[str, str]:
        question = question_text.lower()

        if any(token in question for token in ["这个", "那个", "随便", "怎么弄"]):
            cypher = "MATCH (n:NetworkElement) RETURN n.id AS id, n.name AS name LIMIT 10"
            summary = "Generated a safe fallback query because the question is ambiguous or underspecified."
        else:
            cypher, summary = self._generate_network_schema_v10_query(question)

        return {
            "raw_output": json.dumps(
                {
                    "cypher": cypher,
                    "notes": f"[heuristic] {summary} Schema context: {NETWORK_SCHEMA_V10_CONTEXT}",
                },
                ensure_ascii=False,
            ),
            "model_name": self.model_name,
        }

    def _generate_network_schema_v10_query(self, question: str) -> Tuple[str, str]:
        wants_count = any(token in question for token in ["数量", "多少", "count", "总数", "几个"])

        if any(token in question for token in ["设备", "network element", "router", "网络设备"]) and any(
            token in question for token in ["端口", "port", "接口"]
        ):
            if wants_count:
                return (
                    "MATCH (ne:NetworkElement)-[:HAS_PORT]->(p:Port) RETURN ne.name AS device_name, count(p) AS port_count LIMIT 20",
                    "Built a relationship query from NetworkElement to Port using HAS_PORT.",
                )
            return (
                "MATCH (ne:NetworkElement)-[:HAS_PORT]->(p:Port) RETURN ne.name AS device_name, p.name AS port_name, p.status AS port_status LIMIT 20",
                "Built a relationship query from NetworkElement to Port using HAS_PORT.",
            )

        if any(token in question for token in ["服务", "service"]) and any(token in question for token in ["隧道", "tunnel"]):
            return (
                "MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel) RETURN s.name AS service_name, t.name AS tunnel_name, t.bandwidth AS tunnel_bandwidth LIMIT 20",
                "Matched services and tunnels using SERVICE_USES_TUNNEL.",
            )

        if any(token in question for token in ["隧道", "tunnel"]) and any(token in question for token in ["协议", "protocol"]):
            return (
                "MATCH (t:Tunnel)-[:TUNNEL_PROTO]->(p:Protocol) RETURN t.name AS tunnel_name, p.name AS protocol_name, p.standard AS standard LIMIT 20",
                "Matched tunnels and protocols using TUNNEL_PROTO.",
            )

        if any(token in question for token in ["隧道", "tunnel"]) and any(token in question for token in ["经过", "path", "hop"]):
            return (
                "MATCH (t:Tunnel)-[r:PATH_THROUGH]->(ne:NetworkElement) RETURN t.name AS tunnel_name, ne.name AS hop_name, r.hop_order AS hop_order ORDER BY tunnel_name, hop_order LIMIT 50",
                "Matched tunnel paths through network elements using PATH_THROUGH.",
            )

        entity_key = self._detect_entity(question)
        if entity_key:
            entity = NETWORK_SCHEMA_V10_HINTS[entity_key]
            alias = entity["return_fields"][0].split(".")[0]
            if wants_count:
                return (
                    "MATCH ({alias}:{label}) RETURN count({alias}) AS count".format(
                        alias=alias,
                        label=entity["label"],
                    ),
                    "Built a count query for the detected schema entity.",
                )
            return (
                "MATCH ({alias}:{label}) RETURN {fields} LIMIT 20".format(
                    alias=alias,
                    label=entity["label"],
                    fields=", ".join(entity["return_fields"]),
                ),
                "Built a direct label query using the detected schema entity.",
            )

        return (
            "MATCH (n:NetworkElement) RETURN n.id AS id, n.name AS name, n.ip_address AS ip_address LIMIT 10",
            "Used NetworkElement as the safest default entity for this graph.",
        )

    def _detect_entity(self, question: str) -> str:
        for entity_key, entity in NETWORK_SCHEMA_V10_HINTS.items():
            if any(keyword in question for keyword in entity["keywords"]):
                return entity_key
        return ""


class OpenAICompatibleCypherGenerator:
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

    async def generate_from_prompt(self, task_id: str, question_text: str, generation_prompt: str) -> Dict[str, str]:
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
                    "messages": [{"role": "user", "content": generation_prompt}],
                },
            )
            response.raise_for_status()
            payload = response.json()

        content = payload["choices"][0]["message"]["content"]
        return {
            "raw_output": content,
            "model_name": self.model,
        }


class QwenGeneratorClient:
    def __init__(
        self,
        heuristic_generator: HeuristicCypherGenerator,
        llm_generator: Optional[OpenAICompatibleCypherGenerator] = None,
    ) -> None:
        self.heuristic_generator = heuristic_generator
        self.llm_generator = llm_generator

    async def generate_from_prompt(self, task_id: str, question_text: str, generation_prompt: str) -> Dict[str, str]:
        if self.llm_generator is not None:
            try:
                logger.info("LLM call started for id=%s", task_id)
                result = await self.llm_generator.generate_from_prompt(task_id, question_text, generation_prompt)
                logger.info("LLM call succeeded for id=%s", task_id)
                return result
            except Exception as exc:
                logger.warning("LLM call failed for id=%s: %s: %s", task_id, type(exc).__name__, exc)
                fallback = self.heuristic_generator.generate_from_prompt(task_id, question_text, generation_prompt)
                fallback["raw_output"] = json.dumps(
                    {
                        "cypher": json.loads(fallback["raw_output"]).get("cypher", ""),
                        "notes": (
                            f"[fallback-after-llm-error] {json.loads(fallback['raw_output']).get('notes', '')} "
                            f"LLM error: {type(exc).__name__}: {exc}"
                        ),
                    },
                    ensure_ascii=False,
                )
                return fallback

        fallback = self.heuristic_generator.generate_from_prompt(task_id, question_text, generation_prompt)
        fallback["raw_output"] = json.dumps(
            {
                "cypher": json.loads(fallback["raw_output"]).get("cypher", ""),
                "notes": f"[fallback-no-llm-config] {json.loads(fallback['raw_output']).get('notes', '')}",
            },
            ensure_ascii=False,
        )
        return fallback


class PromptServiceClient:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def fetch_prompt(self, task_id: str, question_text: str) -> str:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/prompt-generation/fetch",
                json={"task_id": task_id, "question_text": question_text},
            )
            response.raise_for_status()
            payload = PromptFetchResponse.model_validate(response.json())
            return payload.generation_prompt


class TestingServiceClient:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def submit(self, payload: EvaluationSubmissionRequest) -> EvaluationSubmissionResponse:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/evaluations/submissions",
                json=payload.model_dump(),
            )
            response.raise_for_status()
            return EvaluationSubmissionResponse.model_validate(response.json())
