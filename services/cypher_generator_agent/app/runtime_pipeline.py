from __future__ import annotations

from typing import Any

from services.cypher_generator_agent.app.clarification_layer.errors import ClarificationNeeded
from services.cypher_generator_agent.app.infrastructure.llm_client import OpenAICompatibleCompletionClient
from services.cypher_generator_agent.app.intent_layer.layer import IntentLayer
from services.cypher_generator_agent.app.lexical_layer.lexer import OntologyLexer
from services.cypher_generator_agent.app.ontology_layer.assets import OntologyAssets
from services.cypher_generator_agent.app.ontology_layer.models import GenerationResult, GenerationTrace
from services.cypher_generator_agent.app.ontology_layer.object_role_selection import (
    ObjectRoleSelectionValidationError,
    OntologyObjectRoleSelectionService,
)
from services.cypher_generator_agent.app.ontology_layer.ontology_mapping import OntologyMappingService
from services.cypher_generator_agent.app.ontology_layer.ontology_path_selection import (
    OntologyPathSelectionService,
    OntologyPathSelectionValidationError,
)
from services.cypher_generator_agent.app.ontology_layer.binding import OntologyBindingService
from services.cypher_generator_agent.app.ontology_layer.coreference import OntologyCoreferenceService
from services.cypher_generator_agent.app.ontology_layer.logical_planning import OntologyLogicalPlanningService
from services.cypher_generator_agent.app.ontology_layer.prompts import BoundedLLMSelector, PromptRegistry
from services.cypher_generator_agent.app.ontology_layer.shape_finalization import OntologyShapeFinalizer
from services.cypher_generator_agent.app.physical_orchestration.compiler import OntologyPhysicalCompiler
from services.cypher_generator_agent.app.validation_layer.validator import OntologySemanticValidator
from services.cypher_generator_agent.app.natural_language_preprocessing.pipeline import preprocess_question


