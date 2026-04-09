from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional, Tuple

import httpx

from shared.models import CypherGenerationRequest, EvaluationSubmissionRequest, EvaluationSubmissionResponse, GeneratedCypher
from shared.schema_profile import NETWORK_SCHEMA_V10_CONTEXT, NETWORK_SCHEMA_V10_HINTS

logger = logging.getLogger("query_generator")


class HeuristicCypherGenerator:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def generate(self, request: CypherGenerationRequest) -> GeneratedCypher:
        context = request.context
        question = context.question.lower()

        if any(token in question for token in ["这个", "那个", "随便", "怎么弄"]):
            cypher = "MATCH (n:NetworkElement) RETURN n.id AS id, n.name AS name LIMIT 10"
            summary = "Generated a safe fallback query because the question is ambiguous or underspecified."
        else:
            cypher, summary = self._generate_network_schema_v10_query(question)

        return GeneratedCypher(
            cypher=cypher,
            model=self.model_name,
            reasoning_summary=f"[heuristic] {summary} Schema context: {NETWORK_SCHEMA_V10_CONTEXT}",
        )

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

    async def generate(self, request: CypherGenerationRequest) -> GeneratedCypher:
        prompt = self._build_messages(request)
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
                    "messages": prompt,
                },
            )
            response.raise_for_status()
            payload = response.json()

        content = payload["choices"][0]["message"]["content"]
        cypher = self._extract_cypher(content)
        return GeneratedCypher(
            cypher=cypher,
            model=self.model,
            reasoning_summary="[llm] Generated Cypher using schema-aware and knowledge-aware prompt over network_schema_v10.",
        )

    def _build_messages(self, request: CypherGenerationRequest) -> List[Dict[str, str]]:
        context = request.context
        system_prompt = (
            "You are a Cypher generation engine for TuGraph. "
            "Generate a single valid Cypher query for graph network_schema_v10. "
            "Only use labels, properties, and edge directions that appear in the schema context and knowledge hint. "
            "Return JSON only in the shape {\"cypher\":\"...\",\"notes\":\"...\"}."
        )
        user_prompt = (
            f"Question ID: {context.id}\n"
            f"Question: {context.question}\n"
            f"Knowledge context: {context.knowledge_context.model_dump_json() if context.knowledge_context else 'none'}\n"
            f"Knowledge/schema hint:\n{context.schema_hint or 'none'}\n\n"
            f"Schema context:\n{NETWORK_SCHEMA_V10_CONTEXT}\n"
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _extract_cypher(self, content: str) -> str:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            elif cleaned.startswith("cypher"):
                cleaned = cleaned[6:].strip()

        try:
            parsed = json.loads(cleaned)
            cypher = parsed.get("cypher", "").strip()
            if cypher:
                return cypher
        except json.JSONDecodeError:
            pass

        if "```cypher" in content:
            fragment = content.split("```cypher", 1)[1].split("```", 1)[0].strip()
            if fragment:
                return fragment

        if "```" in content:
            fragment = content.split("```", 1)[1].split("```", 1)[0].strip()
            if fragment:
                return fragment

        return cleaned


class QwenGeneratorClient:
    def __init__(
        self,
        heuristic_generator: HeuristicCypherGenerator,
        llm_generator: Optional[OpenAICompatibleCypherGenerator] = None,
    ) -> None:
        self.heuristic_generator = heuristic_generator
        self.llm_generator = llm_generator

    async def generate(self, request: CypherGenerationRequest) -> GeneratedCypher:
        if self.llm_generator is not None:
            try:
                logger.info("LLM call started for id=%s", request.context.id)
                result = await self.llm_generator.generate(request)
                logger.info("LLM call succeeded for id=%s, cypher=%s", request.context.id, result.cypher)
                return result
            except Exception as exc:
                logger.warning("LLM call failed for id=%s: %s: %s", request.context.id, type(exc).__name__, exc)
                fallback = self.heuristic_generator.generate(request)
                fallback.reasoning_summary = (
                    f"[fallback-after-llm-error] {fallback.reasoning_summary} "
                    f"LLM error: {type(exc).__name__}: {exc}"
                )
                return fallback

        fallback = self.heuristic_generator.generate(request)
        fallback.reasoning_summary = f"[fallback-no-llm-config] {fallback.reasoning_summary}"
        return fallback


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
