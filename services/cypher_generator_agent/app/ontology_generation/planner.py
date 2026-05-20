from __future__ import annotations

from collections import deque

from .assets import OntologyAssets
from .models import (
    IntentTrace,
    LexerTrace,
    OntologyLogicalPlan,
    PlanEdge,
    PlanFilter,
    PlanMetric,
    PlanNode,
    PlanProjection,
    PlannerTrace,
    ShapeField,
)


ALIASES = {
    "Service": "s",
    "Tunnel": "t",
    "NetworkElement": "ne",
    "Port": "p",
    "Protocol": "proto",
    "Fiber": "f",
    "Link": "l",
}


class OntologyLogicalPlanner:
    def __init__(self, assets: OntologyAssets) -> None:
        self.assets = assets
        self._relations = tuple(entry for entry in assets.entries if entry.mention_type == "relation_predicate")

    def plan(self, lexer_trace: LexerTrace, intent_trace: IntentTrace) -> tuple[OntologyLogicalPlan, PlannerTrace]:
        object_types = _base_object_types(lexer_trace)
        object_types.update(_attribute_parent_types(lexer_trace, object_types))
        if any(item.canonical_id == "REL_TUNNEL_SRC" for item in lexer_trace.mentions):
            object_types.update({"Tunnel", "NetworkElement"})
        if "Service" in object_types and "Tunnel" in object_types:
            object_types.update({"Service", "Tunnel"})

        filters = _filters(lexer_trace)
        nodes = tuple(
            PlanNode(
                id=_node_id(object_type),
                type=object_type,
                alias=ALIASES[object_type],
                filters=tuple(item for item in filters if item.node == _node_id(object_type)),
            )
            for object_type in _ordered_object_types(object_types)
        )
        edges, path_candidates, selected_paths = self._edges(object_types, lexer_trace)
        metrics = _metrics(intent_trace, nodes, lexer_trace)
        projections, bindings = _projections(lexer_trace, object_types, allow_default=not metrics)

        shape = dict(intent_trace.shape)
        if edges:
            shape["hop_count"] = ShapeField(
                value=len(edges),
                source="ontology_path_selection",
                decision="accept",
                confidence=1.0,
            )
            shape["relation_chain_type"] = ShapeField(
                value="fixed_chain",
                source="ontology_path_selection",
                decision="accept",
                confidence=1.0,
            )
        shape["filter_level"] = ShapeField(
            value="record_filter" if filters else "none",
            source="binding",
            decision="accept",
            confidence=1.0,
            derived_from=tuple(item.canonical_id for item in lexer_trace.mentions if item.mention_type == "VALUE"),
        )

        logical_plan = OntologyLogicalPlan(
            root_operation="SELECT",
            intent=intent_trace.intent,
            shape=shape,
            nodes=nodes,
            edges=edges,
            projections=projections,
            metrics=metrics,
        )
        planner_trace = PlannerTrace(
            path_candidates=tuple(path_candidates),
            selected_paths=tuple(selected_paths),
            coreference=_coreference_records(lexer_trace),
            bindings=tuple(bindings),
        )
        return logical_plan, planner_trace

    def _edges(
        self,
        object_types: set[str],
        lexer_trace: LexerTrace,
    ) -> tuple[tuple[PlanEdge, ...], list[dict[str, object]], list[dict[str, object]]]:
        candidates: list[dict[str, object]] = []
        selected: list[dict[str, object]] = []
        edges: list[PlanEdge] = []
        object_order = _ordered_object_mentions(lexer_trace, object_types)
        if len(object_order) < 2:
            return (), candidates, selected

        for left, right in zip(object_order, object_order[1:]):
            path = self._relation_path(left, right, lexer_trace)
            if not path:
                continue
            candidates.append({"from": left, "to": right, "path": [entry.canonical_id for entry in path]})
            selected.append(candidates[-1])
            for relation in path:
                from_type = str(relation.metadata["domain"])
                to_type = str(relation.metadata["range"])
                edge_type = _edge_type(relation)
                edge = PlanEdge(
                    from_node=_node_id(from_type),
                    to_node=_node_id(to_type),
                    relation=relation.canonical_id,
                    edge_type=edge_type,
                )
                if edge not in edges:
                    edges.append(edge)
        return tuple(edges), candidates, selected

    def _relation_path(self, left: str, right: str, lexer_trace: LexerTrace) -> tuple[object, ...]:
        explicit = _explicit_relation_for(left, right, lexer_trace, self._relations)
        if explicit is not None:
            return (explicit,)
        return self._shortest_relation_path(left, right)

    def _shortest_relation_path(self, left: str, right: str) -> tuple[object, ...]:
        graph: dict[str, list[object]] = {}
        for relation in self._relations:
            domain = relation.metadata.get("domain")
            range_ = relation.metadata.get("range")
            if not isinstance(domain, str) or not isinstance(range_, str):
                continue
            graph.setdefault(domain, []).append(relation)
        queue: deque[tuple[str, tuple[object, ...]]] = deque([(left, ())])
        seen = {left}
        while queue:
            node, path = queue.popleft()
            if node == right:
                return path
            for relation in graph.get(node, []):
                next_node = str(relation.metadata["range"])
                if next_node in seen:
                    continue
                seen.add(next_node)
                queue.append((next_node, (*path, relation)))
        return ()


