from __future__ import annotations

from services.testing_agent.app.grammar import Antlr4CypherParserAdapter
from services.testing_agent.app.comparison import compare_answers, normalize_value
from services.testing_agent.app.models import ExecutionResult
from services.testing_agent.app.summary import build_execution_accuracy


def test_strict_compare_ignores_order_when_not_order_sensitive():
    strict = compare_answers(
        golden_answer=[{"id": "a"}, {"id": "b"}],
        actual_answer=[{"id": "b"}, {"id": "a"}],
        order_sensitive=False,
    )

    assert strict.status == "pass"
    assert strict.order_sensitive is False
    assert strict.evidence is None


def test_strict_compare_marks_order_mismatch_for_order_sensitive_results():
    strict = compare_answers(
        golden_answer=[{"id": "a"}, {"id": "b"}],
        actual_answer=[{"id": "b"}, {"id": "a"}],
        order_sensitive=True,
    )

    assert strict.status == "fail"
    assert strict.evidence is not None
    assert strict.evidence.diff.order_mismatch is True


def test_normalize_value_canonicalizes_graph_entities_without_internal_identity():
    normalized = normalize_value(
        {
            "identity": 40,
            "label": "Tunnel",
            "properties": {"bandwidth": 1000.0, "id": "tun-1"},
        }
    )

    assert normalized == {
        "__type__": "node",
        "labels": ["Tunnel"],
        "properties": {"bandwidth": 1000.0, "id": "tun-1"},
    }


def test_execution_accuracy_uses_execution_failed_reason_when_execution_does_not_run_strict_compare():
    execution_accuracy = build_execution_accuracy(
        grammar_score=1,
        strict_check_status="not_run",
        semantic_check_status="not_run",
    )

    assert execution_accuracy.score == 0
    assert execution_accuracy.reason == "execution_failed"


def test_execution_result_top_level_shape_matches_design():
    execution = ExecutionResult(
        success=True,
        rows=[{"id": "a"}],
        row_count=1,
        error_message=None,
        elapsed_ms=5,
    )

    assert execution.model_dump() == {
        "success": True,
        "rows": [{"id": "a"}],
        "row_count": 1,
        "error_message": None,
        "elapsed_ms": 5,
    }


def test_antlr4_cypher_parser_adapter_accepts_basic_readonly_match_query():
    success, parser_error = Antlr4CypherParserAdapter().parse("MATCH (n) RETURN n")

    assert success is True
    assert parser_error is None


def test_antlr4_cypher_parser_adapter_rejects_obviously_invalid_query():
    success, parser_error = Antlr4CypherParserAdapter().parse("MATCH (n RETURN n")

    assert success is False
    assert parser_error is not None
