from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from services.cypher_generator_agent.app.intent_layer.layer import IntentLayer
from services.cypher_generator_agent.app.intent_layer.models import IntentOutput
from services.cypher_generator_agent.app.intent_layer.recognition import IntentRecognitionResult
from services.cypher_generator_agent.app.lexical_layer.lexer import OntologyLexer
from services.cypher_generator_agent.app.ontology_layer.assets import OntologyAssets
from services.cypher_generator_agent.app.ontology_layer.object_role_selection import OntologyObjectRoleSelectionService
from services.cypher_generator_agent.app.ontology_layer.ontology_mapping import OntologyMappingService
from services.cypher_generator_agent.app.ontology_layer.ontology_path_selection import OntologyPathSelectionService
from services.cypher_generator_agent.app.ontology_layer.binding import OntologyBindingService
from services.cypher_generator_agent.app.ontology_layer.coreference import OntologyCoreferenceService
from services.cypher_generator_agent.app.ontology_layer.logical_planning import OntologyLogicalPlanningService


class _AcceptedRecognizer:
    def recognize(self, question: str, *, shape_signals=()) -> IntentRecognitionResult:
        return IntentRecognitionResult(
            primary_intent="record_retrieval_query",
            secondary_intent="related_record_query",
            confidence=0.91,
            source="rule",
            decision="accept",
        )


class _AllPathSubjectsSelector:
    def select(self, prompt_name: str, variables: dict[str, object]):
        class Selection:
            raw_response = "\n".join(
                f"选择 {candidate_id}：path_subject。理由：fixture"
                for candidate_id in variables.get("allowed_candidate_ids", [])
            )

        return Selection()


class _NoLlmSelector:
    def select(self, prompt_name: str, variables: dict[str, object]):
        raise AssertionError("single-candidate ontology path selection should not call the LLM")


class _SameInstanceCoreferenceSelector:
    def select(self, prompt_name: str, variables: dict[str, object]):
        class Selection:
            raw_response = "选择 C1。理由：fixture"

        assert prompt_name == "coreference_selection"
        return Selection()


class _TunnelNameBindingSelector:
    def select(self, prompt_name: str, variables: dict[str, object]):
        candidate_lines = str(variables.get("binding_candidate_list_with_ids") or "")
        match = re.search(r"(bc_[A-Za-z0-9_]+):[^\n]*attribute=Tunnel\.name", candidate_lines)
        if match is None:
            match = re.search(r"(bc_[A-Za-z0-9_]+):", candidate_lines)
        if match is None:
            raise AssertionError("binding fixture did not receive candidates")

        class Selection:
            raw_response = f"选择 {match.group(1)}。理由：fixture"

        assert prompt_name == "binding_selection"
        return Selection()


def test_step_2_intent_layer_independently_produces_intent_output() -> None:
    assets = OntologyAssets.from_default_resources()
    lexer_output = OntologyLexer.from_default_resources(assets).run("查询金牌服务使用的隧道名称")
    intent_layer = IntentLayer(recognizer=_AcceptedRecognizer())

    intent_output = intent_layer.run(
        core_question=lexer_output.question,
        shape_signals=lexer_output.shape_signals,
    )

    assert isinstance(intent_output, IntentOutput)
    assert intent_output.intent.primary == "record_retrieval_query"
    assert intent_output.intent.secondary == "related_record_query"
    assert intent_output.initial_shape["answer_type"].value == "attribute_table"
    assert "查询相关记录" in intent_output.planning_prompt_text


def test_logical_planning_consumes_intent_mapping_and_path_selection_outputs() -> None:
    assets = OntologyAssets.from_default_resources()
    lexer_output = OntologyLexer.from_default_resources(assets).run("查询金牌服务使用的隧道名称")
    intent_output = IntentLayer(recognizer=_AcceptedRecognizer()).run(
        core_question=lexer_output.question,
        shape_signals=lexer_output.shape_signals,
    )
    object_role_selection = OntologyObjectRoleSelectionService(
        llm_selector=_AllPathSubjectsSelector()
    ).select(lexer_trace=lexer_output, intent_output=intent_output)
    ontology_mapping = OntologyMappingService(assets).map(
        lexer_trace=lexer_output,
        object_role_selection=object_role_selection.object_role_selection,
    )
    ontology_path_selection = OntologyPathSelectionService(
        assets=assets,
        llm_selector=_NoLlmSelector(),
    ).fill(
        ontology_mapping=ontology_mapping.to_dict(),
        question=lexer_output.question,
    )

    logical_plan, planning_trace = OntologyLogicalPlanningService(
        assets=assets,
        coreference_service=OntologyCoreferenceService(llm_selector=_SameInstanceCoreferenceSelector()),
        binding_service=OntologyBindingService(llm_selector=_TunnelNameBindingSelector()),
    ).plan(
        question=lexer_output.question,
        lexer_trace=lexer_output,
        intent_output=intent_output,
        ontology_mapping=ontology_mapping.to_dict(),
        ontology_path_selection=ontology_path_selection,
    )

    assert logical_plan.intent == intent_output.intent
    assert logical_plan.shape["answer_type"] == intent_output.initial_shape["answer_type"]
    assert [edge.relation for edge in logical_plan.edges] == ["SERVICE_USES_TUNNEL"]
    assert planning_trace.binding.projections
    assert planning_trace.shape_finalization.precheck_result["passed"] is True


def test_legacy_ontology_layer_intent_classification_path_is_not_available() -> None:
    assert importlib.util.find_spec(
        "services.cypher_generator_agent.app.ontology_layer.intent_classification"
    ) is None


def test_intent_resources_live_outside_ontology_resource_tree() -> None:
    service_root = Path(__file__).resolve().parents[1]

    assert (service_root / "resources/runtime/intent/taxonomy.yaml").exists()
    assert (service_root / "resources/runtime/intent/rules.yaml").exists()
    assert not (service_root / "resources/runtime/ontology/intent").exists()