def _base_object_types(lexer_trace: LexerTrace) -> set[str]:
    object_types = {item.canonical_id for item in lexer_trace.mentions if item.mention_type == "OBJECT"}
    for mention in lexer_trace.mentions:
        if mention.mention_type != "RELATION":
            if mention.mention_type == "VALUE":
                field = mention.metadata.get("constrains_field")
                if isinstance(field, str) and "." in field:
                    object_types.add(field.split(".", 1)[0])
            continue
        for relation_candidate in _relation_candidate_metadata(mention):
            domain = relation_candidate.get("domain")
            range_ = relation_candidate.get("range")
            if isinstance(domain, str):
                object_types.add(domain)
            if isinstance(range_, str):
                object_types.add(range_)
    return object_types


def _attribute_parent_types(lexer_trace: LexerTrace, object_types: set[str]) -> set[str]:
    parents: set[str] = set()
    for mention in lexer_trace.mentions:
        attribute_id = _resolved_attribute_id(mention, object_types)
        if attribute_id is not None and "." in attribute_id:
            parents.add(attribute_id.split(".", 1)[0])
    return parents


def _ordered_object_types(object_types: set[str]) -> list[str]:
    order = ["Service", "Tunnel", "NetworkElement", "Port", "Protocol", "Fiber", "Link"]
    return [item for item in order if item in object_types]


def _ordered_object_mentions(lexer_trace: LexerTrace, object_types: set[str]) -> list[str]:
    positioned: list[tuple[int, str]] = []
    for mention in lexer_trace.mentions:
        if mention.mention_type == "OBJECT" and mention.canonical_id in object_types:
            positioned.append((mention.span_start, mention.canonical_id))
        elif mention.mention_type == "ATTRIBUTE" and "." in mention.canonical_id:
            owner = _resolved_attribute_id(mention, object_types, lexer_trace).split(".", 1)[0]
            if owner in object_types:
                positioned.append((mention.span_start, owner))
        elif mention.mention_type == "RELATION":
            for relation_candidate in _relation_candidate_metadata(mention):
                domain = relation_candidate.get("domain")
                range_ = relation_candidate.get("range")
                if isinstance(domain, str) and domain in object_types:
                    positioned.append((mention.span_start, domain))
                if isinstance(range_, str) and range_ in object_types:
                    positioned.append((mention.span_start + 1, range_))
    ordered: list[str] = []
    for _, object_type in sorted(positioned, key=lambda item: item[0]):
        if object_type not in ordered:
            ordered.append(object_type)
    for fallback in _ordered_object_types(object_types):
        if fallback not in ordered:
            ordered.append(fallback)
    return ordered


def _node_id(object_type: str) -> str:
    return {"Service": "s1", "Tunnel": "t1", "NetworkElement": "n1"}.get(object_type, object_type[:1].lower() + "1")


def _edge_type(relation: object) -> str:
    join_path = getattr(relation, "metadata", {}).get("join_path")
    if isinstance(join_path, list) and join_path and isinstance(join_path[0], dict):
        edge = join_path[0].get("edge")
        if isinstance(edge, str):
            return edge
    return str(getattr(relation, "canonical_id")).removeprefix("REL_")


def _explicit_relation_for(left: str, right: str, lexer_trace: LexerTrace, relations: tuple[object, ...]) -> object | None:
    mentioned_relation_ids: set[str] = set()
    for mention in lexer_trace.mentions:
        if mention.mention_type != "RELATION":
            continue
        mentioned_relation_ids.update(_candidate_refs(mention))
    for relation in relations:
        if relation.canonical_id not in mentioned_relation_ids:
            continue
        if relation.metadata.get("domain") == left and relation.metadata.get("range") == right:
            return relation
    return None


