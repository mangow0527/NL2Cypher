from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .assets import OntologyAssets
from .object_role_selection import ObjectRoleSelection
from .models import LexerTrace, Mention


class OntologyMappingError(ValueError):
    pass


@dataclass(frozen=True)
class MappedMention:
    mapping_id: str
    mention_id: str
    mention_type: str
    surface: str
    span: tuple[int, int]
    ontology_kind: str
    ontology_id: str
    map_source: str
    candidate_refs: tuple[str, ...] = ()
    object_candidate_id: str | None = None
    selected_roles: tuple[str, ...] = ()
    domain_class: str | None = None
    range_class: str | None = None
    target_class: str | None = None
    parent_class: str | None = None
    constrains_attribute: str | None = None
    raw_value: str | None = None
    role: str | None = None
    attribute_candidates: tuple[str, ...] = ()
    semantic_object_kind: str | None = None
    definition_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "mapping_id": self.mapping_id,
            "mention_id": self.mention_id,
            "mention_type": self.mention_type,
            "surface": self.surface,
            "span": list(self.span),
            "ontology_kind": self.ontology_kind,
            "ontology_id": self.ontology_id,
            "map_source": self.map_source,
        }
        if self.candidate_refs:
            payload["candidate_refs"] = list(self.candidate_refs)
        if self.object_candidate_id is not None:
            payload["object_candidate_id"] = self.object_candidate_id
            payload["selected_roles"] = list(self.selected_roles)
        for key in (
            "domain_class",
            "range_class",
            "target_class",
            "parent_class",
            "constrains_attribute",
            "raw_value",
            "role",
            "semantic_object_kind",
            "definition_ref",
        ):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        if self.attribute_candidates:
            payload["attribute_candidates"] = list(self.attribute_candidates)
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True)
class OntologyMapping:
    ontology_objects: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    ontology_relation_hints: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    ontology_attributes: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    ontology_values: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    evidence: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ontology_objects": [dict(item) for item in self.ontology_objects],
            "ontology_relation_hints": [dict(item) for item in self.ontology_relation_hints],
            "ontology_attributes": [dict(item) for item in self.ontology_attributes],
            "ontology_values": [dict(item) for item in self.ontology_values],
            "evidence": [dict(item) for item in self.evidence],
        }


