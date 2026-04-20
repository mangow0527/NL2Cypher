from __future__ import annotations

from services.testing_agent.app.evaluation import evaluate_submission, extract_labels
from contracts.models import TuGraphExecutionResult


def test_result_correctness_ignores_order_when_question_has_no_ordering_requirement():
    execution = TuGraphExecutionResult(
        success=True,
        rows=[{"id": "b"}, {"id": "a"}],
        row_count=2,
        error_message=None,
        elapsed_ms=10,
    )

    result = evaluate_submission(
        question="查询两个设备ID",
        expected_cypher="MATCH (n:NetworkElement) RETURN n.id AS id LIMIT 2",
        expected_answer=[{"id": "a"}, {"id": "b"}],
        actual_cypher="MATCH (n:NetworkElement) RETURN n.id AS id LIMIT 2",
        execution=execution,
        loaded_knowledge_tags=[],
    )

    assert result.dimensions.result_correctness == "pass"
    assert result.metrics is not None
    assert result.metrics.result_correctness.result_set_f1 == 1.0
    assert result.metrics.result_correctness.order_sensitive is False


def test_result_correctness_penalizes_partial_row_recall():
    execution = TuGraphExecutionResult(
        success=True,
        rows=[{"id": "a"}, {"id": "b"}],
        row_count=2,
        error_message=None,
        elapsed_ms=10,
    )

    result = evaluate_submission(
        question="查询三个设备ID",
        expected_cypher="MATCH (n:NetworkElement) RETURN n.id AS id LIMIT 3",
        expected_answer=[{"id": "a"}, {"id": "b"}, {"id": "c"}],
        actual_cypher="MATCH (n:NetworkElement) RETURN n.id AS id LIMIT 2",
        execution=execution,
        loaded_knowledge_tags=[],
    )

    assert result.dimensions.result_correctness == "fail"
    assert result.metrics is not None
    assert round(result.metrics.result_correctness.result_set_precision, 2) == 1.0
    assert round(result.metrics.result_correctness.result_set_recall, 2) == 0.67
    assert round(result.metrics.result_correctness.result_set_f1, 2) == 0.8


def test_order_requirement_is_treated_as_order_sensitive():
    execution = TuGraphExecutionResult(
        success=True,
        rows=[{"id": "a"}, {"id": "b"}],
        row_count=2,
        error_message=None,
        elapsed_ms=10,
    )

    result = evaluate_submission(
        question="按ID降序查询两个设备ID",
        expected_cypher="MATCH (n:NetworkElement) RETURN n.id AS id ORDER BY id DESC LIMIT 2",
        expected_answer=[{"id": "b"}, {"id": "a"}],
        actual_cypher="MATCH (n:NetworkElement) RETURN n.id AS id LIMIT 2",
        execution=execution,
        loaded_knowledge_tags=[],
    )

    assert result.metrics is not None
    assert result.metrics.result_correctness.order_sensitive is True
    assert result.metrics.question_alignment.ordering_limit_match_score == 0.5


def test_evaluation_summary_exposes_overall_score_and_projection_signal():
    execution = TuGraphExecutionResult(
        success=True,
        rows=[{"id": "tun-1", "name": "Tunnel 1"}],
        row_count=1,
        error_message=None,
        elapsed_ms=10,
    )

    result = evaluate_submission(
        question="查询带宽大于等于1的隧道信息",
        expected_cypher="MATCH (a:Tunnel) WHERE a.bandwidth >= 1 RETURN a LIMIT 1",
        expected_answer=[{"a": {"id": "tun-1", "name": "Tunnel 1", "bandwidth": 1000}}],
        actual_cypher="MATCH (a:Tunnel) WHERE a.bandwidth >= 1 RETURN a.id AS id, a.name AS name LIMIT 1",
        execution=execution,
        loaded_knowledge_tags=[],
    )

    assert result.metrics is not None
    assert 0.0 <= result.overall_score <= 1.0
    assert 0.0 <= result.metrics.question_alignment.projection_match_score < 1.0


def test_result_correctness_ignores_entity_alias_when_returned_node_is_same():
    tunnel = {
        "identity": 40,
        "label": "Tunnel",
        "properties": {"id": "tun-mpls-te-1000", "bandwidth": 1000.0},
    }
    execution = TuGraphExecutionResult(
        success=True,
        rows=[{"t": tunnel}],
        row_count=1,
        error_message=None,
        elapsed_ms=10,
    )

    result = evaluate_submission(
        question="查询带宽大于等于1的隧道信息",
        expected_cypher="MATCH (a:Tunnel) WHERE a.bandwidth >= 1 RETURN a LIMIT 1",
        expected_answer=[{"a": tunnel}],
        actual_cypher="MATCH (t:Tunnel) WHERE t.bandwidth >= 1 RETURN t LIMIT 1",
        execution=execution,
        loaded_knowledge_tags=[],
    )

    assert result.metrics is not None
    assert result.dimensions.result_correctness == "pass"
    assert result.metrics.result_correctness.result_set_f1 == 1.0
    assert result.metrics.question_alignment.projection_match_score == 1.0


def test_result_correctness_ignores_related_entity_alias_when_key_and_node_are_same():
    port = {
        "identity": 70,
        "label": "Port",
        "properties": {"id": "port-tun-mpls-te-1000-d0", "name": "Port_0002"},
    }
    execution = TuGraphExecutionResult(
        success=True,
        rows=[{"key": "link-tun-mpls-te-1000-0", "p": port}],
        row_count=1,
        error_message=None,
        elapsed_ms=10,
    )

    result = evaluate_submission(
        question="查询5条链路及其目的端口信息。",
        expected_cypher="MATCH (a:Link)-[:LINK_DST]->(b:Port) RETURN a.id AS key, b LIMIT 1",
        expected_answer=[{"key": "link-tun-mpls-te-1000-0", "b": port}],
        actual_cypher="MATCH (l:Link)-[:LINK_DST]->(p:Port) RETURN l.id AS key, p LIMIT 1",
        execution=execution,
        loaded_knowledge_tags=[],
    )

    assert result.metrics is not None
    assert result.dimensions.result_correctness == "pass"
    assert result.metrics.result_correctness.result_set_f1 == 1.0
    assert result.metrics.question_alignment.projection_match_score == 1.0


def test_label_extraction_does_not_treat_relationship_type_as_label():
    assert extract_labels("MATCH (l:Link)-[:LINK_DST]->(p:Port) RETURN l.id AS key, p LIMIT 5") == [
        "Link",
        "Port",
    ]
