from __future__ import annotations

from typing import Any


class OntologyGenerationError(Exception):
    """Base error for ontology-based Cypher generation."""

    def __init__(self, *, stage: str, message: str, payload: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.stage = stage
        self.message = message
        self.payload = dict(payload or {})


class ResourceMissing(OntologyGenerationError):
    """The question references a concept outside the current assets."""


class EngineeringFailure(OntologyGenerationError):
    """The configured assets are inconsistent or incomplete."""