class OntologyMappingService:
    def __init__(self, assets: OntologyAssets) -> None:
        self.assets = assets
        self._mention_mappings = _mapping_entries(assets.mention_to_ontology)
        self._semantic_objects = _semantic_object_entries(assets.semantic_objects)
        self._classes = _classes(assets)
        self._relations = _relations(assets)
        self._attributes = _attributes(assets)
        self._values = _values(assets)

    def map(
        self,
        *,
        lexer_trace: LexerTrace,
        object_role_selection: ObjectRoleSelection,
    ) -> OntologyMapping:
        mention_ids = _mention_ids(lexer_trace)
        selected_by_mention_id = {
            item.mention_id: (item.candidate_id, item.roles, item.class_id)
            for item in object_role_selection.selected_objects
        }
        mapped: list[MappedMention] = []
        if len(mention_ids) != len(lexer_trace.mentions):
            raise OntologyMappingError("mention id count does not match lexer mentions")
        for mention_id, mention in zip(mention_ids, lexer_trace.mentions):
            mapping = self._map_mention(mention_id, mention, len(mapped) + 1)
            if mapping is None:
                continue
            selected = selected_by_mention_id.get(mention_id)
            if selected is not None:
                metadata = dict(mapping.metadata)
                if selected[2] is not None:
                    metadata["selected_object_class_id"] = selected[2]
                mapping = MappedMention(
                    **{
                        **mapping.__dict__,
                        "object_candidate_id": selected[0],
                        "selected_roles": selected[1],
                        "metadata": metadata,
                    }
                )
            mapped.append(mapping)
        mapped = _contextualize_service_tunnel_traversal(mapped, self._semantic_objects)
        return _ontology_mapping_ir(mapped)

    def _map_mention(self, mention_id: str, mention: Mention, index: int) -> MappedMention | None:
        mapping = self._mention_mappings.get(mention.canonical_id)
        semantic_object = self._semantic_objects.get(mention.canonical_id)
        if mapping is None and semantic_object is not None:
            mapping = {
                "ontology_kind": "semantic_object",
                "ontology_id": semantic_object["id"],
                "map_source": "semantic_objects",
            }
        if mapping is None and mention.mention_type in {"OBJECT", "RELATION", "ATTRIBUTE", "VALUE"}:
            ontology_kind = _default_kind(mention.mention_type)
            mapping = {
                "ontology_kind": ontology_kind,
                "ontology_id": _normalize_ontology_id(mention.canonical_id, ontology_kind),
                "map_source": "candidate_refs",
            }
        if mapping is None and mention.mention_type in {
            "LITERAL_VALUE",
            "COMPARISON_OPERATOR",
            "QUANTIFIER",
            "TIME_EXPRESSION",
        }:
            mapping = {
                "ontology_kind": "structured_mention",
                "ontology_id": mention.canonical_id,
                "map_source": "structured_extract",
            }
        if mapping is None:
            return None

        ontology_kind = str(mapping["ontology_kind"])
        ontology_id = str(mapping["ontology_id"])
        candidate_refs = _candidate_refs(mention)
        common = {
            "mapping_id": f"OM{index}",
            "mention_id": mention_id,
            "mention_type": mention.mention_type,
            "surface": mention.surface,
            "span": (mention.span_start, mention.span_end),
            "ontology_kind": ontology_kind,
            "ontology_id": ontology_id,
            "map_source": str(mapping.get("map_source") or "mention_to_ontology"),
            "candidate_refs": candidate_refs,
            "metadata": dict(mention.metadata),
        }
        self._validate_candidate_refs(candidate_refs, mention.mention_type)

        if ontology_kind == "class":
            self._require(ontology_id, self._classes, "class")
            return MappedMention(**common)
        if ontology_kind == "relation":
            relation = self._require(ontology_id, self._relations, "relation")
            return MappedMention(
                **common,
                domain_class=str(relation["domain_class"]),
                range_class=str(relation["range_class"]),
            )
        if ontology_kind == "relation_role":
            relation = self._require(ontology_id, self._relations, "relation")
            return MappedMention(
                **common,
                role=str(mapping.get("role") or relation.get("role")),
                domain_class=str(relation["domain_class"]),
                target_class=str(mapping.get("target_class") or relation["range_class"]),
            )
        if ontology_kind == "attribute":
            attribute = self._require(ontology_id, self._attributes, "attribute")
            attribute_candidates = tuple(
                self._ontology_id_for_ref(ref, expected_mention_type="ATTRIBUTE")
                for ref in candidate_refs
            )
            return MappedMention(
                **common,
                parent_class=str(attribute["parent_class"]),
                attribute_candidates=attribute_candidates,
            )
        if ontology_kind == "enum_value":
            value = self._require(ontology_id, self._values, "value")
            raw_value = mention.metadata.get("raw_value")
            if raw_value is None:
                raw_value = value.get("raw_value")
            return MappedMention(
                **common,
                constrains_attribute=str(value["constrains_attribute"]),
                raw_value=str(raw_value) if raw_value is not None else None,
            )
        if ontology_kind == "structured_mention":
            return MappedMention(**common)
        if ontology_kind == "semantic_object":
            semantic = self._semantic_objects.get(mention.canonical_id) or _semantic_by_id(
                self._semantic_objects,
                ontology_id,
            )
            if semantic is None:
                raise OntologyMappingError(f"unknown semantic_object: {ontology_id}")
            return MappedMention(
                **common,
                semantic_object_kind=str(semantic["kind"]),
                definition_ref=f"semantic_objects.{ontology_id}",
                domain_class=str(semantic.get("from_class")) if semantic.get("from_class") is not None else None,
                range_class=str(semantic.get("to_class")) if semantic.get("to_class") is not None else None,
            )
        raise OntologyMappingError(f"unsupported ontology_kind: {ontology_kind}")

    def _validate_candidate_refs(self, candidate_refs: tuple[str, ...], mention_type: str) -> None:
        for ref in candidate_refs:
            self._ontology_id_for_ref(ref, expected_mention_type=mention_type)

    def _ontology_id_for_ref(self, ref: str, *, expected_mention_type: str) -> str:
        semantic = self._semantic_objects.get(ref)
        if semantic is not None:
            ontology_id = str(semantic["id"])
            if _semantic_by_id(self._semantic_objects, ontology_id) is None:
                raise OntologyMappingError(f"unknown semantic_object: {ontology_id}")
            return ontology_id
        mapping = self._mention_mappings.get(ref)
        ontology_kind = str(mapping["ontology_kind"]) if mapping is not None else _default_kind(expected_mention_type)
        ontology_id = str(mapping["ontology_id"]) if mapping is not None else _normalize_ontology_id(ref, ontology_kind)
        if ontology_kind == "class":
            self._require(ontology_id, self._classes, "class")
        elif ontology_kind in {"relation", "relation_role"}:
            self._require(ontology_id, self._relations, "relation")
        elif ontology_kind == "attribute":
            self._require(ontology_id, self._attributes, "attribute")
        elif ontology_kind == "enum_value":
            self._require(ontology_id, self._values, "value")
        elif ontology_kind == "semantic_object":
            if _semantic_by_id(self._semantic_objects, ontology_id) is None:
                raise OntologyMappingError(f"unknown semantic_object: {ontology_id}")
        return ontology_id

    def _require(self, ontology_id: str, section: dict[str, Any], kind: str) -> dict[str, Any]:
        value = section.get(ontology_id)
        if not isinstance(value, dict):
            raise OntologyMappingError(f"unknown {kind}: {ontology_id}")
        return value


