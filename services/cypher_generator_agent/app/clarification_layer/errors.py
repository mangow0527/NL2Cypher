from __future__ import annotations

from typing import Any

from services.cypher_generator_agent.app.infrastructure.errors import OntologyGenerationError


class ClarificationNeeded(OntologyGenerationError):
    """The user question is valid input, but needs clarification before planning."""

    def __init__(
        self,
        *,
        stage: str,
        message: str,
        clarification: dict[str, Any],
        partial_trace: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(stage=stage, message=message, payload=clarification, partial_trace=partial_trace)
        self.clarification = dict(clarification)
