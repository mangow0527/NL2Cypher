from __future__ import annotations

from typing import Literal


GenerationFailureReason = Literal[
    "empty_output",
    "no_cypher_found",
    "wrapped_in_markdown",
    "wrapped_in_json",
    "contains_explanation",
    "multiple_statements",
    "unbalanced_brackets",
    "unclosed_string",
    "write_operation",
    "unsupported_call",
    "unsupported_start_clause",
    "unauthorized_schema_reference",
    "logical_plan_mismatch",
    "semantic_match_rejected",
    "path_planning_failed",
    "cypher_fallback_cannot_generate",
    "cypher_syntax_invalid",
    "cypher_readonly_violation",
    "cypher_schema_reference_invalid",
    "compiler_shape_mismatch",
    "target_dialect_static_error",
    "unsupported_query_shape",
    "coverage_failure",
    "literal_unresolved",
    "repair_binding_oscillation",
    "question_decomposer_schema_invalid",
]

ServiceFailureReason = Literal[
    "knowledge_context_unavailable",
    "semantic_contract_unaligned",
    "model_invocation_failed",
    "testing_agent_submission_failed",
]

GenerationFinalStatus = Literal[
    "generated",
    "clarification_required",
    "unsupported_query_shape",
    "generation_failed",
    "service_failed",
]

GenerationSubmissionStatus = Literal["submitted_to_testing"]