def _mapping_entries(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = payload.get("mappings", [])
    if not isinstance(entries, list):
        return {}
    return {str(item["mention_id"]): dict(item) for item in entries if isinstance(item, dict) and "mention_id" in item}


def _ontology_mapping_ir(mention_rows: list[MappedMention]) -> OntologyMapping:
    ontology_objects: list[dict[str, Any]] = []
    ontology_relation_hints: list[dict[str, Any]] = []
    ontology_attributes: list[dict[str, Any]] = []
    ontology_values: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    object_index = 0
    relation_hint_index = 0
    attribute_index = 0
    value_index = 0
    synthetic_object_keys: set[tuple[str, str | None]] = set()

    for order, mapped in enumerate(mention_rows, start=1):
        evidence_id = f"E{order}"
        evidence.append(_evidence_record(mapped, evidence_id))
        evidence_refs = [evidence_id]
        if mapped.ontology_kind == "class":
            object_index += 1
            synthetic_object_keys.add((mapped.ontology_id, mapped.object_candidate_id))
            ontology_objects.append(
                _without_none(
                    {
                        "object_id": f"OO{object_index}",
                        "class_id": mapped.ontology_id,
                        "object_candidate_id": mapped.object_candidate_id,
                        "selected_roles": list(mapped.selected_roles),
                        "evidence_refs": evidence_refs,
                        "order": order,
                    }
                )
            )
        elif mapped.ontology_kind == "relation":
            relation_hint_index += 1
            ontology_relation_hints.append(
                _without_none(
                    {
                        "relation_hint_id": f"ORH{relation_hint_index}",
                        "relation_id": mapped.ontology_id,
                        "from_class": mapped.domain_class,
                        "to_class": mapped.range_class,
                        "object_candidate_id": mapped.object_candidate_id,
                        "selected_roles": list(mapped.selected_roles),
                        "evidence_refs": evidence_refs,
                        "order": order,
                    }
                )
            )
        elif mapped.ontology_kind == "relation_role":
            relation_hint_index += 1
            relation_hint_id = f"ORH{relation_hint_index}"
            relation_hint = _without_none(
                {
                    "relation_hint_id": relation_hint_id,
                    "relation_id": mapped.ontology_id,
                    "from_class": mapped.domain_class,
                    "to_class": mapped.target_class or mapped.range_class,
                    "role": mapped.role,
                    "object_candidate_id": mapped.object_candidate_id,
                    "selected_roles": list(mapped.selected_roles),
                    "evidence_refs": evidence_refs,
                    "order": order,
                }
            )
            ontology_relation_hints.append(relation_hint)
            object_index += 1
            synthetic_object_keys.add((str(mapped.target_class or mapped.range_class), mapped.object_candidate_id))
            ontology_objects.append(
                _without_none(
                    {
                        "object_id": f"OO{object_index}",
                        "class_id": mapped.target_class or mapped.range_class,
                        "object_candidate_id": mapped.object_candidate_id,
                        "selected_roles": list(mapped.selected_roles),
                        "role_hint": {
                            "relation_hint_id": relation_hint_id,
                            "relation_id": mapped.ontology_id,
                            "role": mapped.role,
                            "source_class": mapped.domain_class,
                        },
                        "evidence_refs": evidence_refs,
                        "order": order,
                    }
                )
            )
        elif mapped.ontology_kind == "attribute":
            inferred_class_id = _selected_object_class(mapped)
            if inferred_class_id is not None and (inferred_class_id, mapped.object_candidate_id) not in synthetic_object_keys:
                object_index += 1
                synthetic_object_keys.add((inferred_class_id, mapped.object_candidate_id))
                ontology_objects.append(
                    _without_none(
                        {
                            "object_id": f"OO{object_index}",
                            "class_id": inferred_class_id,
                            "object_candidate_id": mapped.object_candidate_id,
                            "selected_roles": list(mapped.selected_roles),
                            "evidence_refs": evidence_refs,
                            "order": order,
                        }
                    )
                )
            attribute_index += 1
            ontology_attributes.append(
                _without_none(
                    {
                        "attribute_ref_id": f"OA{attribute_index}",
                        "attribute_id": mapped.ontology_id,
                        "parent_class": mapped.parent_class,
                        "attribute_candidates": list(mapped.attribute_candidates),
                        "evidence_refs": evidence_refs,
                        "order": order,
                    }
                )
            )
        elif mapped.ontology_kind == "enum_value":
            inferred_class_id = _selected_object_class(mapped)
            if inferred_class_id is not None and (inferred_class_id, mapped.object_candidate_id) not in synthetic_object_keys:
                object_index += 1
                synthetic_object_keys.add((inferred_class_id, mapped.object_candidate_id))
                ontology_objects.append(
                    _without_none(
                        {
                            "object_id": f"OO{object_index}",
                            "class_id": inferred_class_id,
                            "object_candidate_id": mapped.object_candidate_id,
                            "selected_roles": list(mapped.selected_roles),
                            "evidence_refs": evidence_refs,
                            "order": order,
                        }
                    )
                )
            value_index += 1
            ontology_values.append(
                _without_none(
                    {
                        "value_ref_id": f"OV{value_index}",
                        "value_id": mapped.ontology_id,
                        "raw_value": mapped.raw_value,
                        "constrains_attribute": mapped.constrains_attribute,
                        "evidence_refs": evidence_refs,
                        "order": order,
                    }
                )
            )
        elif mapped.ontology_kind == "semantic_object":
            relation_hint_index += 1
            ontology_relation_hints.append(
                _without_none(
                    {
                        "relation_hint_id": f"ORH{relation_hint_index}",
                        "semantic_object_id": mapped.ontology_id,
                        "semantic_object_kind": mapped.semantic_object_kind,
                        "definition_ref": mapped.definition_ref,
                        "from_class": mapped.domain_class,
                        "to_class": mapped.range_class,
                        "evidence_refs": evidence_refs,
                        "order": order,
                    }
                )
            )

    return OntologyMapping(
        ontology_objects=tuple(ontology_objects),
        ontology_relation_hints=tuple(ontology_relation_hints),
        ontology_attributes=tuple(ontology_attributes),
        ontology_values=tuple(ontology_values),
        evidence=tuple(evidence),
    )


def _selected_object_class(mapped: MappedMention) -> str | None:
    if not mapped.object_candidate_id or not mapped.selected_roles:
        return None
    class_id = mapped.metadata.get("selected_object_class_id")
    if isinstance(class_id, str) and class_id:
        return class_id
    return None


def _evidence_record(mapped: MappedMention, evidence_id: str) -> dict[str, Any]:
    return _without_none(
        {
            "evidence_id": evidence_id,
            "mapping_id": mapped.mapping_id,
            "mention_id": mapped.mention_id,
            "mention_type": mapped.mention_type,
            "surface": mapped.surface,
            "span": list(mapped.span),
            "ontology_kind": mapped.ontology_kind,
            "ontology_id": mapped.ontology_id,
            "map_source": mapped.map_source,
            "candidate_refs": list(mapped.candidate_refs),
            "object_candidate_id": mapped.object_candidate_id,
            "selected_roles": list(mapped.selected_roles),
            "metadata": dict(mapped.metadata),
        }
    )


def _without_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None and value != []}