class OntologyGenerationPipeline:
    def __init__(
        self,
        *,
        assets: OntologyAssets,
        lexer: OntologyLexer | None = None,
        intent_layer: IntentLayer | None = None,
        object_role_selection_service: OntologyObjectRoleSelectionService | None = None,
        ontology_mapping_service: OntologyMappingService | None = None,
        path_selection_service: OntologyPathSelectionService | None = None,
        logical_planning_service: OntologyLogicalPlanningService | None = None,
        validator: OntologySemanticValidator | None = None,
        compiler: OntologyPhysicalCompiler | None = None,
    ) -> None:
        self.assets = assets
        self.lexer = lexer or OntologyLexer.from_default_resources(assets)
        self.intent_layer = intent_layer or IntentLayer()
        self.object_role_selection_service = object_role_selection_service
        self.ontology_mapping_service = ontology_mapping_service or OntologyMappingService(assets)
        self.path_selection_service = path_selection_service or OntologyPathSelectionService(
            assets=assets,
            llm_selector=_UnavailablePathSelectionLLMSelector(),
        )
        self.logical_planning_service = logical_planning_service or OntologyLogicalPlanningService(assets=assets)
        self.validator = validator or OntologySemanticValidator(assets)
        self.compiler = compiler or OntologyPhysicalCompiler()

    @classmethod
    def from_default_resources(cls) -> "OntologyGenerationPipeline":
        assets = OntologyAssets.from_default_resources()
        llm_client = OpenAICompatibleCompletionClient.from_environment()
        intent_layer = None
        object_role_selection_service = None
        path_selection_service = None
        logical_planning_service = None
        if llm_client is not None:
            registry = PromptRegistry.default()
            llm_selector = BoundedLLMSelector(registry=registry, client=llm_client)
            intent_layer = IntentLayer(llm_selector=llm_selector)
            object_role_selection_service = OntologyObjectRoleSelectionService(llm_selector=llm_selector)
            path_selection_service = OntologyPathSelectionService(assets=assets, llm_selector=llm_selector)
            logical_planning_service = OntologyLogicalPlanningService(
                assets=assets,
                coreference_service=OntologyCoreferenceService(llm_selector=llm_selector),
                binding_service=OntologyBindingService(llm_selector=llm_selector),
                shape_finalizer=OntologyShapeFinalizer(assets),
            )
        return cls(
            assets=assets,
            intent_layer=intent_layer,
            object_role_selection_service=object_role_selection_service,
            path_selection_service=path_selection_service,
            logical_planning_service=logical_planning_service,
        )

    def generate(self, question: str, *, trace_id: str = "runtime") -> GenerationResult:
        preprocessing_result = preprocess_question(question)
        preprocessing_payload = preprocessing_result.to_dict()
        if not preprocessing_result.accepted or not preprocessing_result.core_question:
            clarification = preprocessing_result.clarification or {}
            raise ClarificationNeeded(
                stage="preprocessing",
                message="question preprocessing rejected input",
                clarification=_clarification_payload(
                    preprocessing_result.core_candidate or preprocessing_result.cleaned_question or question,
                    None,
                    clarification,
                ),
            )

        lexer_trace = self.lexer.run(preprocessing_result.core_question)
        intent_output = self.intent_layer.run(
            core_question=preprocessing_result.core_question,
            shape_signals=lexer_trace.shape_signals,
        )
        if (
            (intent_output.intent.primary == "unknown" or intent_output.intent.secondary == "unknown")
            and intent_output.intent.decision == "clarify"
        ):
            raise ClarificationNeeded(
                stage="step_2",
                message="intent recognition needs clarification",
                clarification=_clarification_payload(
                    preprocessing_result.core_question,
                    "step_2_intent_shape",
                    {
                        "reason_code": intent_output.intent.clarify_reason or "intent_not_identified",
                        "reason": "当前问题无法识别出准确的意图。",
                        "failed_fields": list(intent_output.intent.failed_fields),
                        "candidate_intents": [dict(item) for item in intent_output.intent.candidate_intents],
                    },
                ),
            )
        if self.object_role_selection_service is None:
            raise ClarificationNeeded(
                stage="step_3_1",
                message="object role selection requires a configured LLM selector",
                clarification=_clarification_payload(
                    preprocessing_result.core_question,
                    "step_3_1_object_role_selection",
                    {
                        "reason_code": "object_role_llm_unavailable",
                        "reason": "Step 3.1 requires LLM-backed object role selection before logical planning.",
                        "blocking_evidence": [],
                    },
                ),
            )
        try:
            object_role_selection_trace = self.object_role_selection_service.select(
                lexer_trace=lexer_trace,
                intent_output=intent_output,
            )
        except ObjectRoleSelectionValidationError as exc:
            raise ClarificationNeeded(
                stage="step_3_1",
                message="object role selection failed validation",
                clarification=_clarification_payload(
                    preprocessing_result.core_question,
                    "step_3_1_object_role_selection",
                    {
                        "reason_code": "object_role_validation_failed",
                        "reason": str(exc),
                        "blocking_evidence": [],
                    },
                ),
            ) from exc
        if object_role_selection_trace.clarification is not None:
            raise ClarificationNeeded(
                stage="step_3_1",
                message="object role selection needs clarification",
                clarification=_clarification_payload(
                    preprocessing_result.core_question,
                    "step_3_1_object_role_selection",
                    object_role_selection_trace.clarification,
                ),
            )
        ontology_mapping = self.ontology_mapping_service.map(
            lexer_trace=lexer_trace,
            object_role_selection=object_role_selection_trace.object_role_selection,
        )
        ontology_mapping_payload = ontology_mapping.to_dict()
        try:
            ontology_path_selection = self.path_selection_service.fill(
                ontology_mapping=ontology_mapping_payload,
                question=preprocessing_result.core_question,
            )
        except OntologyPathSelectionValidationError as exc:
            raise ClarificationNeeded(
                stage="step_3_3",
                message="ontology path selection failed validation",
                clarification=_clarification_payload(
                    preprocessing_result.core_question,
                    "step_3_3_ontology_path_selection",
                    {
                        "reason_code": "path_selection_validation_failed",
                        "reason": str(exc),
                        "blocking_evidence": [],
                    },
                ),
            ) from exc
        if ontology_path_selection.clarification is not None:
            raise ClarificationNeeded(
                stage="step_3_3",
                message="ontology path selection needs clarification",
                clarification=_clarification_payload(
                    preprocessing_result.core_question,
                    "step_3_3_ontology_path_selection",
                    ontology_path_selection.clarification,
                ),
            )
        try:
            logical_plan, planning_trace = self.logical_planning_service.plan(
                question=preprocessing_result.core_question,
                lexer_trace=lexer_trace,
                intent_output=intent_output,
                ontology_mapping=ontology_mapping_payload,
                ontology_path_selection=ontology_path_selection,
            )
        except ClarificationNeeded as exc:
            raise ClarificationNeeded(
                stage=exc.stage,
                message=exc.message,
                clarification=_clarification_payload(preprocessing_result.core_question, None, exc.clarification),
            ) from exc
        validator_trace = self.validator.validate(logical_plan)
        if not validator_trace.accepted:
            failed = [item for item in validator_trace.checks if not item.get("accepted")]
            raise ClarificationNeeded(
                stage="step_4",
                message="semantic validation needs clarification",
                clarification=_clarification_payload(
                    preprocessing_result.core_question,
                    "step_4_semantic_validation",
                    {
                        "reason_code": _semantic_reason_code(failed),
                        "reason": _semantic_reason(failed),
                        "failed_checks": failed,
                    },
                ),
            )
        compiler_trace = self.compiler.compile(logical_plan)
        trace = GenerationTrace(
            trace_id=trace_id,
            preprocessing=preprocessing_payload,
            lexer=lexer_trace,
            intent=intent_output,
            object_role_selection=object_role_selection_trace,
            ontology_mapping=ontology_mapping,
            ontology_path_selection=ontology_path_selection,
            coreference=planning_trace.coreference,
            binding=planning_trace.binding,
            shape_finalization=planning_trace.shape_finalization,
            validator=validator_trace,
            compiler=compiler_trace,
        )
        return GenerationResult(
            status="generated",
            cypher=compiler_trace.cypher,
            logical_plan=logical_plan,
            trace=trace,
        )


