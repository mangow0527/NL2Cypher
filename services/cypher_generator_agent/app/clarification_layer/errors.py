from __future__ import annotations

from typing import Any

from services.cypher_generator_agent.app.infrastructure.errors import OntologyGenerationError


class ClarificationNeeded(OntologyGenerationError):
    """The user question is valid input, but needs clarification before planning."""

    def __init__(self, *, stage: str, message: str, clarification: dict[str, Any]) -> None:
        super().__init__(stage=stage, message=message, payload=clarification)
        self.clarification = dict(clarification)