def _domain_section(payload: dict[str, Any], section: str) -> dict[str, Any]:
    items = payload.get(section, {})
    if isinstance(items, dict):
        return dict(items)
    if isinstance(items, list):
        return {str(item["id"]): dict(item) for item in items if isinstance(item, dict) and "id" in item}
    return {}


def _classes(assets: OntologyAssets) -> dict[str, Any]:
    classes = _domain_section(assets.domain_ontology, "classes")
    for entry in assets.entries:
        if entry.mention_type == "OBJECT":
            classes.setdefault(entry.canonical_id, {"id": entry.canonical_id})
    return classes


def _relations(assets: OntologyAssets) -> dict[str, Any]:
    relations: dict[str, Any] = {}
    for relation_id, relation in _domain_section(assets.domain_ontology, "relations").items():
        normalized = {
            **relation,
            "domain_class": relation.get("domain_class") or relation.get("domain"),
            "range_class": relation.get("range_class") or relation.get("range"),
        }
        relations[relation_id] = normalized
    for entry in assets.entries:
        if entry.mention_type != "RELATION":
            continue
        ontology_id = entry.canonical_id.removeprefix("REL_")
        normalized = {
            "id": ontology_id,
            "domain_class": entry.metadata.get("domain"),
            "range_class": entry.metadata.get("range"),
            "role": entry.metadata.get("role"),
        }
        relations.setdefault(ontology_id, normalized)
    return relations


