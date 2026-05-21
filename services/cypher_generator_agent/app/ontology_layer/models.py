from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from services.cypher_generator_agent.app.intent_layer.models import Intent, IntentOutput, InitialShapeField


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
    structured_matches: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "matcher": self.matcher,
            "ac_matches": [dict(item) for item in self.ac_matches],
            "structured_matches": [dict(item) for item in self.structured_matches],
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
class PlanNodeReturn:
    node: str
    alias: str

    def to_dict(self) -> dict[str, Any]:
        return {"node": self.node, "alias": self.alias}


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
    intent: Intent
    shape: dict[str, InitialShapeField]
    nodes: tuple[PlanNode, ...]
    edges: tuple[PlanEdge, ...]
    projections: tuple[PlanProjection, ...]
    node_returns: tuple[PlanNodeReturn, ...] = ()
    metrics: tuple[PlanMetric, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_operation": self.root_operation,
            "intent": self.intent.to_dict(),
            "shape": {key: value.to_dict() for key, value in self.shape.items()},
            "nodes": [item.to_dict() for item in self.nodes],
            "edges": [item.to_dict() for item in self.edges],
            "projection": [item.to_dict() for item in self.projections],
            "node_returns": [item.to_dict() for item in self.node_returns],
            "metrics": [item.to_dict() for item in self.metrics],
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
    intent: IntentOutput
    object_role_selection: Any
    ontology_mapping: Any
    ontology_path_selection: Any
    coreference: Any
    binding: Any
    shape_finalization: Any
    validator: ValidatorTrace
    compiler: CompilerTrace

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "cga_trace_v2",
            "trace_id": self.trace_id,
            "preprocessing": dict(self.preprocessing),
            "lexer": self.lexer.to_dict(),
            "intent": self.intent.to_dict(),
            "object_role_selection": self.object_role_selection.to_dict(),
            "ontology_mapping": self.ontology_mapping.to_dict(),
            "ontology_path_selection": self.ontology_path_selection.to_dict(),
            "coreference": dict(self.coreference),
            "binding": self.binding.to_dict(),
            "shape_finalization": self.shape_finalization.to_dict(),
            "validator": self.validator.to_dict(),
            "compiler": self.compiler.to_dict(),
        }


@dataclass(frozen=True)
class GenerationResult:
    status: str
    cypher: str
    logical_plan: OntologyLogicalPlan
    trace: GenerationTrace
