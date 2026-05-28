from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from services.cypher_generator_agent.app.literals.models import LiteralResolverResult
from services.cypher_generator_agent.app.retrieval.models import (
    CandidateRetrievalResult,
    SemanticCandidate,
)

from .models import GROUNDED_UNDERSTANDING_SCHEMA_VERSION, grounded_understanding_json_schema


def build_grounded_understanding_prompt(
    *,
    question_decomposition: Mapping[str, Any] | object,
    candidates: CandidateRetrievalResult | Sequence[SemanticCandidate] | Mapping[str, Any],
    literal_results: Sequence[LiteralResolverResult | Mapping[str, Any]],
    repair_context: Mapping[str, Any] | None = None,
) -> str:
    payload = {
        "question_decomposition": _dump_model(question_decomposition),
        "top_candidates": [_candidate_payload(candidate) for candidate in _coerce_candidates(candidates)],
        "literal_resolver_results": [_dump_model(result) for result in literal_results],
    }
    if repair_context:
        payload["repair_context"] = dict(repair_context)
    return "\n".join(
        [
            "你是图原生 Cypher 生成流水线中的语义落地理解选择器。",
            f"只返回符合 {GROUNDED_UNDERSTANDING_SCHEMA_VERSION} schema 的结构化结果。",
            "只能从 top_candidates 中按 candidate_id 选择候选项。",
            "每个 selected binding 必须从候选 payload 中原样复制 semantic_type、semantic_id、semantic_name 和 owner。",
            "literal_resolver_results 中已解析成功的字面值是过滤条件的权威来源：必须原样复制到 selected_literals；如果存在匹配 expected_vertex/expected_edge + expected_property 的属性候选，必须选择该属性候选。",
            "不要因为另一个候选也包含相同枚举值，就为已解析字面值选择不同属性。",
            "如果两个或多个候选很接近且无法安全选择，把它们的 candidate_id 放入 ambiguities，不要为该角色编造 selected binding。",
            "如果存在 repair_context，请修复上一轮语义错误，但不要发明 top_candidates 之外的语义对象。",
            "不要生成 Cypher，不要连接数据库，不要解释过程，不要返回 Markdown。",
            "输入 JSON：",
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
        ]
    )


def build_grounded_understanding_schema() -> dict[str, Any]:
    return grounded_understanding_json_schema()


def candidate_id(candidate: SemanticCandidate) -> str:
    return f"{candidate.semantic_type}:{candidate.semantic_id}"


def _candidate_payload(candidate: SemanticCandidate) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id(candidate),
        "semantic_type": candidate.semantic_type,
        "semantic_id": candidate.semantic_id,
        "semantic_name": candidate.semantic_name,
        "owner": candidate.owner,
        "score": candidate.score,
        "match_type": candidate.match_type,
        "evidence": [evidence.model_dump() for evidence in candidate.evidence],
        "metadata": candidate.metadata,
    }


def _coerce_candidates(
    candidates: CandidateRetrievalResult | Sequence[SemanticCandidate] | Mapping[str, Any],
) -> list[SemanticCandidate]:
    if isinstance(candidates, CandidateRetrievalResult):
        return list(candidates.candidates)
    if isinstance(candidates, Mapping):
        return [
            candidate if isinstance(candidate, SemanticCandidate) else SemanticCandidate.model_validate(candidate)
            for candidate in candidates.get("candidates", [])
        ]
    return [
        candidate if isinstance(candidate, SemanticCandidate) else SemanticCandidate.model_validate(candidate)
        for candidate in candidates
    ]


def _dump_model(value: Any) -> dict[str, Any]:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, dict):
            return dumped
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"cannot serialize grounded understanding input: {value!r}")
