from __future__ import annotations

from dataclasses import dataclass, replace
from collections import deque
import os
import re
from typing import Any

import yaml

from .mention_vector_recall import MentionVectorRetriever, RagMentionVectorRetriever
from .overlap_resolver import DictionaryPriorities, OverlapResolver
from services.cypher_generator_agent.app.infrastructure import resource_paths
from services.cypher_generator_agent.app.ontology_layer.assets import OntologyAssets
from services.cypher_generator_agent.app.ontology_layer.models import ContextSignal, DictionaryEntry, LexerTrace, Mention


TYPE_NORMALIZATION = {
    "business_object": "OBJECT",
    "attribute": "ATTRIBUTE",
    "attribute_value": "VALUE",
    "relation_predicate": "RELATION",
    "operation_intent": "OPERATION",
}

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

@dataclass(frozen=True)
class _ScopeFilterSignalRule:
    signal_type: str
    supports: tuple[str, ...]
    surface_forms: tuple[str, ...]


@dataclass(frozen=True)
class _LexicalSignalRules:
    scope_filter_signals: tuple[_ScopeFilterSignalRule, ...]


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
            mention_type=TYPE_NORMALIZATION.get(self.mention_type, self.mention_type),
            surface=self.surface,
            span_start=self.span_start,
            span_end=self.span_end,
            metadata=dict(self.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "mention_type": TYPE_NORMALIZATION.get(self.mention_type, self.mention_type),
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
        self._overlap_resolver = OverlapResolver(DictionaryPriorities.from_default_resources())
        self._signal_rules = _load_lexical_signal_rules()
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

    def run(self, question: str) -> LexerTrace:
        ac_matches = self._scan(question)
        structured_matches = self._structured_extract(question)
        raw_matches = tuple((*ac_matches, *structured_matches))
        scope_filter_signal_spans = _scope_filter_signal_spans(question, self._signal_rules.scope_filter_signals)
        unmatched_fragments = _unmatched_fragments_from_matches(
            question,
            raw_matches,
            ignored_spans=scope_filter_signal_spans,
        )
        vector_recalls, vector_matches = self._vector_recall(unmatched_fragments)
        final_matches = tuple((*raw_matches, *vector_matches))
        final_resolution = self._overlap_resolver.resolve(final_matches)
        selected = final_resolution.selected
        candidate_groups = _candidate_groups(final_matches)
        mentions = tuple(_mention_from_match(match, candidate_groups) for match in selected)
        context_signals, shape_signals = self._signals(question, mentions)
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
            unmatched_spans=_unmatched_spans(len(question), mentions, ignored_spans=scope_filter_signal_spans),
            context_signals=context_signals,
            shape_signals=shape_signals,
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

    def _structured_extract(self, question: str) -> tuple[_RawMatch, ...]:
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
        for pattern in self._structured_resources.literal_patterns:
            for match in re.finditer(pattern.regex, question, re.IGNORECASE):
                raw = match.group(0)
                if not raw.strip() or _is_partial_literal_token_match(question, match.start(), match.end()):
                    continue
                matches.append(
                    _RawMatch(
                        hit_id="",
                        canonical_id=pattern.canonical_id,
                        mention_type=pattern.mention_type,
                        surface=raw,
                        span_start=match.start(),
                        span_end=match.end(),
                        match_source="time_extract" if pattern.mention_type == "TIME_EXPRESSION" else "literal_extract",
                        metadata={
                            "raw": raw,
                            "value_type_hint": pattern.value_type,
                        },
                        score=1.0,
                    )
                )
        ordered = tuple(sorted(matches, key=lambda item: (item.span_start, item.span_end, item.canonical_id)))
        return _assign_hit_ids(ordered, prefix="structured")

    def _vector_recall(
        self,
        unmatched_fragments: tuple[dict[str, Any], ...],
    ) -> tuple[list[dict[str, Any]], list[_RawMatch]]:
        recalls: list[dict[str, Any]] = []
        matches: list[_RawMatch] = []
        if self._vector_retriever is None:
            return recalls, matches
        for unmatched_fragment in unmatched_fragments:
            fragment = str(unmatched_fragment["surface"])
            fragment_start, fragment_end = unmatched_fragment["span"]
            if len(fragment) < 2:
                continue
            if fragment in {"地址", "名称", "标准", "类型", "状态", "IP", "RFC"}:
                continue
            if _is_runtime_literal_fragment(fragment):
                continue
            expected_type = unmatched_fragment.get("expected_mention_type")
            expected_type = str(expected_type) if expected_type else None
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
                            "mention_type": TYPE_NORMALIZATION.get(candidate.mention_type, candidate.mention_type),
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
            if expected_mention_type and entry.mention_type != expected_mention_type:
                continue
            registered.append(candidate)
        return registered

    def _signals(
        self,
        question: str,
        mentions: tuple[Mention, ...],
    ) -> tuple[tuple[ContextSignal, ...], tuple[ContextSignal, ...]]:
        context: list[ContextSignal] = []
        shape: list[ContextSignal] = []
        next_id = 1
        attribute_owner_pairs: list[tuple[Mention, Mention]] = []
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
        next_id = _append_scope_filter_signals(question, context, next_id, self._signal_rules.scope_filter_signals)
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
                "expected_mention_type": _expected_mention_type(question, fragment_start, fragment_end),
            }
        )
    return tuple(fragments)


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


def _append_scope_filter_signals(
    question: str,
    context: list[ContextSignal],
    next_id: int,
    rules: tuple[_ScopeFilterSignalRule, ...],
) -> int:
    seen_supports = {signal.supports for signal in context}
    for text, start, end, rule in _scope_filter_signal_matches(question, rules):
        if rule.supports in seen_supports:
            continue
        context.append(
            ContextSignal(
                signal_id=f"S{next_id}",
                signal_type=rule.signal_type,
                text=text,
                span_start=start,
                span_end=end,
                supports=rule.supports,
                strength=1.0,
            )
        )
        seen_supports.add(rule.supports)
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


