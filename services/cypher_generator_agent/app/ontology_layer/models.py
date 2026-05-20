from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _dict_without_none(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item is not None}


@dataclass(frozen=True)
class DictionaryEntry:
    canonical_id: str
    mention_type: str
    surface_forms: tuple[str, ...]
    description: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Mention:
    canonical_id: str
    mention_type: str
    surface: str
    span_start: int
    span_end: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "mention_type": self.mention_type,
            "surface": self.surface,
            "span": [self.span_start, self.span_end],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ContextSignal:
    signal_id: str
    signal_type: str
    text: str
    span_start: int
    span_end: int
    supports: tuple[str, ...]
    strength: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "type": self.signal_type,
            "text": self.text,
            "span": [self.span_start, self.span_end],
            "supports": list(self.supports),
            "strength": self.strength,
        }


@dataclass(frozen=True)
class ShapeField:
    value: Any
    source: str
    decision: str
    confidence: float
    derived_from: tuple[str, ...] = ()
    pending_until: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _dict_without_none(
            {
                "value": self.value,
                "source": self.source,
                "decision": self.decision,
                "confidence": self.confidence,
                "derived_from": list(self.derived_from),
                "pending_until": self.pending_until,
            }
        )


@dataclass(frozen=True)
class IntentIdentity:
    primary: str
    secondary: str
    source: str
    decision: str
    confidence: float
    clarify_origin: str | None = None
    clarify_reason: str | None = None
    failed_fields: tuple[str, ...] = ()
    candidate_intents: tuple[dict[str, Any], ...] = ()
    evidence: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "primary": self.primary,
            "secondary": self.secondary,
            "source": self.source,
            "decision": self.decision,
            "confidence": self.confidence,
        }
        if self.clarify_origin is not None:
            payload["clarify_origin"] = self.clarify_origin
        if self.clarify_reason is not None:
            payload["clarify_reason"] = self.clarify_reason
        if self.failed_fields:
            payload["failed_fields"] = list(self.failed_fields)
        if self.candidate_intents:
            payload["candidate_intents"] = [dict(item) for item in self.candidate_intents]
        if self.evidence is not None:
            payload["evidence"] = dict(self.evidence)
        return payload


@dataclass(frozen=True)
class LexerTrace:
    question: str
    matcher: str
    ac_matches: tuple[dict[str, Any], ...]
    selected_hits: tuple[dict[str, Any], ...]
    discarded_hits: tuple[dict[str, Any], ...]
    resolution_summary: dict[str, int]
    unmatched_fragments: tuple[dict[str, Any], ...]
    vector_recalls: tuple[dict[str, Any], ...]
    mentions: tuple[Mention, ...]
    unmatched_spans: tuple[tuple[int, int], ...]
    context_signals: tuple[ContextSignal, ...]
    shape_signals: tuple[ContextSignal, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "matcher": self.matcher,
            "ac_matches": [dict(item) for item in self.ac_matches],
            "selected_hits": [dict(item) for item in self.selected_hits],
            "discarded_hits": [dict(item) for item in self.discarded_hits],
            "resolution_summary": dict(self.resolution_summary),
            "unmatched_fragments": [dict(item) for item in self.unmatched_fragments],
            "vector_recalls": [dict(item) for item in self.vector_recalls],
            "mentions": [item.to_dict() for item in self.mentions],
            "unmatched_spans": [list(item) for item in self.unmatched_spans],
            "context_signals": [item.to_dict() for item in self.context_signals],
            "shape_signals": [item.to_dict() for item in self.shape_signals],
        }


@dataclass(frozen=True)
class IntentTrace:
    intent: IntentIdentity
    shape: dict[str, ShapeField]
    candidates: tuple[dict[str, Any], ...]
    rule_signals_used: tuple[str, ...]
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent.to_dict(),
            "shape": {key: value.to_dict() for key, value in self.shape.items()},
            "candidates": [dict(item) for item in self.candidates],
            "rule_signals_used": list(self.rule_signals_used),
            "diagnostics": dict(self.diagnostics),
        }