def _filters(lexer_trace: LexerTrace) -> tuple[PlanFilter, ...]:
    filters: list[PlanFilter] = []
    for mention in lexer_trace.mentions:
        if mention.mention_type != "VALUE":
            continue
        if mention.metadata.get("conditional_metric"):
            continue
        field = mention.metadata.get("constrains_field")
        if not isinstance(field, str) or "." not in field:
            continue
        owner, attr = field.split(".", 1)
        filters.append(
            PlanFilter(
                node=_node_id(owner),
                attr=attr,
                operator="=",
                value=_value_payload(mention),
            )
        )
    return tuple(filters)


def _metrics(intent_trace: IntentTrace, nodes: tuple[PlanNode, ...], lexer_trace: LexerTrace) -> tuple[PlanMetric, ...]:
    if intent_trace.intent.primary == "breakdown_query" and intent_trace.intent.secondary == "multi_metric_breakdown_query":
        target = _node_by_type(nodes, "Tunnel") or _metric_target_node(nodes)
        conditional = _conditional_metric_filter(lexer_trace)
        metrics = [PlanMetric(function="count", node=target.id, alias=f"{_metric_alias_prefix(target.type)}_count")]
        if conditional is not None:
            metrics.append(
                PlanMetric(
                    function="conditional_count",
                    node=target.id,
                    alias=_conditional_metric_alias(conditional),
                    condition=(conditional,),
                )
            )
        return tuple(metrics)
    if intent_trace.intent.primary != "metric_query" or intent_trace.intent.secondary != "count_metric_query":
        return ()
    target = _metric_target_node(nodes)
    return (PlanMetric(function="count", node=target.id, alias=f"{_metric_alias_prefix(target.type)}_count"),)


def _node_by_type(nodes: tuple[PlanNode, ...], object_type: str) -> PlanNode | None:
    for node in nodes:
        if node.type == object_type:
            return node
    return None


def _conditional_metric_filter(lexer_trace: LexerTrace) -> PlanFilter | None:
    for mention in lexer_trace.mentions:
        if mention.mention_type != "VALUE" or not mention.metadata.get("conditional_metric"):
            continue
        field = mention.metadata.get("constrains_field")
        if not isinstance(field, str) or "." not in field:
            continue
        owner, attr = field.split(".", 1)
        return PlanFilter(node=_node_id(owner), attr=attr, operator="=", value=_value_payload(mention))
    return None


def _conditional_metric_alias(condition: PlanFilter) -> str:
    value = str(condition.value).lower().replace("-", "_")
    return f"source_ne_{value}_tunnel_count"


def _value_payload(mention: object) -> object:
    metadata = getattr(mention, "metadata", {})
    if not isinstance(metadata, dict):
        return None
    if "literal_value" in metadata:
        return metadata["literal_value"]
    return metadata.get("raw_value")


def _metric_target_node(nodes: tuple[PlanNode, ...]) -> PlanNode:
    for preferred in ("Tunnel", "Service", "NetworkElement", "Port"):
        for node in nodes:
            if node.type == preferred:
                return node
    return nodes[-1]


def _metric_alias_prefix(object_type: str) -> str:
    return {"Service": "service", "Tunnel": "tunnel", "NetworkElement": "network_element", "Port": "port"}.get(
        object_type, object_type.lower()
    )


def _projections(
    lexer_trace: LexerTrace,
    object_types: set[str],
    *,
    allow_default: bool = True,
) -> tuple[tuple[PlanProjection, ...], list[dict[str, object]]]:
    return_markers = [item for item in lexer_trace.mentions if item.canonical_id == "OP_RETURN_FIELD"]
    projection_start = min((item.span_end for item in return_markers), default=0)
    projections: list[PlanProjection] = []
    bindings: list[dict[str, object]] = []
    for mention in lexer_trace.mentions:
        if mention.mention_type != "ATTRIBUTE" or mention.span_start < projection_start:
            continue
        attribute_id = _resolved_attribute_id(mention, object_types, lexer_trace)
        if attribute_id is None or "." not in attribute_id:
            continue
        owner, attr = attribute_id.split(".", 1)
        if owner not in object_types:
            continue
        projection = PlanProjection(node=_node_id(owner), attribute=attr, alias=_projection_alias(owner, attr, lexer_trace))
        if projection not in projections:
            projections.append(projection)
            bindings.append(
                {
                    "mention": mention.canonical_id,
                    "resolved_attribute": attribute_id,
                    "node": projection.node,
                    "attribute": attr,
                    "alias": projection.alias,
                    "evidence": mention.surface,
                }
            )
    if allow_default and not projections:
        for object_type in ("Tunnel", "Service", "NetworkElement"):
            if object_type in object_types:
                projections.append(
                    PlanProjection(node=_node_id(object_type), attribute="name", alias=_projection_alias(object_type, "name", lexer_trace))
                )
                break
    return tuple(projections), bindings