def _append_predicate_group_signals(
    question: str,
    mentions: tuple[Mention, ...],
    context: list[ContextSignal],
    next_id: int,
) -> int:
    attributes = [item for item in mentions if item.mention_type == "ATTRIBUTE"]
    operators = [item for item in mentions if item.mention_type == "COMPARISON_OPERATOR"]
    literals = [item for item in mentions if item.mention_type in {"LITERAL_VALUE", "TIME_EXPRESSION"}]
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
        literal = min(
            (
                item
                for item in literals
                if item.span_start >= operator.span_end
                and _only_predicate_glue(question[operator.span_end : item.span_start])
            ),
            key=lambda item: item.span_start,
            default=None,
        )
        if literal is None:
            continue
        context.append(
            ContextSignal(
                signal_id=f"S{next_id}",
                signal_type="PREDICATE_GROUP",
                text=question[attribute.span_start : literal.span_end],
                span_start=attribute.span_start,
                span_end=literal.span_end,
                supports=tuple(
                    dict.fromkeys(
                        (
                            *_attribute_supports(attribute),
                            operator.canonical_id,
                            literal.surface,
                            literal.canonical_id,
                        )
                    )
                ),
                strength=1.0,
            )
        )
        next_id += 1
    return next_id


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


def _scope_filter_signal_spans(
    question: str,
    rules: tuple[_ScopeFilterSignalRule, ...],
) -> tuple[tuple[int, int], ...]:
    return tuple((start, end) for _, start, end, _ in _scope_filter_signal_matches(question, rules))


def _scope_filter_signal_matches(
    question: str,
    rules: tuple[_ScopeFilterSignalRule, ...],
) -> tuple[tuple[str, int, int, _ScopeFilterSignalRule], ...]:
    matches: list[tuple[str, int, int, _ScopeFilterSignalRule]] = []
    for rule in rules:
        for term in rule.surface_forms:
            for match in re.finditer(re.escape(term), question):
                matches.append((term, match.start(), match.end(), rule))
    return tuple(sorted(matches, key=lambda item: (item[1], item[2], item[0])))


def _load_lexical_signal_rules() -> _LexicalSignalRules:
    path = resource_paths.lexer_signal_rules_path()
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    scope_filter_signals: list[_ScopeFilterSignalRule] = []
    for rule in (payload.get("scope_filter_signals") or {}).values():
        if not isinstance(rule, dict):
            continue
        surface_forms = tuple(str(value) for value in rule.get("surface_forms", ()) if str(value))
        supports = tuple(str(value) for value in rule.get("supports", ()) if str(value))
        signal_type = str(rule.get("signal_type") or "")
        if not surface_forms or not supports or not signal_type:
            continue
        scope_filter_signals.append(
            _ScopeFilterSignalRule(
                signal_type=signal_type,
                supports=supports,
                surface_forms=surface_forms,
            )
        )
    return _LexicalSignalRules(scope_filter_signals=tuple(scope_filter_signals))


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
                mention_type=str(item.get("mention_type") or "LITERAL_VALUE"),
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


def _candidate_groups(matches: tuple[_RawMatch, ...]) -> dict[tuple[int, int, str, str], tuple[dict[str, Any], ...]]:
    grouped: dict[tuple[int, int, str, str], dict[str, dict[str, Any]]] = {}
    for match in matches:
        key = _candidate_group_key(match)
        grouped.setdefault(key, {})
        existing = grouped[key].setdefault(
            match.canonical_id,
            {
                "canonical_id": match.canonical_id,
                "mention_type": TYPE_NORMALIZATION.get(match.mention_type, match.mention_type),
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
        TYPE_NORMALIZATION.get(match.mention_type, match.mention_type),
    )


def _normalized_index_entries(
    entry: DictionaryEntry,
    entries_by_id: dict[str, DictionaryEntry],
) -> tuple[DictionaryEntry, ...]:
    if entry.mention_type == "synonym":
        return ()
    if entry.mention_type != "synonym_group":
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


def _expected_mention_type(question: str, start: int, end: int) -> str | None:
    fragment = question[start:end]
    if re.search(r"(越|过|经|用|连接|关联|拥有|下挂)", fragment):
        return "relation_predicate"
    if re.search(r"(数量|总数|统计|返回|查询)", fragment):
        return "operation_intent"
    if start > 0 and question[start - 1] == "的":
        return "attribute"
    return None


def _is_runtime_literal_fragment(fragment: str) -> bool:
    text = fragment.strip()
    if not text:
        return False
    comparable = _strip_literal_operator_prefix(text)
    if any(char in comparable for char in "\"'“”‘’"):
        return True
    if re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", comparable):
        return True
    if re.search(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b",
        comparable,
    ):
        return True
    if re.fullmatch(r"_?[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+", comparable):
        return True
    if re.fullmatch(r"_[A-Za-z0-9]+", comparable):
        return True
    if re.fullmatch(r"\d{4}[-/年]\d{1,2}(?:[-/月]\d{1,2}日?)?", comparable):
        return True
    if re.fullmatch(r"\d+(?:\.\d+)?(?:%|[A-Za-z]+|[个条次台])?", comparable):
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


def _strip_literal_operator_prefix(text: str) -> str:
    stripped = text.strip()
    patterns = (
        r"^(?:为|是|等于|不等于|大于|小于|不少于|不大于|不小于|超过|低于|高于|>=|<=|>|<|=|:|：)+",
    )
    for pattern in patterns:
        stripped = re.sub(pattern, "", stripped).strip()
    return stripped
