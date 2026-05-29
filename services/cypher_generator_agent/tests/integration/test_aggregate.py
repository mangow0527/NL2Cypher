from __future__ import annotations

from services.cypher_generator_agent.app.core.pipeline import run_pipeline


def test_pipeline_generates_metric_aggregate_for_firewall_count() -> None:
    result = run_pipeline(
        question="全网有多少台防火墙",
        qa_id="gq-008",
        generation_run_id="run-aggregate-firewall",
    )

    assert result.status == "generated"
    assert result.dsl["query_shape"] == "metric_aggregate"
    assert result.dsl["operations"][0]["metric_name"] == "device_count"
    assert result.dsl["operations"][0]["filters"][0]["value"]["normalized"] == "firewall"
    assert result.cypher == (
        "MATCH (ne:NetworkElement)\n"
        "WHERE ne.elem_type = 'firewall'\n"
        "RETURN count(ne) AS device_count"
    )
    trace = result.trace
    assert trace["final_status"] == "generated"
    assert trace["final_outputs"]["cypher"] == result.cypher


def test_pipeline_generates_ad_hoc_aggregate_for_port_status_count() -> None:
    result = run_pipeline(
        question="按状态统计端口数量",
        qa_id="gq-010",
        generation_run_id="run-aggregate-port-status",
    )

    assert result.status == "generated"
    assert result.dsl["query_shape"] == "ad_hoc_aggregate"
    assert result.dsl["operations"][0]["measures"][0]["alias"] == "port_count"
    assert result.cypher == (
        "MATCH (port:Port)\n"
        "RETURN port.status AS status, count(port.id) AS port_count"
    )
