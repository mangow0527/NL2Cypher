from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from services.cypher_generator_agent.app.binding.models import (
    BindingPlan,
    CandidateBinding,
    FilterBinding,
    LiteralBinding,
    MetricBinding,
    VertexBinding,
)
from services.cypher_generator_agent.app.dsl.builder import RestrictedDslBuilder
from services.cypher_generator_agent.app.dsl.parser import parse_restricted_query_dsl
from services.cypher_generator_agent.app.semantic_model import GraphSemanticRegistry, load_graph_semantic_model


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "network_topology_graph_model.yaml"


@pytest.fixture(scope="module")
def registry() -> GraphSemanticRegistry:
    return load_graph_semantic_model(FIXTURE_PATH).registry


def test_metric_aggregate_plan_builds_metric_dsl(registry: GraphSemanticRegistry) -> None:
    literal = LiteralBinding(
        raw_literal="防火墙",
        resolved=True,
        value="firewall",
        normalized_value="firewall",
        match_type="value_synonym",
        confidence=1.0,
        owner="NetworkElement",
        property="elem_type",
    )
    plan = BindingPlan(
        query_shape="metric_aggregate",
        metric_bindings=[MetricBinding(name="device_count", candidate=_candidate("metric", "device_count"))],
        literal_bindings=[literal],
        filters=[
            FilterBinding(
                owner="NetworkElement",
                property="elem_type",
                operator="eq",
                raw_literal="防火墙",
                value="firewall",
                literal=literal,
            )
        ],
        projection=[{"alias": "device_count", "source": "metric.device_count"}],
    )

    dsl = RestrictedDslBuilder(registry).build(
        plan,
        source_question="全网有多少台防火墙",
        query_id="q-device-count-firewall",
    )

    assert dsl == {
        "schema_version": "restricted_query_dsl_v1",
        "query_id": "q-device-count-firewall",
        "query_shape": "metric_aggregate",
        "source_question": "全网有多少台防火墙",
        "bindings": {"metric": {"metric_name": "device_count"}},
        "operations": [
            {
                "op": "metric_aggregate",
                "metric_name": "device_count",
                "group_by": [],
                "filters": [
                    {
                        "target": "ne",
                        "property": {"owner": "NetworkElement", "name": "elem_type"},
                        "operator": "eq",
                        "value": {
                            "raw": "防火墙",
                            "normalized": "firewall",
                            "resolver_match_type": "value_synonym",
                        },
                    }
                ],
            }
        ],
        "projection": {"items": [{"alias": "device_count", "source": "metric.device_count"}]},
    }
    ast = parse_restricted_query_dsl(dsl, registry)
    assert ast.operations[0].metric_name == "device_count"
    assert ast.operations[0].filters[0].target.alias == "ne"


def test_ad_hoc_aggregate_plan_builds_aggregate_dsl(registry: GraphSemanticRegistry) -> None:
    plan = BindingPlan(
        query_shape="ad_hoc_aggregate",
        vertex_bindings=[VertexBinding(name="Port", candidate=_candidate("vertex", "Port"))],
        group_by=[
            {
                "alias": "status",
                "target": "port",
                "property": {"owner": "Port", "name": "status"},
            }
        ],
        measures=[
            {
                "alias": "port_count",
                "function": "count",
                "target": "port",
                "property": {"owner": "Port", "name": "id"},
            }
        ],
        projection=[
            {"alias": "status", "source": "group.status"},
            {"alias": "port_count", "source": "measure.port_count"},
        ],
    )

    dsl = RestrictedDslBuilder(registry).build(
        plan,
        source_question="按状态统计端口数量",
        query_id="q-port-count-by-status",
    )

    assert dsl["bindings"] == {"port": {"vertex_name": "Port"}}
    assert dsl["operations"] == [
        {
            "op": "aggregate",
            "group_by": [
                {
                    "alias": "status",
                    "target": "port",
                    "property": {"owner": "Port", "name": "status"},
                }
            ],
            "measures": [
                {
                    "alias": "port_count",
                    "function": "count",
                    "target": "port",
                    "property": {"owner": "Port", "name": "id"},
                }
            ],
        }
    ]
    ast = parse_restricted_query_dsl(dsl, registry)
    assert ast.operations[0].measures[0].alias == "port_count"


def _candidate(semantic_type: str, semantic_id: str) -> CandidateBinding:
    return CandidateBinding(
        semantic_type=semantic_type,
        semantic_id=semantic_id,
        semantic_name=semantic_id,
        score=1.0,
        match_type="exact",
    )
