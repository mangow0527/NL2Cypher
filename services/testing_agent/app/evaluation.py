from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any, List, Sequence

from .models import (
    EvaluationDimensions,
    EvaluationMetrics,
    EvaluationSummary,
    QuestionAlignmentMetrics,
    ResultCorrectnessMetrics,
    SchemaAlignmentMetrics,
    SyntaxValidityMetrics,
    TuGraphExecutionResult,
    Verdict,
)
from .schema_profile import NETWORK_SCHEMA_V10_CONTEXT

LABEL_PATTERN = re.compile(r"\(\s*(?:[A-Za-z_][A-Za-z0-9_]*\s*)?:\s*([A-Za-z_][A-Za-z0-9_]*)")
REL_PATTERN = re.compile(r"\[:([A-Za-z_][A-Za-z0-9_]*)")
PROPERTY_PATTERN = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\.([A-Za-z_][A-Za-z0-9_]*)")
RETURN_CLAUSE_PATTERN = re.compile(r"\bRETURN\b(.*?)(?:\bORDER\s+BY\b|\bLIMIT\b|$)", re.IGNORECASE | re.DOTALL)
WHERE_PATTERN = re.compile(r"\bWHERE\b", re.IGNORECASE)
ORDER_BY_PATTERN = re.compile(r"\bORDER\s+BY\b", re.IGNORECASE)
LIMIT_PATTERN = re.compile(r"\bLIMIT\b", re.IGNORECASE)
COUNT_PATTERN = re.compile(r"\bcount\s*\(", re.IGNORECASE)
SUM_PATTERN = re.compile(r"\bsum\s*\(", re.IGNORECASE)
AVG_PATTERN = re.compile(r"\bavg\s*\(", re.IGNORECASE)
MIN_PATTERN = re.compile(r"\bmin\s*\(", re.IGNORECASE)
MAX_PATTERN = re.compile(r"\bmax\s*\(", re.IGNORECASE)

VALID_LABELS = {"NetworkElement", "Protocol", "Tunnel", "Service", "Port", "Fiber", "Link"}
VALID_RELATIONS = {
    "HAS_PORT",
    "FIBER_SRC",
    "FIBER_DST",
    "LINK_SRC",
    "LINK_DST",
    "TUNNEL_SRC",
    "TUNNEL_DST",
    "TUNNEL_PROTO",
    "PATH_THROUGH",
    "SERVICE_USES_TUNNEL",
}
AMBIGUOUS_TOKENS = ["随便", "看看", "情况", "这个", "那个", "帮我看看"]
ORDER_HINT_TOKENS = ["排序", "升序", "降序", "前", "top", "最高", "最低"]
OVERALL_SCORE_WEIGHTS = {
    "syntax_validity": 0.15,
    "schema_alignment": 0.20,
    "result_correctness": 0.40,
    "question_alignment": 0.25,
}


