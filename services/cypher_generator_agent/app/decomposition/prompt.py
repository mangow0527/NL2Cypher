from __future__ import annotations

from typing import Any

from .models import QUESTION_DECOMPOSITION_SCHEMA_VERSION, question_decomposition_json_schema


def build_question_decomposition_prompt(question: str) -> str:
    return "\n".join(
        [
            "You are the Question Decomposer for a graph-native Cypher generation pipeline.",
            f"Return only structured output for schema {QUESTION_DECOMPOSITION_SCHEMA_VERSION}.",
            "Always include intent_type and output_shape from the allowed enum values.",
            "Use only the user's surface-language terms. Do not output graph labels, edge names, property names, metrics, path pattern ids, or Cypher.",
            "Keep literal_candidates graph-independent objects with required text, kind_hint, and attached_to.",
            "Classify every meaningful surface term into exactly one bucket:",
            "- substantive_terms: domain concepts, metrics, entities, relations, states, and actions.",
            "- stopword_terms: polite phrasing or filler that should not drive retrieval.",
            "- modality_terms: approximations, uncertainty, or soft constraints.",
            "- time_terms: temporal expressions.",
            "- unparsed_terms: text you cannot confidently classify.",
            "Preserve classifiers and attachment words from the user's question as surface terms; downstream code will normalize them.",
            "If the question is missing the referent for a pronoun or deictic expression, return result_type=clarification_required with a concise clarification_question.",
            "Do not generate Cypher, do not explain, and do not return markdown.",
            f"Question: {question}",
        ]
    )


def build_question_decomposition_schema() -> dict[str, Any]:
    return question_decomposition_json_schema()
