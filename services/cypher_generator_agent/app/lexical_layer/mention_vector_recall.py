from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Protocol

import httpx

from services.cypher_generator_agent.app.ontology_layer.assets import OntologyAssets
from services.cypher_generator_agent.app.ontology_layer.models import DictionaryEntry


DEFAULT_MENTION_COLLECTION = "nl2cypher_mention_candidates_v1"
DEFAULT_MENTION_SEARCH_ENDPOINT = "/api/v1/mention/search"


class MentionVectorSearchError(RuntimeError):
    pass


class MentionVectorRetriever(Protocol):
    provider: str

    def search(
        self,
        fragment: str,
        *,
        expected_mention_type: str | None,
        top_k: int,
    ) -> list["MentionVectorCandidate"]:
        ...


@dataclass(frozen=True)
class MentionVectorCandidate:
    id: str
    text: str
    canonical_id: str
    mention_type: str
    surface: str
    score: float
    metadata: dict[str, Any]

    @classmethod
    def from_hit(cls, hit: dict[str, Any]) -> "MentionVectorCandidate":
        metadata = _dict_value(hit, "metadata")
        return cls(
            id=_required_text(hit, "id", "candidate_id", "fragment_key"),
            text=_required_text(hit, "text", "content", "sample_text"),
            canonical_id=_required_text(hit, "canonical_id", metadata=metadata),
            mention_type=_required_text(hit, "mention_type", metadata=metadata),
            surface=_required_text(hit, "surface", metadata=metadata),
            score=_score(hit),
            metadata=metadata,
        )


@dataclass(frozen=True)
class MentionVectorDocument:
    id: str
    text: str
    canonical_id: str
    mention_type: str
    surface: str
    description: str
    metadata: dict[str, Any]

    def to_rag_fragment(self) -> dict[str, Any]:
        metadata = {
            **self.metadata,
            "canonical_id": self.canonical_id,
            "mention_type": self.mention_type,
            "surface": self.surface,
        }
        return {
            "id": self.id,
            "type": "mention_candidate",
            "title": f"{self.canonical_id} / {self.surface}",
            "content": self.text,
            "tags": ["mention_candidate", self.mention_type],
            "metadata": metadata,
        }