def _projection_alias(owner: str, attr: str, lexer_trace: LexerTrace) -> str:
    if owner == "NetworkElement" and any(item.canonical_id == "REL_TUNNEL_SRC" for item in lexer_trace.mentions):
        return f"source_ne_{attr}"
    prefix = {"Service": "service", "Tunnel": "tunnel", "NetworkElement": "network_element"}.get(owner, owner.lower())
    return f"{prefix}_{attr}"


def _coreference_records(lexer_trace: LexerTrace) -> tuple[dict[str, object], ...]:
    records: list[dict[str, object]] = []
    seen: dict[str, int] = {}
    for mention in lexer_trace.mentions:
        if mention.mention_type not in {"OBJECT", "RELATION"}:
            continue
        seen[mention.canonical_id] = seen.get(mention.canonical_id, 0) + 1
    for canonical_id, count in seen.items():
        if count > 1:
            records.append({"canonical_id": canonical_id, "decision": "same_instance", "count": count})
    return tuple(records)


def _resolved_attribute_id(
    mention: object,
    object_types: set[str],
    lexer_trace: LexerTrace | None = None,
) -> str | None:
    if getattr(mention, "mention_type", None) != "ATTRIBUTE":
        return None
    candidates = _candidate_refs(mention)
    nearest_owner = _nearest_left_attribute_owner(mention, lexer_trace) if lexer_trace is not None else None
    if nearest_owner is not None:
        for candidate in candidates:
            if candidate.startswith(f"{nearest_owner}."):
                return candidate
    for owner in _ordered_object_types(object_types):
        for candidate in candidates:
            if candidate.startswith(f"{owner}."):
                return candidate
    canonical_id = getattr(mention, "canonical_id", "")
    if isinstance(canonical_id, str):
        return canonical_id
    return None


def _nearest_left_attribute_owner(mention: object, lexer_trace: LexerTrace | None) -> str | None:
    if lexer_trace is None:
        return None
    owners: list[tuple[int, str]] = []
    mention_start = getattr(mention, "span_start", 0)
    for item in lexer_trace.mentions:
        if item.span_end > mention_start:
            continue
        if item.mention_type == "OBJECT":
            owners.append((item.span_end, item.canonical_id))
        elif item.mention_type == "RELATION":
            for relation_candidate in _relation_candidate_metadata(item):
                range_ = relation_candidate.get("range")
                if isinstance(range_, str):
                    owners.append((item.span_end, range_))
        elif item.mention_type == "VALUE":
            field = item.metadata.get("constrains_field")
            if isinstance(field, str) and "." in field:
                owners.append((item.span_end, field.split(".", 1)[0]))
    if not owners:
        return None
    return max(owners, key=lambda item: item[0])[1]


def _candidate_refs(mention: object) -> tuple[str, ...]:
    metadata = getattr(mention, "metadata", {})
    refs = metadata.get("candidate_refs") if isinstance(metadata, dict) else None
    if isinstance(refs, (list, tuple)) and refs:
        return tuple(str(item) for item in refs)
    canonical_id = getattr(mention, "canonical_id", "")
    return (str(canonical_id),) if canonical_id else ()


def _relation_candidate_metadata(mention: object) -> tuple[dict[str, object], ...]:
    metadata = getattr(mention, "metadata", {})
    if isinstance(metadata, dict):
        candidates = metadata.get("candidates")
        if isinstance(candidates, list) and candidates:
            return tuple(
                dict(candidate.get("metadata", {}))
                for candidate in candidates
                if isinstance(candidate, dict) and isinstance(candidate.get("metadata"), dict)
            )
    return (dict(metadata),) if isinstance(metadata, dict) else ()
