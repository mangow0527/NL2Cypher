from __future__ import annotations

from services.cypher_generator_agent.app.clarification_layer.errors import ClarificationNeeded
from services.cypher_generator_agent.app.infrastructure.llm_client import OpenAICompatibleCompletionClient
from services.cypher_generator_agent.app.lexical_layer.lexer import OntologyLexer
from services.cypher_generator_agent.app.ontology_layer.assets import OntologyAssets
from services.cypher_generator_agent.app.ontology_layer.intent_classification.ontology import OntologyIntentClassifier
from services.cypher_generator_agent.app.ontology_layer.models import GenerationResult, GenerationTrace
from services.cypher_generator_agent.app.ontology_layer.object_role_selection import (
    ObjectRoleSelectionValidationError,
    OntologyObjectRoleSelectionService,
)
from services.cypher_generator_agent.app.ontology_layer.ontology_mapping import OntologyMappingService
from services.cypher_generator_agent.app.ontology_layer.planner import OntologyLogicalPlanner
from services.cypher_generator_agent.app.ontology_layer.prompts import BoundedLLMSelector, PromptRegistry
from services.cypher_generator_agent.app.physical_orchestration.compiler import OntologyPhysicalCompiler
from services.cypher_generator_agent.app.validation_layer.validator import OntologySemanticValidator
from services.cypher_generator_agent.app.natural_language_preprocessing.pipeline import preprocess_question


class OntologyGenerationPipeline:
    def __init__(
        self,
        *,
        assets: OntologyAssets,
        lexer: OntologyLexer | None = None,
        intent_classifier: OntologyIntentClassifier | None = None,
        object_role_selection_service: OntologyObjectRoleSelectionService | None = None,
        ontology_mapping_service: OntologyMappingService | None = None,
        planner: OntologyLogicalPlanner | None = None,
        validator: OntologySemanticValidator | None = None,
        compiler: OntologyPhysicalCompiler | None = None,
    ) -> None:
        self.assets = assets
        self.lexer = lexer or OntologyLexer.from_default_resources(assets)
        self.intent_classifier = intent_classifier or OntologyIntentClassifier()
        self.object_role_selection_service = object_role_selection_service
        self.ontology_mapping_service = ontology_mapping_service or OntologyMappingService(assets)
        self.planner = planner or OntologyLogicalPlanner(assets)
        self.validator = validator or OntologySemanticValidator(assets)
        self.compiler = compiler or OntologyPhysicalCompiler()

    @classmethod
    def from_default_resources(cls) -> "OntologyGenerationPipeline":
        assets = OntologyAssets.from_default_resources()
        llm_client = OpenAICompatibleCompletionClient.from_environment()
        intent_classifier = None
        object_role_selection_service = None
        if llm_client is not None:
            registry = PromptRegistry.default()
            llm_selector = BoundedLLMSelector(registry=registry, client=llm_client)
            intent_classifier = OntologyIntentClassifier(llm_selector=llm_selector)
            object_role_selection_service = OntologyObjectRoleSelectionService(llm_selector=llm_selector)
        return cls(assets=assets, intent_classifier=intent_classifier, object_role_selection_service=object_role_selection_service)

    def generate(self, question: str, *, trace_id: str = "runtime") -> GenerationResult:
        preprocessing_result = preprocess_question(question)
        preprocessing_payload = preprocessing_result.to_dict()
        if not preprocessing_result.accepted or not preprocessing_result.core_question:
            clarification = preprocessing_result.clarification or {}
            raise ClarificationNeeded(
                stage="preprocessing",
                message="question preprocessing rejected input",
                clarification=clarification,
            )

        lexer_trace = self.lexer.run(preprocessing_result.core_question)
        intent_trace = self.intent_classifier.classify(
            core_question=preprocessing_result.core_question,
            shape_signals=lexer_trace.shape_signals,
        )
        if self.object_role_selection_service is None:
            raise ClarificationNeeded(
                stage="step_2_1",
                message="object role selection requires a configured LLM selector",
                clarification={
                    "reason": "Step 2.1 requires LLM-backed object role selection before logical planning.",
                    "blocking_evidence": [],
                },
            )
        try:
            object_role_selection_trace = self.object_role_selection_service.select(
                lexer_trace=lexer_trace,
                intent_trace=intent_trace,
            )
        except ObjectRoleSelectionValidationError as exc:
            raise ClarificationNeeded(
                stage="step_2_1",
                message="object role selection failed validation",
                clarification={
                    "reason": str(exc),
                    "blocking_evidence": [],
                },
            ) from exc
        if object_role_selection_trace.clarification is not None:
            raise ClarificationNeeded(
                stage="step_2_1",
                message="object role selection needs clarification",
                clarification=object_role_selection_trace.clarification,
            )
        ontology_mapping = self.ontology_mapping_service.map(
            lexer_trace=lexer_trace,
            object_role_selection=object_role_selection_trace.object_role_selection,
        )
        logical_plan, planner_trace = self.planner.plan(lexer_trace, intent_trace)
        validator_trace = self.validator.validate(logical_plan)
        if not validator_trace.accepted:
            failed = [item for item in validator_trace.checks if not item.get("accepted")]
            raise ValueError(f"semantic validation failed: {failed}")
        compiler_trace = self.compiler.compile(logical_plan)
        trace = GenerationTrace(
            trace_id=trace_id,
            preprocessing=preprocessing_payload,
            lexer=lexer_trace,
            intent=intent_trace,
            object_role_selection=object_role_selection_trace,
            ontology_mapping=ontology_mapping,
            planner=planner_trace,
            validator=validator_trace,
            compiler=compiler_trace,
        )
        return GenerationResult(
            status="generated",
            cypher=compiler_trace.cypher,
            logical_plan=logical_plan,
            trace=trace,
        )