class RagMentionVectorRetriever:
    provider = "rag_mention_vector"

    def __init__(
        self,
        *,
        base_url: str,
        collection: str = DEFAULT_MENTION_COLLECTION,
        endpoint_path: str = DEFAULT_MENTION_SEARCH_ENDPOINT,
        timeout_seconds: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.collection = collection
        self.endpoint_path = endpoint_path if endpoint_path.startswith("/") else f"/{endpoint_path}"
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    @classmethod
    def from_environment(cls) -> "RagMentionVectorRetriever | None":
        store = _settings_value("NL2CYPHER_MENTION_EMBEDDING_STORE", "").strip().lower()
        if store not in {"rag", "rag_vector", "rag_vector_store"}:
            return None
        base_url = (
            _settings_value("NL2CYPHER_MENTION_RAG_SERVICE_URL")
            or _settings_value("CYPHER_GENERATOR_AGENT_RAG_SERVICE_URL")
            or ""
        ).strip()
        if not base_url:
            return None
        return cls(
            base_url=base_url,
            collection=_settings_value("NL2CYPHER_MENTION_RAG_COLLECTION", DEFAULT_MENTION_COLLECTION),
            endpoint_path=_settings_value("NL2CYPHER_MENTION_RAG_ENDPOINT", DEFAULT_MENTION_SEARCH_ENDPOINT),
            timeout_seconds=float(_settings_value("NL2CYPHER_MENTION_RAG_TIMEOUT_SECONDS", "60")),
        )

    def search(
        self,
        fragment: str,
        *,
        expected_mention_type: str | None,
        top_k: int,
    ) -> list[MentionVectorCandidate]:
        if not fragment.strip():
            return []
        filters: dict[str, object] = {"enabled": True}
        if expected_mention_type:
            filters["mention_type"] = expected_mention_type
        request_payload: dict[str, object] = {
            "query": fragment,
            "top_k": top_k,
            "collection": self.collection,
            "filters": filters,
        }
        try:
            with httpx.Client(timeout=self.timeout_seconds, transport=self.transport) as client:
                response = client.post(f"{self.base_url}{self.endpoint_path}", json=request_payload)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise MentionVectorSearchError(f"RAG mention search failed: {exc}") from exc
        return _parse_candidates(payload)


def build_mention_vector_documents(assets: OntologyAssets) -> tuple[MentionVectorDocument, ...]:
    entries_by_id = assets.by_id
    documents: dict[str, MentionVectorDocument] = {}
    for entry in assets.entries:
        for document in _documents_for_entry(entry, entries_by_id):
            documents.setdefault(document.id, document)
    return tuple(sorted(documents.values(), key=lambda item: item.id))


def _documents_for_entry(
    entry: DictionaryEntry,
    entries_by_id: dict[str, DictionaryEntry],
) -> tuple[MentionVectorDocument, ...]:
    if entry.mention_type == "synonym":
        return ()
    if entry.mention_type != "synonym_group":
        return tuple(_document_for_surface(entry, surface, extra_metadata={}) for surface in entry.surface_forms if surface)

    documents: list[MentionVectorDocument] = []
    applied_to = entry.metadata.get("applied_to", ())
    targets = applied_to if isinstance(applied_to, (list, tuple)) else ()
    for target_id in targets:
        target = entries_by_id.get(str(target_id))
        if target is None:
            continue
        for surface in entry.surface_forms:
            if not surface:
                continue
            documents.append(
                _document_for_surface(
                    target,
                    surface,
                    extra_metadata={
                        "dictionary": entry.metadata.get("dictionary", "synonyms"),
                        "via_synonym_group": entry.canonical_id,
                    },
                )
            )
    return tuple(documents)


def _document_for_surface(
    entry: DictionaryEntry,
    surface: str,
    *,
    extra_metadata: dict[str, Any],
) -> MentionVectorDocument:
    text_parts = [surface, entry.canonical_id, entry.description]
    for value in entry.metadata.get("surface_forms", ()):
        text_parts.append(str(value))
    text = " ".join(part for part in text_parts if part)
    metadata = {**entry.metadata, **extra_metadata}
    return MentionVectorDocument(
        id=f"mention.{entry.canonical_id}.{surface}",
        text=text,
        canonical_id=entry.canonical_id,
        mention_type=entry.mention_type,
        surface=surface,
        description=entry.description,
        metadata=metadata,
    )


def _parse_candidates(payload: Any) -> list[MentionVectorCandidate]:
    if not isinstance(payload, dict):
        raise MentionVectorSearchError("RAG mention search response must be a JSON object")
    hits = payload.get("hits")
    if hits is None:
        hits = payload.get("matches")
    if hits is None:
        hits = payload.get("results")
    if not isinstance(hits, list):
        raise MentionVectorSearchError("RAG mention search response missing hits list")
    candidates: list[MentionVectorCandidate] = []
    for hit in hits:
        if not isinstance(hit, dict):
            raise MentionVectorSearchError("RAG mention search hit must be a JSON object")
        candidates.append(MentionVectorCandidate.from_hit(hit))
    return candidates


def _required_text(hit: dict[str, Any], *keys: str, metadata: dict[str, Any] | None = None) -> str:
    value = _hit_value(hit, *keys)
    if value is None and metadata is not None:
        for key in keys:
            value = metadata.get(key)
            if value is not None:
                break
    text = "" if value is None else str(value).strip()
    if not text:
        raise MentionVectorSearchError(f"RAG mention search hit missing {'/'.join(keys)}")
    return text


def _score(hit: dict[str, Any]) -> float:
    value = _hit_value(hit, "score", "similarity")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise MentionVectorSearchError("RAG mention search hit missing numeric score") from exc


def _dict_value(hit: dict[str, Any], key: str) -> dict[str, Any]:
    value = hit.get(key)
    return dict(value) if isinstance(value, dict) else {}


def _hit_value(hit: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in hit:
            return hit[key]
    for nested_key in ("payload", "metadata"):
        nested_value = hit.get(nested_key)
        if not isinstance(nested_value, dict):
            continue
        for key in keys:
            if key in nested_value:
                return nested_value[key]
    return None


def _settings_value(name: str, default: str | None = None) -> str:
    value = os.getenv(name)
    if value is not None:
        return value
    dotenv_value = _dotenv_values().get(name)
    if dotenv_value is not None:
        return dotenv_value
    return "" if default is None else default


def _dotenv_values() -> dict[str, str]:
    path = Path(".env")
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        values[key] = value
    return values
