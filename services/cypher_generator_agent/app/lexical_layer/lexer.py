from __future__ import annotations

from dataclasses import dataclass, replace
from collections import deque
import os
import re
from typing import Any

import yaml

from .mention_vector_recall import MentionVectorRetriever, RagMentionVectorRetriever
from .overlap_resolver import DictionaryPriorities, OverlapResolver
from .types import normalize_expected_mention_type, normalize_mention_type
from services.cypher_generator_agent.app.infrastructure import resource_paths
from services.cypher_generator_agent.app.ontology_layer.assets import OntologyAssets
from services.cypher_generator_agent.app.ontology_layer.models import ContextSignal, DictionaryEntry, LexerTrace, Mention
from services.cypher_generator_agent.app.question_framing_layer.models import QuestionFramingRole, QuestionFramingTrace


SHAPE_SIGNAL_SPECS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (
        ("path_enumeration_hint", "path_answer_hint"),
        ("所有路径", "全部路径", "多条路径", "候选路径", "路径列表", "所有可达路径"),
    ),
    (
        ("topology_answer_hint", "path_answer_hint"),
        ("周边拓扑", "局部拓扑", "资源拓扑", "链路拓扑", "拓扑子图", "完整资源拓扑", "拓扑"),
    ),
    (
        ("path_answer_hint",),
        (
            "完整路径",
            "路径详情",
            "路径明细",
            "经过顺序",
            "网络设备顺序",
            "服务到端口的路径",
            "完整经过路径",
            "经过路径",
            "业务路径",
            "链路明细",
            "形成的路径",
            "构成的路径",
            "所构成的路径",
        ),
    ),
    (
        ("aggregation_hint", "count_hint"),
        ("统计", "数量", "总数", "个数", "多少", "共有多少", "有多少", "一共有多少", "总共有多少"),
    ),
    (
        ("group_by_hint",),
        ("按", "各", "每个", "每种", "每类", "分别统计", "分布", "分组统计"),
    ),
    (
        ("ranking_hint", "order_hint"),
        ("最高", "最低", "最多", "最少", "最大", "最小", "排名", "top", "Top", "排序", "降序", "升序", "从高到低", "从低到高"),
    ),
    (
        ("limit_hint",),
        ("最多返回", "只显示", "限制返回"),
    ),
    (
        ("time_grain_hint",),
        ("按天", "按日", "按月", "按年", "按小时", "每天", "每月", "每小时", "最近", "历史", "趋势", "同比", "环比"),
    ),
    (
        ("existence_hint",),
        ("是否存在", "有没有", "是否有", "是否", "能否", "能不能", "是否能", "存在吗", "存在么"),
    ),
)

GENERIC_STANDALONE_VECTOR_FRAGMENTS: set[str] = {
    "对应",
    "相关",
    "之间",
    "连接",
    "连接关系",
    "关联",
    "关联关系",
    "关系",
    "属性",
    "信息",
    "记录",
    "拥有",
    "及其",
    "各自",
}

@dataclass(frozen=True)
class _StructuredOperatorRule:
    canonical_id: str
    surface_forms: tuple[str, ...]
    cypher_op: str
    applies_to: tuple[str, ...]
    arity: int


@dataclass(frozen=True)
class _StructuredQuantifierRule:
    canonical_id: str
    surface_forms: tuple[str, ...]
    semantic: str
    shape_effect: str
    affects_intent: bool


@dataclass(frozen=True)
class _StructuredLiteralPattern:
    canonical_id: str
    mention_type: str
    value_type: str
    regex: str


@dataclass(frozen=True)
class _StructuredExtractionResources:
    operators: tuple[_StructuredOperatorRule, ...]
    quantifiers: tuple[_StructuredQuantifierRule, ...]
    literal_patterns: tuple[_StructuredLiteralPattern, ...]


