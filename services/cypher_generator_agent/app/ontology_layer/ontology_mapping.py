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
    role: str | None = None
    attribute_candidates: tuple[str, ...] = ()
    semantic_object_kind: str | None = None
    definition_ref: str | None = None

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
            "role",
            "semantic_object_kind",
            "definition_ref",
        ):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        if self.attribute_candidates:
            payload["attribute_candidates"] = list(self.attribute_candidates)
        return payload


@dataclass(frozen=True)
class OntologyMapping:
    mapped_mentions: tuple[MappedMention, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {"mapped_mentions": [item.to_dict() for item in self.mapped_mentions]}


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
            item.mention_id: (item.candidate_id, item.roles)
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
                mapping = MappedMention(
                    **{
                        **mapping.__dict__,
                        "object_candidate_id": selected[0],
                        "selected_roles": selected[1],
                    }
                )
            mapped.append(mapping)
        return OntologyMapping(mapped_mentions=tuple(mapped))

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
            return MappedMention(**common, constrains_attribute=str(value["constrains_attribute"]))
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
        if entry.mention_type == "business_object":
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
        relations.setdefault(relation_id.removeprefix("REL_"), normalized)
    for entry in assets.entries:
        if entry.mention_type != "relation_predicate":
            continue
        ontology_id = entry.canonical_id.removeprefix("REL_")
        normalized = {
            "id": ontology_id,
            "domain_class": entry.metadata.get("domain"),
            "range_class": entry.metadata.get("range"),
            "role": entry.metadata.get("role"),
        }
        relations.setdefault(ontology_id, normalized)
        relations.setdefault(entry.canonical_id, normalized)
    return relations


def _attributes(assets: OntologyAssets) -> dict[str, Any]:
    attributes = _domain_section(assets.domain_ontology, "attributes")
    for entry in assets.entries:
        if entry.mention_type == "attribute":
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
        if entry.mention_type == "attribute_value":
            values.setdefault(
                entry.canonical_id,
                {
                    "id": entry.canonical_id,
                    "constrains_attribute": entry.metadata.get("constrains_field"),
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
            mention_id = item.get("mention_id")
            if isinstance(mention_id, str) and mention_id:
                entries_by_mention[mention_id] = normalized
    return entries_by_mention


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