@dataclass(frozen=True)
class PlanFilter:
    node: str
    attr: str
    operator: str
    value: Any

    def to_dict(self) -> dict[str, Any]:
        return {"node": self.node, "attr": self.attr, "operator": self.operator, "value": self.value}


@dataclass(frozen=True)
class PlanNode:
    id: str
    type: str
    alias: str
    filters: tuple[PlanFilter, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "alias": self.alias,
            "filters": [item.to_dict() for item in self.filters],
        }


@dataclass(frozen=True)
class PlanEdge:
    from_node: str
    to_node: str
    relation: str
    edge_type: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "from": self.from_node,
            "to": self.to_node,
            "relation": self.relation,
            "edge_type": self.edge_type,
        }


@dataclass(frozen=True)
class PlanProjection:
    node: str
    attribute: str
    alias: str

    def to_dict(self) -> dict[str, Any]:
        return {"node": self.node, "attribute": self.attribute, "alias": self.alias}


@dataclass(frozen=True)
class PlanMetric:
    function: str
    node: str
    alias: str
    distinct: bool = False
    condition: tuple[PlanFilter, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "function": self.function,
            "node": self.node,
            "alias": self.alias,
            "distinct": self.distinct,
            "condition": [item.to_dict() for item in self.condition],
        }


@dataclass(frozen=True)
class OntologyLogicalPlan:
    root_operation: str
    intent: IntentIdentity
    shape: dict[str, ShapeField]
    nodes: tuple[PlanNode, ...]
    edges: tuple[PlanEdge, ...]
    projections: tuple[PlanProjection, ...]
    metrics: tuple[PlanMetric, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_operation": self.root_operation,
            "intent": self.intent.to_dict(),
            "shape": {key: value.to_dict() for key, value in self.shape.items()},
            "nodes": [item.to_dict() for item in self.nodes],
            "edges": [item.to_dict() for item in self.edges],
            "projection": [item.to_dict() for item in self.projections],
            "metrics": [item.to_dict() for item in self.metrics],
        }


@dataclass(frozen=True)
class PlannerTrace:
    path_candidates: tuple[dict[str, Any], ...]
    selected_paths: tuple[dict[str, Any], ...]
    coreference: tuple[dict[str, Any], ...]
    bindings: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path_candidates": [dict(item) for item in self.path_candidates],
            "selected_paths": [dict(item) for item in self.selected_paths],
            "coreference": [dict(item) for item in self.coreference],
            "bindings": [dict(item) for item in self.bindings],
        }


@dataclass(frozen=True)
class ValidatorTrace:
    accepted: bool
    checks: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {"accepted": self.accepted, "checks": [dict(item) for item in self.checks]}


@dataclass(frozen=True)
class CompilerTrace:
    renderer_family: str
    mapping_version: int
    physical_schema_version: int
    physical_bindings: dict[str, str]
    attribute_bindings: dict[str, str]
    cypher: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "renderer_family": self.renderer_family,
            "mapping_version": self.mapping_version,
            "physical_schema_version": self.physical_schema_version,
            "physical_bindings": dict(self.physical_bindings),
            "attribute_bindings": dict(self.attribute_bindings),
            "cypher": self.cypher,
        }


@dataclass(frozen=True)
class GenerationTrace:
    trace_id: str
    preprocessing: dict[str, Any]
    lexer: LexerTrace
    intent: IntentTrace
    object_role_selection: Any
    ontology_mapping: Any
    planner: PlannerTrace
    validator: ValidatorTrace
    compiler: CompilerTrace

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "preprocessing": dict(self.preprocessing),
            "lexer": self.lexer.to_dict(),
            "intent": self.intent.to_dict(),
            "object_role_selection": self.object_role_selection.to_dict(),
            "ontology_mapping": self.ontology_mapping.to_dict(),
            "planner": self.planner.to_dict(),
            "validator": self.validator.to_dict(),
            "compiler": self.compiler.to_dict(),
        }


@dataclass(frozen=True)
class GenerationResult:
    status: str
    cypher: str
    logical_plan: OntologyLogicalPlan
    trace: GenerationTrace