@dataclass(frozen=True)
class _RawMatch:
    hit_id: str
    canonical_id: str
    mention_type: str
    surface: str
    span_start: int
    span_end: int
    match_source: str
    metadata: dict[str, Any]
    score: float

    @property
    def length(self) -> int:
        return self.span_end - self.span_start

    def to_mention(self) -> Mention:
        return Mention(
            canonical_id=self.canonical_id,
            mention_type=normalize_mention_type(self.mention_type),
            surface=self.surface,
            span_start=self.span_start,
            span_end=self.span_end,
            metadata=dict(self.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "mention_type": normalize_mention_type(self.mention_type),
            "surface": self.surface,
            "span": [self.span_start, self.span_end],
            "hit_id": self.hit_id,
            "match_source": self.match_source,
            "score": self.score,
        }


class OntologyLexer:
    def __init__(
        self,
        assets: OntologyAssets,
        *,
        vector_retriever: MentionVectorRetriever | None = None,
        vector_top_k: int = 5,
        vector_accept_threshold: float = 0.4,
    ) -> None:
        self.assets = assets
        self._automaton = _SurfaceAutomaton.from_entries(assets.entries)
        self._overlap_resolver = OverlapResolver(DictionaryPriorities.default())
        self._structured_resources = _load_structured_extraction_resources()
        self._vector_retriever = vector_retriever
        self._vector_top_k = vector_top_k
        self._vector_accept_threshold = vector_accept_threshold

    @classmethod
    def from_default_resources(cls, assets: OntologyAssets) -> "OntologyLexer":
        return cls(
            assets,
            vector_retriever=RagMentionVectorRetriever.from_environment(),
            vector_accept_threshold=float(os.getenv("NL2CYPHER_MENTION_VECTOR_ACCEPT_THRESHOLD", "0.4")),
        )

    def run(self, question: str, *, question_framing: QuestionFramingTrace | None = None) -> LexerTrace:
        ac_matches = _filter_role_incompatible_ac_matches(
            self._scan(question),
            question_framing,
        )
        structural_matches = self._structured_cue_extract(question)
        pre_literal_matches = tuple((*ac_matches, *structural_matches))
        pre_literal_unmatched_fragments = _unmatched_fragments_from_matches(
            question,
            pre_literal_matches,
            question_framing=question_framing,
        )
        literal_matches = self._literal_extract(question, pre_literal_unmatched_fragments)
        structured_matches = tuple((*structural_matches, *literal_matches))
        raw_matches = tuple((*ac_matches, *structured_matches))
        vector_fragments = _unmatched_fragments_from_matches(
            question,
            raw_matches,
            ignored_spans=_retrieval_plan_vector_covered_spans(question_framing),
            question_framing=question_framing,
        )
        vector_recalls, vector_matches = self._vector_recall(
            vector_fragments,
            question=question,
            question_framing=question_framing,
            existing_matches=raw_matches,
        )
        unmatched_fragments = _unmatched_fragments_from_matches(
            question,
            raw_matches,
            question_framing=question_framing,
        )
        final_matches = tuple((*raw_matches, *vector_matches))
        final_resolution = self._overlap_resolver.resolve(final_matches)
        selected = final_resolution.selected
        candidate_groups = _candidate_groups(final_matches)
        mentions = _resolve_attribute_mentions_by_left_owner(
            tuple(_mention_from_match(match, candidate_groups) for match in selected)
        )
        context_signals, shape_signals = self._signals(question, mentions, question_framing=question_framing)
        return LexerTrace(
            question=question,
            matcher="ac",
            ac_matches=tuple(match.to_dict() for match in ac_matches),
            structured_matches=tuple(match.to_dict() for match in structured_matches),
            selected_hits=final_resolution.selected_to_dicts(),
            discarded_hits=final_resolution.discarded_to_dicts(),
            resolution_summary=final_resolution.summary(total_raw_hits=len(final_matches)),
            unmatched_fragments=unmatched_fragments,
            vector_recalls=tuple(vector_recalls),
            mentions=mentions,
            unmatched_spans=_unmatched_spans(len(question), mentions),
            context_signals=context_signals,
            shape_signals=shape_signals,
            question_framing=question_framing.to_dict() if question_framing is not None else None,
        )

    def _scan(self, question: str) -> tuple[_RawMatch, ...]:
        matches: list[_RawMatch] = []
        for start, surface, entry in self._automaton.scan(question):
            span_end = start + len(surface)
            if _is_partial_ascii_token_match(question, start, span_end, surface):
                continue
            metadata = dict(entry.metadata)
            if "via_synonym_group" in entry.metadata:
                metadata["via_synonym_group"] = entry.metadata["via_synonym_group"]
            matches.append(
                _RawMatch(
                    hit_id="",
                    canonical_id=entry.canonical_id,
                    mention_type=entry.mention_type,
                    surface=surface,
                    span_start=start,
                    span_end=span_end,
                    match_source="ac_exact",
                    metadata=metadata,
                    score=1.0,
                )
            )
        return _assign_hit_ids(
            tuple(sorted(matches, key=lambda item: (item.span_start, item.span_end, item.canonical_id))),
            prefix="ac",
        )

    def _structured_cue_extract(self, question: str) -> tuple[_RawMatch, ...]:
        matches: list[_RawMatch] = []
        for rule in self._structured_resources.operators:
            for surface in rule.surface_forms:
                for match in re.finditer(re.escape(surface), question):
                    start, end = match.span()
                    if _is_partial_ascii_token_match(question, start, end, surface):
                        continue
                    matches.append(
                        _RawMatch(
                            hit_id="",
                            canonical_id=rule.canonical_id,
                            mention_type="COMPARISON_OPERATOR",
                            surface=surface,
                            span_start=start,
                            span_end=end,
                            match_source="operator_extract",
                            metadata={
                                "cypher_op": rule.cypher_op,
                                "applies_to": list(rule.applies_to),
                                "arity": rule.arity,
                            },
                            score=1.0,
                        )
                    )
        for rule in self._structured_resources.quantifiers:
            for surface in rule.surface_forms:
                for match in re.finditer(re.escape(surface), question):
                    start, end = match.span()
                    matches.append(
                        _RawMatch(
                            hit_id="",
                            canonical_id=rule.canonical_id,
                            mention_type="QUANTIFIER",
                            surface=surface,
                            span_start=start,
                            span_end=end,
                            match_source="quantifier_extract",
                            metadata={
                                "semantic": rule.semantic,
                                "shape_effect": rule.shape_effect,
                                "affects_intent": rule.affects_intent,
                            },
                            score=1.0,
                        )
                    )
        ordered = tuple(sorted(matches, key=lambda item: (item.span_start, item.span_end, item.canonical_id)))
        return _assign_hit_ids(ordered, prefix="structured")

    def _literal_extract(
        self,
        question: str,
        fragments: tuple[dict[str, Any], ...],
    ) -> tuple[_RawMatch, ...]:
        matches: list[_RawMatch] = []
        for fragment in fragments:
            surface = str(fragment.get("surface") or "")
            span = fragment.get("span")
            if not surface or not isinstance(span, (list, tuple)) or len(span) != 2:
                continue
            fragment_start = int(span[0])
            for pattern in self._structured_resources.literal_patterns:
                for match in re.finditer(pattern.regex, surface, re.IGNORECASE):
                    start = fragment_start + match.start()
                    end = fragment_start + match.end()
                    raw = match.group(0)
                    if not raw.strip() or _is_partial_literal_token_match(question, start, end):
                        continue
                    matches.append(
                        _RawMatch(
                            hit_id="",
                            canonical_id=pattern.canonical_id,
                            mention_type=pattern.mention_type,
                            surface=raw,
                            span_start=start,
                            span_end=end,
                            match_source="time_extract" if pattern.mention_type == "TIME_EXPRESSION" else "literal_extract",
                            metadata={
                                "raw": raw,
                                "value_type_hint": pattern.value_type,
                            },
                            score=1.0,
                        )
                    )
        ordered = tuple(sorted(matches, key=lambda item: (item.span_start, item.span_end, item.canonical_id)))
        return _assign_hit_ids(ordered, prefix="literal")

    def _vector_recall(
        self,
        unmatched_fragments: tuple[dict[str, Any], ...],
        *,
        question: str,
        question_framing: QuestionFramingTrace | None = None,
        existing_matches: tuple[_RawMatch, ...] = (),
    ) -> tuple[list[dict[str, Any]], list[_RawMatch]]:
        recalls: list[dict[str, Any]] = []
        matches: list[_RawMatch] = []
        if self._vector_retriever is None:
            return recalls, matches
        recalls.extend(self._retrieval_plan_vector_recalls(question_framing))
        for unmatched_fragment in unmatched_fragments:
            fragment = str(unmatched_fragment["surface"])
            fragment_start, fragment_end = unmatched_fragment["span"]
            if len(fragment) < 2:
                continue
            if _is_generic_standalone_vector_fragment(fragment):
                continue
            if fragment in {"地址", "名称", "标准", "类型", "状态", "元素", "IP", "RFC"}:
                continue
            if _is_metric_functional_vector_fragment(
                fragment,
                fragment_start,
                fragment_end,
                question_framing=question_framing,
                existing_matches=existing_matches,
            ):
                continue
            if _is_attribute_possession_functional_fragment(
                fragment,
                fragment_start,
                fragment_end,
                question_framing=question_framing,
                existing_matches=existing_matches,
                question=question,
            ):
                continue
            if _is_generic_node_return_fragment(fragment):
                continue
            if _is_relation_path_structural_fragment(
                fragment,
                fragment_start,
                fragment_end,
                question_framing=question_framing,
            ):
                continue
            if _is_return_endpoint_modifier_fragment(
                fragment,
                fragment_start,
                fragment_end,
                question_framing=question_framing,
            ):
                continue
            if _is_return_content_filler_fragment(
                fragment,
                fragment_start,
                fragment_end,
                question_framing=question_framing,
                existing_matches=existing_matches,
            ):
                continue
            expected_type = unmatched_fragment.get("expected_mention_type")
            expected_type = normalize_expected_mention_type(str(expected_type)) if expected_type else None
            candidates = self._registered_vector_candidates(
                fragment,
                expected_mention_type=expected_type,
            )
            if not candidates:
                continue
            recalls.append(
                {
                    "fragment": fragment,
                    "span": [fragment_start, fragment_end],
                    "expected_mention_type": expected_type,
                    "provider": self._vector_retriever.provider,
                    "candidates": [
                        {
                            "candidate_id": candidate.id,
                            "canonical_id": candidate.canonical_id,
                            "mention_type": normalize_mention_type(candidate.mention_type),
                            "score": round(candidate.score, 6),
                            "matched_surface": candidate.surface,
                        }
                        for candidate in candidates
                    ],
                }
            )
            best_candidate = candidates[0]
            if best_candidate.score < self._vector_accept_threshold:
                continue
            best_entry = self.assets.by_id[best_candidate.canonical_id]
            matches.append(
                _RawMatch(
                    hit_id=f"vector-{len(matches) + 1}",
                    canonical_id=best_entry.canonical_id,
                    mention_type=best_entry.mention_type,
                    surface=fragment,
                    span_start=fragment_start,
                    span_end=fragment_end,
                    match_source="vector_recall",
                    metadata={
                        **best_entry.metadata,
                        **best_candidate.metadata,
                        "vector_candidate_id": best_candidate.id,
                        "vector_recalled_from": best_candidate.surface,
                        "vector_score": best_candidate.score,
                    },
                    score=best_candidate.score,
                )
            )
        return recalls, matches

    def _retrieval_plan_vector_recalls(
        self,
        question_framing: QuestionFramingTrace | None,
    ) -> list[dict[str, Any]]:
        recalls: list[dict[str, Any]] = []
        if question_framing is None:
            return recalls
        for path_query in _retrieval_plan_path_queries(question_framing):
            retrieval_text = str(path_query.get("retrieval_text") or "").strip()
            if len(retrieval_text) < 2:
                continue
            candidates = self._registered_vector_candidates(
                retrieval_text,
                expected_mention_type=None,
            )
            if not candidates:
                continue
            recalls.append(
                {
                    "fragment": retrieval_text,
                    "span": _retrieval_plan_query_span(path_query),
                    "expected_mention_type": None,
                    "provider": self._vector_retriever.provider,  # type: ignore[union-attr]
                    "source": "question_framing_retrieval_plan",
                    "query_id": str(path_query.get("query_id") or ""),
                    "candidates": [
                        {
                            "candidate_id": candidate.id,
                            "canonical_id": candidate.canonical_id,
                            "mention_type": normalize_mention_type(candidate.mention_type),
                            "score": round(candidate.score, 6),
                            "matched_surface": candidate.surface,
                        }
                        for candidate in candidates
                    ],
                }
            )
        return recalls

    def _registered_vector_candidates(
        self,
        fragment: str,
        *,
        expected_mention_type: str | None,
    ):
        candidates = self._vector_retriever.search(  # type: ignore[union-attr]
            fragment,
            expected_mention_type=expected_mention_type,
            top_k=self._vector_top_k,
        )
        registered: list[Any] = []
        for candidate in candidates:
            entry = self.assets.by_id.get(candidate.canonical_id)
            if entry is None:
                continue
            if normalize_mention_type(entry.mention_type) == "VALUE":
                continue
            if expected_mention_type and normalize_mention_type(entry.mention_type) != expected_mention_type:
                continue
            registered.append(candidate)
        return registered

    def _signals(
        self,
        question: str,
        mentions: tuple[Mention, ...],
        *,
        question_framing: QuestionFramingTrace | None = None,
    ) -> tuple[tuple[ContextSignal, ...], tuple[ContextSignal, ...]]:
        context: list[ContextSignal] = []
        shape: list[ContextSignal] = []
        next_id = 1
        next_id = _append_question_framing_signals(question_framing, context, next_id)
        attribute_owner_pairs: list[tuple[Mention, Mention]] = []
        predicate_attribute_keys = _predicate_attribute_keys(question, mentions)
        for mention in mentions:
            if mention.canonical_id == "OP_RETURN_FIELD":
                shape.append(
                    ContextSignal(
                        signal_id=f"S{next_id}",
                        signal_type="SHAPE_SIGNAL",
                        text=mention.surface,
                        span_start=mention.span_start,
                        span_end=mention.span_end,
                        supports=("answer_projection_region", "project_marker"),
                        strength=1.0,
                    )
                )
                next_id += 1
            if mention.canonical_id == "OP_DETAIL":
                shape.append(
                    ContextSignal(
                        signal_id=f"S{next_id}",
                        signal_type="SHAPE_SIGNAL",
                        text=mention.surface,
                        span_start=mention.span_start,
                        span_end=mention.span_end,
                        supports=("entity_detail_hint", "node_return_hint"),
                        strength=1.0,
                    )
                )
                next_id += 1
            if mention.mention_type == "VALUE":
                target = _nearest_right_object(mention, mentions)
                if target is not None:
                    context.append(
                        ContextSignal(
                            signal_id=f"S{next_id}",
                            signal_type="PROXIMAL_MODIFIER",
                            text=question[mention.span_start : target.span_end],
                            span_start=mention.span_start,
                            span_end=target.span_end,
                            supports=(mention.canonical_id, target.canonical_id),
                            strength=0.95,
                        )
                    )
                    next_id += 1
            if mention.mention_type == "QUANTIFIER":
                target = _nearest_right_object(mention, mentions)
                span_end = target.span_end if target is not None else mention.span_end
                supports = _quantifier_supports(mention)
                context.append(
                    ContextSignal(
                        signal_id=f"S{next_id}",
                        signal_type="QUANTIFIER_BINDING",
                        text=question[mention.span_start : span_end],
                        span_start=mention.span_start,
                        span_end=span_end,
                        supports=supports,
                        strength=1.0,
                    )
                )
                next_id += 1
                shape.append(
                    ContextSignal(
                        signal_id=f"S{next_id}",
                        signal_type="SHAPE_SIGNAL",
                        text=mention.surface,
                        span_start=mention.span_start,
                        span_end=mention.span_end,
                        supports=supports,
                        strength=1.0,
                    )
                )
                next_id += 1
            if mention.mention_type == "ATTRIBUTE":
                if _mention_key(mention) not in predicate_attribute_keys and not _is_filter_only_framing_attribute(
                    mention,
                    question_framing,
                ):
                    shape.append(
                        ContextSignal(
                            signal_id=f"S{next_id}",
                            signal_type="SHAPE_SIGNAL",
                            text=mention.surface,
                            span_start=mention.span_start,
                            span_end=mention.span_end,
                            supports=("answer_projection_region",),
                            strength=0.85,
                        )
                    )
                    next_id += 1
                target = _nearest_left_owner(mention, mentions)
                if target is not None:
                    attribute_owner_pairs.append((mention, target))
        next_id = _append_predicate_group_signals(question, mentions, context, next_id)
        for owner, attributes in _attribute_groups_by_owner(attribute_owner_pairs):
            context.append(
                ContextSignal(
                    signal_id=f"S{next_id}",
                    signal_type="PROXIMAL_MODIFIER",
                    text=question[owner.span_start : max(item.span_end for item in attributes)],
                    span_start=owner.span_start,
                    span_end=max(item.span_end for item in attributes),
                    supports=tuple(item.canonical_id for item in attributes) + (owner.canonical_id,),
                    strength=0.9,
                )
            )
            next_id += 1
        next_id = _append_quantifier_scope_signals(mentions, context, next_id)
        if any(item.canonical_id == "OP_RETURN_FIELD" for item in mentions):
            context.append(
                ContextSignal(
                    signal_id=f"S{next_id}",
                    signal_type="OPERATION_CUE",
                    text="返回",
                    span_start=question.find("返回") if "返回" in question else 0,
                    span_end=(question.find("返回") + 2) if "返回" in question else 0,
                    supports=("project_marker",),
                    strength=1.0,
                )
            )
            next_id += 1
        next_id = _append_question_shape_signals(question, shape, next_id)
        return tuple(context), tuple(shape)


def _assign_hit_ids(matches: tuple[_RawMatch, ...], *, prefix: str) -> tuple[_RawMatch, ...]:
    return tuple(replace(match, hit_id=f"{prefix}-{index}") for index, match in enumerate(matches, start=1))


def _filter_role_incompatible_ac_matches(
    matches: tuple[_RawMatch, ...],
    question_framing: QuestionFramingTrace | None,
) -> tuple[_RawMatch, ...]:
    if question_framing is None:
        return matches
    filtered: list[_RawMatch] = []
    for match in matches:
        if (
            normalize_mention_type(match.mention_type) in {"OBJECT", "ATTRIBUTE"}
            and _is_relation_path_structural_fragment(
                match.surface,
                match.span_start,
                match.span_end,
                question_framing=question_framing,
            )
        ):
            continue
        filtered.append(match)
    return _assign_hit_ids(tuple(filtered), prefix="ac")


def _unmatched_spans(
    question_length: int,
    mentions: tuple[Mention, ...],
    *,
    ignored_spans: tuple[tuple[int, int], ...] = (),
) -> tuple[tuple[int, int], ...]:
    return _unmatched_spans_from_ranges(
        question_length,
        tuple((mention.span_start, mention.span_end) for mention in mentions) + ignored_spans,
    )


def _unmatched_spans_from_ranges(
    question_length: int,
    ranges: tuple[tuple[int, int], ...],
) -> tuple[tuple[int, int], ...]:
    spans: list[tuple[int, int]] = []
    cursor = 0
    for start, end in sorted(ranges, key=lambda item: (item[0], item[1])):
        if end <= cursor:
            continue
        if start > cursor:
            spans.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < question_length:
        spans.append((cursor, question_length))
    return tuple(spans)


def _unmatched_fragments_from_matches(
    question: str,
    matches: tuple[_RawMatch, ...],
    *,
    ignored_spans: tuple[tuple[int, int], ...] = (),
    question_framing: QuestionFramingTrace | None = None,
) -> tuple[dict[str, Any], ...]:
    fragments: list[dict[str, Any]] = []
    coverage_spans = tuple((match.span_start, match.span_end) for match in matches) + ignored_spans
    for start, end in _unmatched_spans_from_ranges(len(question), coverage_spans):
        fragment, fragment_start, fragment_end = _trim_fragment(question, start, end)
        if not fragment:
            continue
        fragments.append(
            {
                "surface": fragment,
                "span": [fragment_start, fragment_end],
                "expected_mention_type": _expected_mention_type(
                    question,
                    fragment_start,
                    fragment_end,
                    question_framing=question_framing,
                ),
            }
        )
    return tuple(fragments)


def _retrieval_plan_path_queries(question_framing: QuestionFramingTrace | None) -> tuple[dict[str, Any], ...]:
    if question_framing is None:
        return ()
    retrieval_plan = getattr(question_framing, "retrieval_plan", None)
    if not isinstance(retrieval_plan, dict):
        return ()
    raw_queries = retrieval_plan.get("path_queries")
    if not isinstance(raw_queries, list):
        return ()
    return tuple(item for item in raw_queries if isinstance(item, dict))


def _retrieval_plan_vector_covered_spans(question_framing: QuestionFramingTrace | None) -> tuple[tuple[int, int], ...]:
    spans: list[tuple[int, int]] = []
    for path_query in _retrieval_plan_path_queries(question_framing):
        raw_spans = path_query.get("grounding_spans")
        if not isinstance(raw_spans, list):
            continue
        for raw_span in raw_spans:
            span = _coerce_span(raw_span)
            if span is not None:
                spans.append(span)
    return tuple(spans)


def _retrieval_plan_query_span(path_query: dict[str, Any]) -> list[int] | None:
    raw_spans = path_query.get("grounding_spans")
    if not isinstance(raw_spans, list):
        return None
    spans = [span for span in (_coerce_span(raw_span) for raw_span in raw_spans) if span is not None]
    if not spans:
        return None
    return [min(start for start, _ in spans), max(end for _, end in spans)]


def _coerce_span(raw_span: Any) -> tuple[int, int] | None:
    if not isinstance(raw_span, (list, tuple)) or len(raw_span) != 2:
        return None
    try:
        start = int(raw_span[0])
        end = int(raw_span[1])
    except (TypeError, ValueError):
        return None
    if start < 0 or end <= start:
        return None
    return (start, end)


def _is_generic_standalone_vector_fragment(fragment: str) -> bool:
    compact = re.sub(r"\s+", "", fragment)
    return compact in GENERIC_STANDALONE_VECTOR_FRAGMENTS


def _append_question_framing_signals(
    question_framing: QuestionFramingTrace | None,
    context: list[ContextSignal],
    next_id: int,
) -> int:
    if question_framing is None:
        return next_id
    for atom in question_framing.atoms:
        if atom.span is None:
            continue
        context.append(
            ContextSignal(
                signal_id=f"S{next_id}",
                signal_type="QUESTION_FRAMING_ATOM",
                text=atom.text,
                span_start=atom.span[0],
                span_end=atom.span[1],
                supports=tuple(
                    dict.fromkeys(
                        ("question_framing", atom.atom_id, *(role.value for role in atom.roles))
                    )
                ),
                strength=atom.confidence,
            )
        )
        next_id += 1
    return next_id


def _is_filter_only_framing_attribute(
    mention: Mention,
    question_framing: QuestionFramingTrace | None,
) -> bool:
    if question_framing is None:
        return False
    roles = set(question_framing.roles_for_span(mention.span_start, mention.span_end))
    return QuestionFramingRole.FILTER_CONDITION in roles and QuestionFramingRole.RETURN_CONTENT not in roles


def _nearest_right_object(mention: Mention, mentions: tuple[Mention, ...]) -> Mention | None:
    candidates = [item for item in mentions if item.mention_type == "OBJECT" and item.span_start >= mention.span_end]
    return min(candidates, key=lambda item: item.span_start, default=None)


def _nearest_left_owner(mention: Mention, mentions: tuple[Mention, ...]) -> Mention | None:
    left_mentions = [item for item in mentions if item.span_end <= mention.span_start and item.mention_type in {"OBJECT", "RELATION"}]
    return max(left_mentions, key=lambda item: item.span_end, default=None)


def _attribute_groups_by_owner(
    pairs: list[tuple[Mention, Mention]],
) -> tuple[tuple[Mention, tuple[Mention, ...]], ...]:
    groups: list[tuple[Mention, list[Mention]]] = []
    for attribute, owner in pairs:
        for existing_owner, attributes in groups:
            if existing_owner == owner:
                attributes.append(attribute)
                break
        else:
            groups.append((owner, [attribute]))
    return tuple((owner, tuple(attributes)) for owner, attributes in groups)


def _append_quantifier_scope_signals(
    mentions: tuple[Mention, ...],
    context: list[ContextSignal],
    next_id: int,
) -> int:
    seen_supports = {signal.supports for signal in context}
    supports = ("all_scope", "no_filter")
    for mention in mentions:
        if mention.canonical_id != "QUANT_ALL" or supports in seen_supports:
            continue
        context.append(
            ContextSignal(
                signal_id=f"S{next_id}",
                signal_type="NO_FILTER_CONDITION",
                text=mention.surface,
                span_start=mention.span_start,
                span_end=mention.span_end,
                supports=supports,
                strength=1.0,
            )
        )
        seen_supports.add(supports)
        next_id += 1
    return next_id


def _append_question_shape_signals(question: str, shape: list[ContextSignal], next_id: int) -> int:
    seen_supports = {signal.supports for signal in shape}
    for supports, terms in SHAPE_SIGNAL_SPECS:
        if supports in seen_supports:
            continue
        match = _first_term_match(question, terms)
        if match is None:
            continue
        text, start, end = match
        shape.append(
            ContextSignal(
                signal_id=f"S{next_id}",
                signal_type="SHAPE_SIGNAL",
                text=text,
                span_start=start,
                span_end=end,
                supports=supports,
                strength=1.0,
            )
        )
        seen_supports.add(supports)
        next_id += 1
    if ("node_return_hint",) not in seen_supports and not any("node_return_hint" in supports for supports in seen_supports):
        node_match = _terminal_node_return_match(question)
        if node_match is not None:
            text, start, end = node_match
            shape.append(
                ContextSignal(
                    signal_id=f"S{next_id}",
                    signal_type="SHAPE_SIGNAL",
                    text=text,
                    span_start=start,
                    span_end=end,
                    supports=("node_return_hint",),
                    strength=1.0,
                )
            )
            next_id += 1
    if ("limit_hint",) not in seen_supports:
        limit_match = re.search(r"前\s*\d+\s*(?:条|个)?|top\s*\d+", question, re.IGNORECASE)
        if limit_match is not None:
            shape.append(
                ContextSignal(
                    signal_id=f"S{next_id}",
                    signal_type="SHAPE_SIGNAL",
                    text=limit_match.group(0),
                    span_start=limit_match.start(),
                    span_end=limit_match.end(),
                    supports=("limit_hint",),
                    strength=1.0,
                )
            )
            next_id += 1
    return next_id


def _terminal_node_return_match(question: str) -> tuple[str, int, int] | None:
    match = re.search(r"节点(?=[。？！?!，,\s]*$)", question)
    if match is None:
        return None
    return match.group(0), match.start(), match.end()


def _append_predicate_group_signals(
    question: str,
    mentions: tuple[Mention, ...],
    context: list[ContextSignal],
    next_id: int,
) -> int:
    for attribute, operator, value in _predicate_groups(question, mentions):
        context.append(
            ContextSignal(
                signal_id=f"S{next_id}",
                signal_type="PREDICATE_GROUP",
                text=question[attribute.span_start : value.span_end],
                span_start=attribute.span_start,
                span_end=value.span_end,
                supports=tuple(
                    dict.fromkeys(
                        (
                            *_attribute_supports(attribute),
                            operator.canonical_id,
                            value.surface,
                            value.canonical_id,
                        )
                    )
                ),
                strength=1.0,
            )
        )
        next_id += 1
    return next_id


def _predicate_attribute_keys(question: str, mentions: tuple[Mention, ...]) -> set[tuple[int, int, str]]:
    return {_mention_key(attribute) for attribute, _, _ in _predicate_groups(question, mentions)}


def _predicate_groups(question: str, mentions: tuple[Mention, ...]) -> tuple[tuple[Mention, Mention, Mention], ...]:
    attributes = [item for item in mentions if item.mention_type == "ATTRIBUTE"]
    operators = [item for item in mentions if item.mention_type == "COMPARISON_OPERATOR"]
    values = [item for item in mentions if item.mention_type in {"VALUE", "LITERAL_VALUE", "TIME_EXPRESSION"}]
    groups: list[tuple[Mention, Mention, Mention]] = []
    for attribute in attributes:
        operator = min(
            (
                item
                for item in operators
                if item.span_start >= attribute.span_end
                and _only_predicate_glue(question[attribute.span_end : item.span_start])
            ),
            key=lambda item: item.span_start,
            default=None,
        )
        if operator is None:
            continue
        value = min(
            (
                item
                for item in values
                if item.span_start >= operator.span_end
                and _only_predicate_glue(question[operator.span_end : item.span_start])
            ),
            key=lambda item: item.span_start,
            default=None,
        )
        if value is not None:
            groups.append((attribute, operator, value))
    return tuple(groups)


def _mention_key(mention: Mention) -> tuple[int, int, str]:
    return (mention.span_start, mention.span_end, mention.canonical_id)


def _only_predicate_glue(text: str) -> bool:
    return not text or bool(re.fullmatch(r"[\s的为是:：,，]*", text))


def _attribute_supports(mention: Mention) -> tuple[str, ...]:
    refs = mention.metadata.get("candidate_refs")
    values: list[str] = [mention.canonical_id]
    if isinstance(refs, (list, tuple)):
        values.extend(str(ref) for ref in refs)
    return tuple(dict.fromkeys(values))


def _quantifier_supports(mention: Mention) -> tuple[str, ...]:
    semantic = str(mention.metadata.get("semantic") or "")
    shape_effect = str(mention.metadata.get("shape_effect") or "")
    supports = ["quantifier", mention.canonical_id]
    if semantic:
        supports.append(semantic)
    if shape_effect:
        supports.append(shape_effect)
    if mention.metadata.get("affects_intent"):
        supports.append("affects_intent")
    return tuple(supports)


def _load_structured_extraction_resources() -> _StructuredExtractionResources:
    operators_payload = _load_yaml_mapping(resource_paths.lexer_operators_path())
    quantifiers_payload = _load_yaml_mapping(resource_paths.lexer_quantifiers_path())
    literal_payload = _load_yaml_mapping(resource_paths.lexer_literal_patterns_path())
    operators: list[_StructuredOperatorRule] = []
    for item in operators_payload.get("operators", []) or []:
        if not isinstance(item, dict):
            continue
        surface_forms = tuple(str(value) for value in item.get("surface_forms", ()) if str(value))
        canonical_id = str(item.get("canonical_id") or "")
        cypher_op = str(item.get("cypher_op") or "")
        if not canonical_id or not surface_forms or not cypher_op:
            continue
        operators.append(
            _StructuredOperatorRule(
                canonical_id=canonical_id,
                surface_forms=surface_forms,
                cypher_op=cypher_op,
                applies_to=tuple(str(value) for value in item.get("applies_to", ()) if str(value)),
                arity=int(item.get("arity") or 1),
            )
        )
    quantifiers: list[_StructuredQuantifierRule] = []
    for item in quantifiers_payload.get("quantifiers", []) or []:
        if not isinstance(item, dict):
            continue
        surface_forms = tuple(str(value) for value in item.get("surface_forms", ()) if str(value))
        canonical_id = str(item.get("canonical_id") or "")
        if not canonical_id or not surface_forms:
            continue
        quantifiers.append(
            _StructuredQuantifierRule(
                canonical_id=canonical_id,
                surface_forms=surface_forms,
                semantic=str(item.get("semantic") or ""),
                shape_effect=str(item.get("shape_effect") or ""),
                affects_intent=bool(item.get("affects_intent", False)),
            )
        )
    literal_patterns: list[_StructuredLiteralPattern] = []
    for item in literal_payload.get("patterns", []) or []:
        if not isinstance(item, dict):
            continue
        canonical_id = str(item.get("canonical_id") or "")
        regex = str(item.get("regex") or "")
        if not canonical_id or not regex:
            continue
        literal_patterns.append(
            _StructuredLiteralPattern(
                canonical_id=canonical_id,
                mention_type=normalize_mention_type(str(item.get("mention_type") or "LITERAL_VALUE")),
                value_type=str(item.get("value_type") or ""),
                regex=regex,
            )
        )
    return _StructuredExtractionResources(
        operators=tuple(operators),
        quantifiers=tuple(quantifiers),
        literal_patterns=tuple(literal_patterns),
    )


def _load_yaml_mapping(path: Any) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {}


def _first_term_match(question: str, terms: tuple[str, ...]) -> tuple[str, int, int] | None:
    matches = [(start, term) for term in terms if (start := question.find(term)) >= 0]
    if not matches:
        return None
    start, term = min(matches, key=lambda item: item[0])
    return term, start, start + len(term)


class _AutomatonNode:
    def __init__(self) -> None:
        self.children: dict[str, "_AutomatonNode"] = {}
        self.fail: "_AutomatonNode | None" = None
        self.entries: list[tuple[str, Any]] = []


class _SurfaceAutomaton:
    def __init__(self) -> None:
        self.root = _AutomatonNode()
        self.root.fail = self.root

    @classmethod
    def from_entries(cls, entries: tuple[Any, ...]) -> "_SurfaceAutomaton":
        automaton = cls()
        entries_by_id = {entry.canonical_id: entry for entry in entries}
        for entry in entries:
            for surface in entry.surface_forms:
                if not surface:
                    continue
                for indexed_entry in _normalized_index_entries(entry, entries_by_id):
                    node = automaton.root
                    for char in surface:
                        node = node.children.setdefault(char, _AutomatonNode())
                    node.entries.append((surface, indexed_entry))
        automaton._build_failure_links()
        return automaton

    def _build_failure_links(self) -> None:
        queue: deque[_AutomatonNode] = deque()
        for child in self.root.children.values():
            child.fail = self.root
            queue.append(child)

        while queue:
            node = queue.popleft()
            for char, child in node.children.items():
                fallback = node.fail
                while fallback is not self.root and fallback is not None and char not in fallback.children:
                    fallback = fallback.fail
                if fallback is not None and char in fallback.children and fallback.children[char] is not child:
                    child.fail = fallback.children[char]
                else:
                    child.fail = self.root
                child.entries.extend(child.fail.entries if child.fail is not None else ())
                queue.append(child)

    def scan(self, text: str) -> list[tuple[int, str, Any]]:
        matches: list[tuple[int, str, Any]] = []
        node = self.root
        for index, char in enumerate(text):
            while node is not self.root and char not in node.children:
                node = node.fail if node.fail is not None else self.root
            node = node.children.get(char, self.root)
            for surface, entry in node.entries:
                start = index - len(surface) + 1
                if start >= 0:
                    matches.append((start, surface, entry))
        return matches


def _trim_fragment(question: str, start: int, end: int) -> tuple[str, int, int]:
    while start < end and question[start] in "，,。！？；:： 的其和与及上所":
        start += 1
    while end > start and question[end - 1] in "，,。！？；:： 的其和与及上所":
        end -= 1
    return question[start:end], start, end


def _mention_from_match(
    match: _RawMatch,
    candidate_groups: dict[tuple[int, int, str, str], tuple[dict[str, Any], ...]],
) -> Mention:
    mention = match.to_mention()
    candidates = candidate_groups.get(_candidate_group_key(match), ())
    if len(candidates) <= 1:
        return mention
    return replace(
        mention,
        metadata={
            **mention.metadata,
            "candidate_refs": [candidate["canonical_id"] for candidate in candidates],
            "candidates": list(candidates),
            "via_synonym_groups": sorted(
                {
                    group
                    for candidate in candidates
                    for group in candidate.get("via_synonym_groups", [])
                    if isinstance(group, str)
                }
            ),
        },
    )


def _resolve_attribute_mentions_by_left_owner(mentions: tuple[Mention, ...]) -> tuple[Mention, ...]:
    resolved: list[Mention] = []
    for mention in mentions:
        if mention.mention_type != "ATTRIBUTE":
            resolved.append(mention)
            continue
        owner = _nearest_left_owner(mention, tuple(resolved))
        candidate = _candidate_for_owner(mention, owner)
        if candidate is None:
            resolved.append(mention)
            continue
        merged_metadata = {
            **dict(candidate.get("metadata") or {}),
            "candidate_refs": list(mention.metadata.get("candidate_refs", ())),
            "candidates": list(mention.metadata.get("candidates", ())),
            "via_synonym_groups": list(mention.metadata.get("via_synonym_groups", ())),
        }
        resolved.append(
            replace(
                mention,
                canonical_id=str(candidate["canonical_id"]),
                metadata=merged_metadata,
            )
        )
    return tuple(resolved)


def _candidate_for_owner(mention: Mention, owner: Mention | None) -> dict[str, Any] | None:
    if owner is None:
        return None
    candidates = mention.metadata.get("candidates")
    if not isinstance(candidates, list):
        return None
    owner_refs = {owner.canonical_id}
    owner_candidate_refs = owner.metadata.get("candidate_refs")
    if isinstance(owner_candidate_refs, list):
        owner_refs.update(str(item) for item in owner_candidate_refs)
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        metadata = candidate.get("metadata")
        parent = metadata.get("parent_object") if isinstance(metadata, dict) else None
        canonical_id = str(candidate.get("canonical_id") or "")
        if parent in owner_refs or any(canonical_id.startswith(f"{owner_ref}.") for owner_ref in owner_refs):
            return candidate
    return None


def _candidate_groups(matches: tuple[_RawMatch, ...]) -> dict[tuple[int, int, str, str], tuple[dict[str, Any], ...]]:
    grouped: dict[tuple[int, int, str, str], dict[str, dict[str, Any]]] = {}
    for match in matches:
        key = _candidate_group_key(match)
        grouped.setdefault(key, {})
        existing = grouped[key].setdefault(
            match.canonical_id,
            {
                "canonical_id": match.canonical_id,
                "mention_type": normalize_mention_type(match.mention_type),
                "metadata": dict(match.metadata),
                "via_synonym_groups": [],
            },
        )
        synonym_group = match.metadata.get("via_synonym_group")
        if isinstance(synonym_group, str) and synonym_group not in existing["via_synonym_groups"]:
            existing["via_synonym_groups"].append(synonym_group)
    return {
        key: tuple(sorted(values.values(), key=lambda item: item["canonical_id"]))
        for key, values in grouped.items()
        if len(values) > 1
    }


def _candidate_group_key(match: _RawMatch) -> tuple[int, int, str, str]:
    return (
        match.span_start,
        match.span_end,
        match.surface,
        normalize_mention_type(match.mention_type),
    )


def _normalized_index_entries(
    entry: DictionaryEntry,
    entries_by_id: dict[str, DictionaryEntry],
) -> tuple[DictionaryEntry, ...]:
    if entry.mention_type == "SYNONYM":
        return ()
    if entry.mention_type != "SYNONYM_GROUP":
        return (entry,)

    normalized: list[DictionaryEntry] = []
    applied_to = entry.metadata.get("applied_to", ())
    targets = applied_to if isinstance(applied_to, (list, tuple)) else ()
    for target_id in targets:
        target = entries_by_id.get(str(target_id))
        if target is None:
            continue
        normalized.append(
            replace(
                target,
                metadata={
                    **target.metadata,
                    "via_synonym_group": entry.canonical_id,
                },
            )
        )
    return tuple(normalized)


def _expected_mention_type(
    question: str,
    start: int,
    end: int,
    *,
    question_framing: QuestionFramingTrace | None = None,
) -> str | None:
    framing_expected_type = _expected_mention_type_from_question_framing(question_framing, start, end)
    if framing_expected_type is not None:
        return framing_expected_type
    fragment = question[start:end]
    if re.search(r"(越|过|经|用|连接|关联|拥有|下挂)", fragment):
        return "RELATION"
    if re.search(r"(数量|总数|统计|返回|查询)", fragment):
        return "OPERATION"
    if start > 0 and question[start - 1] == "的":
        return "ATTRIBUTE"
    return None


def _expected_mention_type_from_question_framing(
    question_framing: QuestionFramingTrace | None,
    start: int,
    end: int,
) -> str | None:
    if question_framing is None:
        return None
    roles = set(question_framing.roles_for_span(start, end))
    if QuestionFramingRole.RELATION_PATH in roles:
        return "RELATION"
    if QuestionFramingRole.RETURN_CONTENT in roles:
        atoms = _question_framing_atoms_for_span(question_framing, start, end)
        if any(_is_explicit_attribute_return_atom(atom.text) for atom in atoms):
            return "ATTRIBUTE"
        if any(_is_generic_node_return_atom(atom.text) for atom in atoms):
            return None
        return "ATTRIBUTE"
    if QuestionFramingRole.FIND_OBJECT in roles and QuestionFramingRole.FILTER_CONDITION not in roles:
        atoms = _question_framing_atoms_for_span(question_framing, start, end)
        if any(
            atom.span == (start, end)
            and QuestionFramingRole.FIND_OBJECT in atom.roles
            and QuestionFramingRole.FILTER_CONDITION not in atom.roles
            for atom in atoms
        ):
            return "OBJECT"
    if QuestionFramingRole.AGG_SORT_TIME in roles:
        return "OPERATION"
    return None


def _question_framing_atoms_for_span(
    question_framing: QuestionFramingTrace,
    start: int,
    end: int,
) -> tuple[Any, ...]:
    return tuple(atom for atom in question_framing.atoms if atom.overlaps(start, end))


def _is_explicit_attribute_return_atom(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return False
    explicit_terms = (
        "ID",
        "编号",
        "标识",
        "名称",
        "状态",
        "管理状态",
        "带宽",
        "延迟",
        "时延",
        "类型",
        "元素类型",
        "服务类型",
        "业务类型",
        "厂商",
        "软件版本",
        "版本",
        "位置",
        "速率",
        "MAC",
        "物理地址",
        "IP地址",
        "地址",
        "QoS",
        "服务质量",
        "标准",
        "长度",
    )
    return any(term in compact for term in explicit_terms)


def _is_generic_node_return_atom(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return False
    generic_terms = ("信息", "详情", "详细信息", "完整信息", "节点", "节点信息", "对象信息", "服务信息", "业务信息")
    return any(term in compact for term in generic_terms) and not _is_explicit_attribute_return_atom(compact)


def _is_generic_node_return_fragment(fragment: str) -> bool:
    compact = re.sub(r"\s+", "", fragment)
    return compact in {"信息", "详情", "详细信息", "完整信息", "节点", "节点信息", "对象信息", "服务信息", "业务信息"}


def _is_metric_functional_vector_fragment(
    fragment: str,
    start: int,
    end: int,
    *,
    question_framing: QuestionFramingTrace | None,
    existing_matches: tuple[_RawMatch, ...],
) -> bool:
    compact = re.sub(r"\s+", "", fragment)
    if not compact:
        return False
    functional_terms = {
        "属性",
        "字段",
        "记录",
        "数量",
        "总数量",
        "总数",
        "属性记录",
        "属性非空",
        "属性非空记录",
        "属性非空的记录",
        "记录数量",
    }
    if compact not in functional_terms and not re.fullmatch(r"(?:属性|字段)?非空(?:的)?记录", compact):
        return False
    if compact in {"数量", "总数量", "总数", "记录数量"}:
        return True
    if question_framing is not None:
        roles = set(question_framing.roles_for_span(start, end))
        if roles.intersection(
            {
                QuestionFramingRole.RETURN_CONTENT,
                QuestionFramingRole.AGG_SORT_TIME,
                QuestionFramingRole.FILTER_CONDITION,
                QuestionFramingRole.RELATION_PATH,
            }
        ):
            return True
    return any(
        normalize_mention_type(match.mention_type) == "ATTRIBUTE"
        and (0 <= start - match.span_end <= 4 or 0 <= match.span_start - end <= 4)
        for match in existing_matches
    )


def _is_attribute_possession_functional_fragment(
    fragment: str,
    start: int,
    end: int,
    *,
    question_framing: QuestionFramingTrace | None,
    existing_matches: tuple[_RawMatch, ...],
    question: str,
) -> bool:
    compact = re.sub(r"\s+", "", fragment)
    if compact not in {"拥有", "中拥有", "具有", "中具有", "带有", "中带有", "具备", "中具备"}:
        return False
    next_attributes = [
        match
        for match in existing_matches
        if normalize_mention_type(match.mention_type) == "ATTRIBUTE" and 0 <= match.span_start - end <= 2
    ]
    if not next_attributes:
        return False
    local_window = question[start : min(len(question), max(match.span_end for match in next_attributes) + 4)]
    if "属性" not in local_window and "字段" not in local_window:
        return False
    if question_framing is None:
        return True
    roles = set(question_framing.roles_for_span(start, end))
    return bool(
        roles.intersection(
            {
                QuestionFramingRole.FILTER_CONDITION,
                QuestionFramingRole.RETURN_CONTENT,
                QuestionFramingRole.AGG_SORT_TIME,
                QuestionFramingRole.RELATION_PATH,
            }
        )
    )


def _is_relation_path_structural_fragment(
    fragment: str,
    start: int,
    end: int,
    *,
    question_framing: QuestionFramingTrace | None,
) -> bool:
    if question_framing is None:
        return False
    compact = re.sub(r"\s+", "", fragment)
    if compact not in {"连接", "关系", "关联", "之间", "连接关系", "关联关系"}:
        return False
    roles = set(question_framing.roles_for_span(start, end))
    return QuestionFramingRole.RELATION_PATH in roles


def _is_return_endpoint_modifier_fragment(
    fragment: str,
    start: int,
    end: int,
    *,
    question_framing: QuestionFramingTrace | None,
) -> bool:
    if question_framing is None:
        return False
    compact = re.sub(r"\s+", "", fragment)
    if not compact:
        return False
    if not any(compact.startswith(prefix) for prefix in ("双方", "两端", "两侧", "两者", "二者")):
        return False
    if not any(compact.endswith(suffix) for suffix in ("元素", "对象", "实体", "节点")):
        return False
    return any(
        atom.contains(start, end)
        and QuestionFramingRole.RETURN_CONTENT in atom.roles
        and _is_explicit_attribute_return_atom(atom.text)
        for atom in question_framing.atoms
    )


def _is_return_content_filler_fragment(
    fragment: str,
    start: int,
    end: int,
    *,
    question_framing: QuestionFramingTrace | None,
    existing_matches: tuple[_RawMatch, ...],
) -> bool:
    if question_framing is None:
        return False
    if _is_explicit_attribute_return_atom(fragment):
        return False
    containing_atoms = [
        atom
        for atom in question_framing.atoms
        if atom.contains(start, end) and QuestionFramingRole.RETURN_CONTENT in atom.roles
    ]
    if not containing_atoms:
        return False
    for atom in containing_atoms:
        attribute_matches = [
            match
            for match in existing_matches
            if normalize_mention_type(match.mention_type) == "ATTRIBUTE" and atom.contains(match.span_start, match.span_end)
        ]
        has_left_attribute = any(match.span_end <= start for match in attribute_matches)
        has_right_attribute = any(match.span_start >= end for match in attribute_matches)
        if has_left_attribute and has_right_attribute:
            return True
    return False


def _is_partial_ascii_token_match(question: str, start: int, end: int, surface: str) -> bool:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", surface):
        return False
    if start > 0 and re.match(r"[A-Za-z0-9_]", question[start - 1]):
        return True
    if end < len(question) and re.match(r"[A-Za-z0-9_]", question[end]):
        return True
    return False


def _is_partial_literal_token_match(question: str, start: int, end: int) -> bool:
    if start > 0 and re.match(r"[A-Za-z0-9_]", question[start - 1]):
        return True
    if end < len(question) and re.match(r"[A-Za-z0-9_]", question[end]):
        return True
    return False