class _UnavailablePathSelectionLLMSelector:
    def select(self, prompt_name: str, variables: dict[str, object]) -> object:
        raise OntologyPathSelectionValidationError(
            "ontology path selection requires a configured LLM selector for multi-candidate paths"
        )


def _clarification_payload(core_question: str, source_step: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    result = {"core_question": core_question}
    if source_step is not None:
        result["source_step"] = source_step
    result.update(dict(payload))
    return result


def _semantic_reason_code(failed_checks: list[dict[str, object]]) -> str:
    checks = {str(item.get("check")) for item in failed_checks}
    if checks & {"projection_attribute_exists", "filter_attribute_exists", "metric_condition_attribute_exists"}:
        return "SEMANTIC_ATTRIBUTE_OWNER_INVALID"
    if "edge_domain_range" in checks:
        return "SEMANTIC_RELATION_DIRECTION_INVALID"
    if "edge_nodes_exist" in checks:
        return "SEMANTIC_ILLEGAL_PATH"
    if "return_non_empty" in checks or "constraint_rule" in checks:
        return "SEMANTIC_CONSTRAINT_VIOLATION"
    return "SEMANTIC_VALIDATION_FAILED"


def _semantic_reason(failed_checks: list[dict[str, object]]) -> str:
    if not failed_checks:
        return "logical plan 未通过语义校验。"
    first = failed_checks[0]
    check = first.get("check")
    if check in {"projection_attribute_exists", "filter_attribute_exists", "metric_condition_attribute_exists"}:
        return f"{first.get('attribute')} 不属于当前对象或未登记在本体中。"
    if check == "edge_domain_range":
        return f"{first.get('edge')} 的连接方向或端点类型不符合本体定义。"
    if check == "edge_nodes_exist":
        return f"{first.get('edge')} 引用了不存在的路径端点。"
    return f"{check} 未通过语义校验。"