def normalize_json(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if (stripped.startswith("{") and stripped.endswith("}")) or (
            stripped.startswith("[") and stripped.endswith("]")
        ):
            try:
                return normalize_json(json.loads(stripped))
            except Exception:
                return value
        return value
    if isinstance(value, dict):
        return {k: normalize_json(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [normalize_json(item) for item in value]
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(normalize_json(value), ensure_ascii=False, sort_keys=True)


def _safe_divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _f1(precision: float, recall: float) -> float:
    return (2 * precision * recall / (precision + recall)) if precision + recall else 0.0


def _score_to_verdict(score: float) -> str:
    if score >= 0.95:
        return "pass"
    if score >= 0.4:
        return "partial"
    return "fail"


def _score_to_status(score: float) -> str:
    return "pass" if score >= 0.95 else "fail"


def extract_labels(cypher: str) -> List[str]:
    return sorted(set(LABEL_PATTERN.findall(cypher or "")))


def extract_relations(cypher: str) -> List[str]:
    return sorted(set(REL_PATTERN.findall(cypher or "")))


def extract_properties(cypher: str) -> List[str]:
    return sorted(set(PROPERTY_PATTERN.findall(cypher or "")))


def _extract_return_clause(cypher: str) -> str:
    match = RETURN_CLAUSE_PATTERN.search(cypher or "")
    if not match:
        return ""
    return " ".join(match.group(1).strip().split())


def _is_graph_entity(value: Any) -> bool:
    normalized = normalize_json(value)
    return (
        isinstance(normalized, dict)
        and "label" in normalized
        and ("identity" in normalized or "properties" in normalized)
    )


def _semantic_row_keys_from_row(row: Any) -> set[str]:
    normalized = normalize_json(row)
    if not isinstance(normalized, dict):
        return {"value"}
    keys: set[str] = set()
    for key, value in normalized.items():
        value = normalize_json(value)
        if _is_graph_entity(value):
            label = value.get("label") if isinstance(value, dict) else None
            keys.add(f"entity:{label or 'unknown'}")
        else:
            keys.add(str(key))
    return keys


def _semantic_row_keys(rows: Any) -> set[str]:
    if isinstance(rows, list) and rows:
        return _semantic_row_keys_from_row(rows[0])
    return _semantic_row_keys_from_row(rows)


def _semantic_normalize_row(row: Any) -> Any:
    normalized = normalize_json(row)
    if not isinstance(normalized, dict):
        return normalized

    scalar_fields: dict[str, Any] = {}
    graph_entities: list[Any] = []
    for key, value in normalized.items():
        value = normalize_json(value)
        if _is_graph_entity(value):
            graph_entities.append(value)
        else:
            scalar_fields[str(key)] = value

    if not graph_entities:
        return scalar_fields

    semantic_row: dict[str, Any] = dict(scalar_fields)
    semantic_row["__graph_entities__"] = sorted(_canonical_json(entity) for entity in graph_entities)
    return semantic_row


def _extract_entity_aliases_from_return(cypher: str) -> set[str]:
    clause = _extract_return_clause(cypher)
    if not clause:
        return set()
    aliases: set[str] = set()
    for item in clause.split(","):
        token = item.strip()
        if not token:
            continue
        lowered = token.lower()
        if " as " in lowered:
            continue
        if "." not in token and "(" not in token:
            aliases.add(token)
    return aliases


def _contains_aggregation(cypher: str) -> bool:
    lowered = cypher or ""
    return any(
        pattern.search(lowered)
        for pattern in [COUNT_PATTERN, SUM_PATTERN, AVG_PATTERN, MIN_PATTERN, MAX_PATTERN]
    )


def _contains_syntax_error(error_message: str | None) -> bool:
    return bool(error_message and "syntax" in error_message.lower())


def _contains_schema_error(error_message: str | None) -> bool:
    lowered = (error_message or "").lower()
    return "schema" in lowered or "label" in lowered or "property" in lowered


def _contains_filter(cypher: str) -> bool:
    return bool(WHERE_PATTERN.search(cypher or ""))


def _contains_limit(cypher: str) -> bool:
    return bool(LIMIT_PATTERN.search(cypher or ""))


def _contains_order_by(cypher: str) -> bool:
    return bool(ORDER_BY_PATTERN.search(cypher or ""))


def _is_order_sensitive(question: str, expected_cypher: str) -> bool:
    lowered_question = (question or "").lower()
    if _contains_order_by(expected_cypher):
        return True
    return any(token in lowered_question for token in ORDER_HINT_TOKENS)


def _set_match_score(actual: Sequence[str], expected: Sequence[str]) -> float:
    actual_set = set(actual)
    expected_set = set(expected)
    if not actual_set and not expected_set:
        return 1.0
    tp = len(actual_set & expected_set)
    precision = _safe_divide(tp, len(actual_set))
    recall = _safe_divide(tp, len(expected_set))
    return _f1(precision, recall)


def _normalize_rows(rows: Any) -> list[str]:
    if not isinstance(rows, list):
        return [_canonical_json(_semantic_normalize_row(rows))]
    return [_canonical_json(_semantic_normalize_row(item)) for item in rows]


def compare_answer(expected_answer: Any, execution: TuGraphExecutionResult, *, order_sensitive: bool) -> tuple[ResultCorrectnessMetrics, str]:
    actual_rows = execution.rows
    expected_rows = expected_answer if isinstance(expected_answer, list) else expected_answer

    actual_canonical_rows = _normalize_rows(actual_rows)
    expected_canonical_rows = _normalize_rows(expected_rows)

    execution_match_score = 1.0 if (
        actual_canonical_rows == expected_canonical_rows
        if order_sensitive
        else Counter(actual_canonical_rows) == Counter(expected_canonical_rows)
    ) else 0.0

    expected_counter = Counter(expected_canonical_rows)
    actual_counter = Counter(actual_canonical_rows)
    true_positive = sum(min(actual_counter[key], expected_counter[key]) for key in actual_counter)
    precision = _safe_divide(true_positive, sum(actual_counter.values()))
    recall = _safe_divide(true_positive, sum(expected_counter.values()))
    result_set_f1 = _f1(precision, recall)
    score = 0.3 * execution_match_score + 0.7 * result_set_f1

    detail = (
        f"expected_rows={_canonical_json(expected_rows)}; "
        f"actual_rows={_canonical_json(actual_rows)}; "
        f"order_sensitive={order_sensitive}"
    )
    metrics = ResultCorrectnessMetrics(
        score=score,
        verdict=_score_to_verdict(score),
        execution_match_score=execution_match_score,
        result_set_precision=precision,
        result_set_recall=recall,
        result_set_f1=result_set_f1,
        order_sensitive=order_sensitive,
        evidence=[] if execution_match_score == 1.0 else [detail],
    )
    return metrics, detail


def calculate_overall_score(metrics: EvaluationMetrics) -> float:
    return (
        OVERALL_SCORE_WEIGHTS["syntax_validity"] * metrics.syntax_validity.score
        + OVERALL_SCORE_WEIGHTS["schema_alignment"] * metrics.schema_alignment.score
        + OVERALL_SCORE_WEIGHTS["result_correctness"] * metrics.result_correctness.score
        + OVERALL_SCORE_WEIGHTS["question_alignment"] * metrics.question_alignment.score
    )


def _build_schema_metrics(
    actual_cypher: str,
    expected_cypher: str,
    execution: TuGraphExecutionResult,
) -> SchemaAlignmentMetrics:
    actual_labels = extract_labels(actual_cypher)
    actual_relations = extract_relations(actual_cypher)
    actual_properties = extract_properties(actual_cypher)
    expected_labels = extract_labels(expected_cypher)
    expected_relations = extract_relations(expected_cypher)
    expected_properties = extract_properties(expected_cypher)

    evidence: list[str] = []

    invalid_labels = [label for label in actual_labels if label not in VALID_LABELS]
    invalid_relations = [rel for rel in actual_relations if rel not in VALID_RELATIONS]
    if invalid_labels or invalid_relations:
        evidence.append(
            "Actual Cypher contains labels or relations outside network_schema_v10: "
            f"labels={actual_labels}, relations={actual_relations}"
        )
    if _contains_schema_error(execution.error_message):
        evidence.append(f"Execution reported schema error: {execution.error_message}")

    label_match_score = _set_match_score(actual_labels, expected_labels)
    relation_match_score = _set_match_score(actual_relations, expected_relations)
    property_match_score = _set_match_score(actual_properties, expected_properties)

    if invalid_labels:
        label_match_score = min(label_match_score, 0.0)
    if invalid_relations:
        relation_match_score = min(relation_match_score, 0.0)

    score = 0.3 * label_match_score + 0.4 * relation_match_score + 0.3 * property_match_score
    return SchemaAlignmentMetrics(
        score=score,
        verdict=_score_to_verdict(score),
        label_match_score=label_match_score,
        relation_match_score=relation_match_score,
        property_match_score=property_match_score,
        evidence=evidence,
    )


def _build_syntax_metrics(execution: TuGraphExecutionResult) -> SyntaxValidityMetrics:
    execution_success = execution.success and not bool(execution.error_message)
    parse_success = not _contains_syntax_error(execution.error_message)
    if execution_success:
        score = 1.0
    elif parse_success:
        score = 0.5
    else:
        score = 0.0
    evidence = [] if score >= 0.95 else [f"Execution failed or syntax invalid: {execution.error_message or 'unknown syntax issue'}"]
    return SyntaxValidityMetrics(
        score=score,
        verdict=_score_to_verdict(score),
        parse_success=parse_success,
        execution_success=execution_success,
        evidence=evidence,
    )


def _build_question_alignment_metrics(
    *,
    question: str,
    expected_cypher: str,
    actual_cypher: str,
    execution: TuGraphExecutionResult,
    expected_answer: Any,
    order_sensitive: bool,
) -> QuestionAlignmentMetrics:
    expected_labels = extract_labels(expected_cypher)
    actual_labels = extract_labels(actual_cypher)
    expected_relations = extract_relations(expected_cypher)
    actual_relations = extract_relations(actual_cypher)
    expected_properties = extract_properties(expected_cypher)
    actual_properties = extract_properties(actual_cypher)

    evidence: list[str] = []
    entity_match_score = _set_match_score(actual_labels, expected_labels)
    relation_path_match_score = _set_match_score(actual_relations, expected_relations)

    expected_has_filter = _contains_filter(expected_cypher)
    actual_has_filter = _contains_filter(actual_cypher)
    if expected_has_filter == actual_has_filter:
        filter_match_score = 1.0 if not expected_has_filter else _set_match_score(actual_properties, expected_properties)
    else:
        filter_match_score = 0.0

    expected_has_aggregation = _contains_aggregation(expected_cypher)
    actual_has_aggregation = _contains_aggregation(actual_cypher)
    aggregation_match_score = 1.0 if expected_has_aggregation == actual_has_aggregation else 0.0

    expected_row_keys = _semantic_row_keys(expected_answer)
    actual_row_keys = _semantic_row_keys(execution.rows)
    expected_entity_aliases = _extract_entity_aliases_from_return(expected_cypher)
    actual_entity_aliases = _extract_entity_aliases_from_return(actual_cypher)

    if expected_row_keys or actual_row_keys:
        projection_match_score = _set_match_score(sorted(actual_row_keys), sorted(expected_row_keys))
    elif expected_entity_aliases or actual_entity_aliases:
        projection_match_score = _set_match_score(sorted(actual_entity_aliases), sorted(expected_entity_aliases))
    else:
        projection_match_score = 1.0

    expected_has_limit = _contains_limit(expected_cypher)
    actual_has_limit = _contains_limit(actual_cypher)
    expected_has_order = _contains_order_by(expected_cypher)
    actual_has_order = _contains_order_by(actual_cypher)

    ordering_components = []
    if order_sensitive:
        ordering_components.append(1.0 if expected_has_order == actual_has_order else 0.0)
    if expected_has_limit or actual_has_limit:
        ordering_components.append(1.0 if expected_has_limit == actual_has_limit else 0.0)
    ordering_limit_match_score = (
        sum(ordering_components) / len(ordering_components) if ordering_components else 1.0
    )

    if any(token in question.lower() for token in AMBIGUOUS_TOKENS):
        evidence.append("Question contains ambiguous wording and lacks clear entity constraints.")
    if relation_path_match_score < 0.5 and expected_relations:
        evidence.append(
            f"Actual vs expected relation overlap too low: actual={actual_relations}, expected={expected_relations}"
        )
    if entity_match_score < 0.5 and expected_labels:
        evidence.append(
            f"Actual vs expected label overlap too low: actual={actual_labels}, expected={expected_labels}"
        )
    if projection_match_score < 0.95:
        evidence.append(
            f"Projection shape mismatch: expected_keys={sorted(expected_row_keys)}, actual_keys={sorted(actual_row_keys)}"
        )

    applicable_scores = [
        entity_match_score,
        relation_path_match_score,
        filter_match_score,
        aggregation_match_score,
        projection_match_score,
        ordering_limit_match_score,
    ]
    score = sum(applicable_scores) / len(applicable_scores)
    return QuestionAlignmentMetrics(
        score=score,
        verdict=_score_to_verdict(score),
        entity_match_score=entity_match_score,
        relation_path_match_score=relation_path_match_score,
        filter_match_score=filter_match_score,
        aggregation_match_score=aggregation_match_score,
        projection_match_score=projection_match_score,
        ordering_limit_match_score=ordering_limit_match_score,
        evidence=evidence,
    )


def evaluate_submission(
    question: str,
    expected_cypher: str,
    expected_answer: Any,
    actual_cypher: str,
    execution: TuGraphExecutionResult,
    loaded_knowledge_tags: List[str],
) -> EvaluationSummary:
    order_sensitive = _is_order_sensitive(question, expected_cypher)

    syntax_metrics = _build_syntax_metrics(execution)
    schema_metrics = _build_schema_metrics(actual_cypher, expected_cypher, execution)
    result_metrics, result_detail = compare_answer(expected_answer, execution, order_sensitive=order_sensitive)
    question_metrics = _build_question_alignment_metrics(
        question=question,
        expected_cypher=expected_cypher,
        actual_cypher=actual_cypher,
        execution=execution,
        expected_answer=expected_answer,
        order_sensitive=order_sensitive,
    )

    dimensions = EvaluationDimensions(
        syntax_validity=_score_to_status(syntax_metrics.score),
        schema_alignment=_score_to_status(schema_metrics.score),
        result_correctness=_score_to_status(result_metrics.score),
        question_alignment=_score_to_status(question_metrics.score),
    )
    metrics = EvaluationMetrics(
        syntax_validity=syntax_metrics,
        schema_alignment=schema_metrics,
        result_correctness=result_metrics,
        question_alignment=question_metrics,
    )

    evidence: list[str] = []
    evidence.extend(syntax_metrics.evidence)
    evidence.extend(schema_metrics.evidence)
    if result_metrics.verdict != "pass":
        evidence.append(f"Result mismatch: {result_detail}")
    evidence.extend(question_metrics.evidence)

    failures = [
        dimensions.syntax_validity,
        dimensions.schema_alignment,
        dimensions.result_correctness,
        dimensions.question_alignment,
    ].count("fail")

    if failures == 0:
        verdict: Verdict = "pass"
    elif failures == 4 or dimensions.syntax_validity == "fail":
        verdict = "fail"
    else:
        verdict = "partial_fail"

    if not evidence:
        evidence.append(f"Schema context used: {NETWORK_SCHEMA_V10_CONTEXT}")

    overall_score = calculate_overall_score(metrics)

    symptom = _build_symptom(verdict, dimensions, loaded_knowledge_tags)
    return EvaluationSummary(
        verdict=verdict,
        dimensions=dimensions,
        overall_score=overall_score,
        metrics=metrics,
        symptom=symptom,
        evidence=evidence,
    )


def _build_symptom(verdict: Verdict, dimensions: EvaluationDimensions, loaded_tags: List[str]) -> str:
    if verdict == "pass":
        return "Generated query is structurally aligned with the golden reference and returned the expected data."
    if dimensions.syntax_validity == "fail":
        return "Generated Cypher is not executable or has syntax issues."
    if dimensions.schema_alignment == "fail":
        return "Generated Cypher is not aligned with the graph schema."
    if dimensions.result_correctness == "fail" and dimensions.question_alignment == "pass":
        return "Generated Cypher is plausible but returned data inconsistent with the golden answer."
    if dimensions.question_alignment == "fail":
        return (
            "Question, generated Cypher, and golden intent are not semantically aligned; "
            f"loaded knowledge tags were {loaded_tags}."
        )
    return "Multiple quality dimensions failed and require deeper diagnosis."