def _attributes(assets: OntologyAssets) -> dict[str, Any]:
    attributes = _domain_section(assets.domain_ontology, "attributes")
    for entry in assets.entries:
        if entry.mention_type == "ATTRIBUTE":
            attributes.setdefault(
                entry.canonical_id,
                {
                    "id": entry.canonical_id,
                    "parent_class": entry.metadata.get("parent_object") or entry.canonical_id.split(".", 1)[0],
                },
            )
    return attributes


def _values(assets: OntologyAssets) -> dict[str, Any]:
    values = _domain_section(assets.domain_ontology, "values")
    for entry in assets.entries:
        if entry.mention_type == "VALUE":
            values.setdefault(
                entry.canonical_id,
                {
                    "id": entry.canonical_id,
                    "constrains_attribute": entry.metadata.get("constrains_field"),
                    "raw_value": entry.metadata.get("raw_value"),
                },
            )
    return values


def _semantic_object_entries(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries_by_mention: dict[str, dict[str, Any]] = {}
    entries = payload.get("semantic_objects", [])
    if isinstance(entries, list):
        entries_by_mention.update(
            {str(item["mention_id"]): dict(item) for item in entries if isinstance(item, dict) and "mention_id" in item}
        )
    for kind in ("concepts", "traversals", "patterns", "metrics", "constraints"):
        section = payload.get(kind)
        if not isinstance(section, list):
            continue
        for item in section:
            if not isinstance(item, dict) or "id" not in item:
                continue
            normalized = {**item, "kind": str(item.get("kind") or kind[:-1])}
            entries_by_mention[str(item["id"])] = normalized
            mention_id = item.get("mention_id")
            if isinstance(mention_id, str) and mention_id:
                entries_by_mention[mention_id] = normalized
    return entries_by_mention


def _contextualize_service_tunnel_traversal(
    mapped_mentions: list[MappedMention],
    semantic_objects: dict[str, dict[str, Any]],
) -> list[MappedMention]:
    semantic = _semantic_by_id(semantic_objects, "service_traverses_tunnel")
    if semantic is None:
        return mapped_mentions
    contextualized: list[MappedMention] = []
    for index, mapped in enumerate(mapped_mentions):
        if not _is_ambiguous_service_tunnel_through(mapped):
            contextualized.append(mapped)
            continue
        left_class = _nearest_class_before(mapped_mentions, index)
        right_class = _nearest_class_after(mapped_mentions, index)
        if left_class != "Service" or right_class != "Tunnel":
            contextualized.append(mapped)
            continue
        contextualized.append(
            MappedMention(
                **{
                    **mapped.__dict__,
                    "ontology_kind": "semantic_object",
                    "ontology_id": "service_traverses_tunnel",
                    "map_source": "contextual_semantic_traversal",
                    "domain_class": str(semantic.get("from_class") or "Service"),
                    "range_class": str(semantic.get("to_class") or "Tunnel"),
                    "target_class": None,
                    "parent_class": None,
                    "constrains_attribute": None,
                    "role": None,
                    "attribute_candidates": (),
                    "semantic_object_kind": str(semantic.get("kind") or "traversal"),
                    "definition_ref": "semantic_objects.service_traverses_tunnel",
                }
            )
        )
    return contextualized


def _is_ambiguous_service_tunnel_through(mapped: MappedMention) -> bool:
    return (
        mapped.ontology_kind == "relation"
        and mapped.ontology_id == "PATH_THROUGH"
        and "REL_PATH_THROUGH" in mapped.candidate_refs
        and mapped.surface in {"经过", "穿过", "途经"}
    )


def _nearest_class_before(mapped_mentions: list[MappedMention], index: int) -> str | None:
    for mapped in reversed(mapped_mentions[:index]):
        if mapped.ontology_kind == "class":
            return mapped.ontology_id
    return None


def _nearest_class_after(mapped_mentions: list[MappedMention], index: int) -> str | None:
    for mapped in mapped_mentions[index + 1 :]:
        if mapped.ontology_kind == "class":
            return mapped.ontology_id
    return None


def _semantic_by_id(entries: dict[str, dict[str, Any]], ontology_id: str) -> dict[str, Any] | None:
    for item in entries.values():
        if item.get("id") == ontology_id:
            return item
    return None


def _candidate_refs(mention: Mention) -> tuple[str, ...]:
    refs = mention.metadata.get("candidate_refs")
    if isinstance(refs, (list, tuple)) and refs:
        return tuple(str(item) for item in refs)
    return (mention.canonical_id,)


def _mention_ids(lexer_trace: LexerTrace) -> tuple[str, ...]:
    counters: dict[str, int] = {}
    mention_ids: list[str] = []
    for mention in lexer_trace.mentions:
        explicit_id = mention.metadata.get("mention_id") if isinstance(mention.metadata, dict) else None
        if isinstance(explicit_id, str) and explicit_id:
            mention_ids.append(explicit_id)
            continue
        base = _stable_id_part(mention.canonical_id or mention.surface)
        counters[base] = counters.get(base, 0) + 1
        mention_ids.append(f"m_{base}_{counters[base]}")
    return tuple(mention_ids)


def _stable_id_part(value: str) -> str:
    normalized = []
    for char in value:
        if char.isalnum():
            normalized.append(char.lower())
        else:
            normalized.append("_")
    return "".join(normalized).strip("_") or "mention"


def _default_kind(mention_type: str) -> str:
    return {
        "OBJECT": "class",
        "RELATION": "relation",
        "ATTRIBUTE": "attribute",
        "VALUE": "enum_value",
    }.get(mention_type, "")


def _normalize_ontology_id(ref: str, ontology_kind: str) -> str:
    if ontology_kind in {"relation", "relation_role"}:
        return ref.removeprefix("REL_")
    return ref
