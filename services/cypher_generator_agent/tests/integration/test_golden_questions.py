from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from services.cypher_generator_agent.app.core.pipeline import run_pipeline
from services.cypher_generator_agent.app.dsl.parser import parse_restricted_query_dsl
from services.cypher_generator_agent.app.semantic_model.loader import load_graph_semantic_model


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"
GOLDEN_QUESTIONS_PATH = FIXTURE_DIR / "golden_questions.yaml"
MODEL_PATH = FIXTURE_DIR / "network_topology_graph_model.yaml"

FULL_REGRESSION_QUERY_SHAPES = {
    "single_hop_traversal",
    "named_path_pattern",
    "variable_path_traversal",
    "metric_aggregate",
    "ad_hoc_aggregate",
    "top_n",
    "two_step_aggregate",
}
REGRESSION_SCOPES = {"smoke", "full"}


def _regression_cases() -> list[dict[str, Any]]:
    return [
        case
        for case in _load_yaml(GOLDEN_QUESTIONS_PATH)["golden_questions"]
        if case.get("regression_scope") in REGRESSION_SCOPES
    ]


def _smoke_regression_cases() -> list[dict[str, Any]]:
    return [
        case
        for case in _load_yaml(GOLDEN_QUESTIONS_PATH)["golden_questions"]
        if case.get("regression_scope") == "smoke"
    ]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _read_text_fixture(path: Path) -> str:
    return path.read_text(encoding="utf-8").rstrip("\n")


def test_full_golden_regression_matrix_covers_generated_query_shapes() -> None:
    cases = _regression_cases()
    generated_cases = [case for case in cases if case["expected_status"] == "generated"]
    non_success_cases = [case for case in cases if case["expected_status"] != "generated"]

    assert {case["query_shape"] for case in generated_cases} == FULL_REGRESSION_QUERY_SHAPES
    assert {case["expected_reason_code"] for case in non_success_cases} >= {
        "coverage_failure",
        "literal_unresolved",
    }
    assert {case["id"] for case in _smoke_regression_cases()}
    for case in generated_cases:
        assert case["expected_dsl_fixture"]
        assert case["expected_cypher_fixture"]
        assert (FIXTURE_DIR / case["expected_dsl_fixture"]).is_file()
        assert (FIXTURE_DIR / case["expected_cypher_fixture"]).is_file()


def test_golden_regression_has_ci_workflow_entrypoint() -> None:
    workflow_path = Path(__file__).resolve().parents[4] / ".github" / "workflows" / "cypher-generator-agent.yml"

    assert workflow_path.is_file()
    workflow_text = workflow_path.read_text(encoding="utf-8")
    assert "workflow_dispatch" in workflow_text
    assert "test_golden_questions.py" in workflow_text
    assert "services/cypher_generator_agent/tests" in workflow_text
    assert "PYTHONPATH: ." in workflow_text


@pytest.mark.parametrize("case", _regression_cases(), ids=lambda case: case["id"])
def test_full_golden_regression_case_matches_expected_dsl_and_cypher(
    case: dict[str, Any],
) -> None:
    _assert_golden_case(case)


@pytest.mark.parametrize("case", _smoke_regression_cases(), ids=lambda case: case["id"])
def test_smoke_golden_regression_case_matches_expected_contract(
    case: dict[str, Any],
) -> None:
    assert case["ci_smoke"] is True
    _assert_golden_case(case)


def _assert_golden_case(case: dict[str, Any]) -> None:
    generation_run_id = f"golden-{case['id']}"
    output = run_pipeline(
        question=case["question"],
        qa_id=case["id"],
        generation_run_id=generation_run_id,
    )

    assert output.status == case["expected_status"]
    assert output.trace["question_id"] == case["id"]
    assert output.trace["generation_run_id"] == generation_run_id
    assert output.trace["final_status"] == output.status

    if case["expected_status"] != "generated":
        assert output.cypher is None
        assert output.dsl is None
        if case["expected_status"] == "clarification_required":
            assert output.failure is None
            assert output.clarification is not None
            assert output.trace["final_outputs"]["clarification"]["question"] == output.clarification.question
            assert _last_repair_reason(output.trace) == case["expected_reason_code"]
            return
        assert output.failure is not None
        assert output.failure.reason == case["expected_reason_code"]
        assert output.trace["final_outputs"]["failure"]["reason"] == case["expected_reason_code"]
        return

    assert output.failure is None
    expected_dsl = _load_json(FIXTURE_DIR / case["expected_dsl_fixture"])
    expected_cypher = _read_text_fixture(FIXTURE_DIR / case["expected_cypher_fixture"])
    assert output.dsl == expected_dsl
    assert output.cypher == expected_cypher

    registry = load_graph_semantic_model(MODEL_PATH).registry
    ast = parse_restricted_query_dsl(output.dsl, registry)
    assert ast.query_shape.value == case["query_shape"]
    assert output.trace["final_status"] == "generated"
    assert output.trace["final_outputs"]["dsl"] == output.dsl
    assert output.trace["final_outputs"]["cypher"] == output.cypher


def _last_repair_reason(trace: dict[str, object]) -> str:
    for stage in reversed(trace["stages"]):
        if stage["stage"] != "repair_controller":
            continue
        return stage["output_ref"]["value"]["reason_code"]
    raise AssertionError("missing repair_controller stage")
