from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from services.cypher_generator_agent.app.infrastructure import resource_paths

from .models import DictionaryEntry


MENTION_DICTIONARY_FILES = (
    "business_objects.yaml",
    "attributes.yaml",
    "attribute_values.yaml",
    "relation_predicates.yaml",
    "operation_intents.yaml",
    "synonyms.yaml",
)


@dataclass(frozen=True)
class OntologyAssets:
    entries: tuple[DictionaryEntry, ...]
    mention_to_ontology: dict[str, Any] = field(default_factory=dict)
    domain_ontology: dict[str, Any] = field(default_factory=dict)
    semantic_objects: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_default_resources(cls) -> "OntologyAssets":
        dictionary_dir = resource_paths.lexical_mention_dictionaries_dir()
        ontology_dir = resource_paths.ontology_resource_dir()
        return cls.from_dictionary_dir(dictionary_dir, ontology_dir=ontology_dir)

    @classmethod
    def from_dictionary_dir(cls, dictionary_dir: Path, *, ontology_dir: Path | None = None) -> "OntologyAssets":
        entries: list[DictionaryEntry] = []
        for file_name in MENTION_DICTIONARY_FILES:
            path = dictionary_dir / file_name
            if not path.exists():
                continue
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for item in payload.get("entries", []):
                if not isinstance(item, dict) or "canonical_id" not in item:
                    continue
                entries.append(_entry_from_mapping(item, dictionary=path.stem))
        return cls(
            entries=tuple(entries),
            mention_to_ontology=_load_yaml(ontology_dir / "mention_to_ontology.yaml") if ontology_dir else {},
            domain_ontology=_load_yaml(ontology_dir / "domain_ontology.yaml") if ontology_dir else {},
            semantic_objects=_load_yaml(ontology_dir / "semantic_objects.yaml") if ontology_dir else {},
        )

    @property
    def by_id(self) -> dict[str, DictionaryEntry]:
        return {entry.canonical_id: entry for entry in self.entries}

    def relation(self, relation_id: str) -> DictionaryEntry:
        entry = self.by_id[relation_id]
        if entry.mention_type != "relation_predicate":
            raise KeyError(f"{relation_id} is not a relation predicate")
        return entry

    def attribute(self, attribute_id: str) -> DictionaryEntry:
        entry = self.by_id[attribute_id]
        if entry.mention_type != "attribute":
            raise KeyError(f"{attribute_id} is not an attribute")
        return entry


def _entry_from_mapping(item: dict[str, Any], *, dictionary: str) -> DictionaryEntry:
    metadata = {key: value for key, value in item.items() if key not in {"canonical_id", "mention_type", "surface_forms", "description"}}
    metadata.setdefault("dictionary", dictionary)
    return DictionaryEntry(
        canonical_id=str(item["canonical_id"]),
        mention_type=str(item.get("mention_type", "")),
        surface_forms=tuple(str(value) for value in item.get("surface_forms", [])),
        description=str(item.get("description", "")),
        metadata=metadata,
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        return {}
    return payload
