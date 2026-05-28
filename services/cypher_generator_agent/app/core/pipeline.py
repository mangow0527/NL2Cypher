from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
import re
from time import perf_counter
from typing import Any

from services.cypher_generator_agent.app.binding import BindingValidationError, SemanticBinder
from services.cypher_generator_agent.app.compiler import CypherCompiler, CypherCompilerError
from services.cypher_generator_agent.app.core.errors import GenerationFailureReason, ServiceFailureReason
from services.cypher_generator_agent.app.core.result import GenerationOutput
from services.cypher_generator_agent.app.cypher_validation import CypherSelfValidator
from services.cypher_generator_agent.app.cypher_validation.models import CypherSelfValidationResult
from services.cypher_generator_agent.app.decomposition import QuestionDecomposer
from services.cypher_generator_agent.app.decomposition.models import (
    QuestionDecomposition,
    QuestionDecompositionClarification,
    QuestionDecompositionFailure,
)
from services.cypher_generator_agent.app.dsl.builder import RestrictedDslBuilder
from services.cypher_generator_agent.app.dsl.parser import RestrictedDslValidationError, parse_restricted_query_dsl
from services.cypher_generator_agent.app.infrastructure.config import Settings, get_settings
from services.cypher_generator_agent.app.infrastructure.llm_client import OpenAICompatibleStructuredLLMClient
from services.cypher_generator_agent.app.literals.models import LiteralResolverRequest, LiteralResolverResult
from services.cypher_generator_agent.app.literals.resolver import LiteralResolver
from services.cypher_generator_agent.app.literals.value_index import StaticValueIndex
from services.cypher_generator_agent.app.observability.stages import StageName
from services.cypher_generator_agent.app.observability.trace import GraphTraceBuilder, inline_ref
from services.cypher_generator_agent.app.repair.controller import RepairController
from services.cypher_generator_agent.app.repair.fingerprint import from_binding_plan
from services.cypher_generator_agent.app.repair.models import RepairDecision, RepairIssue
from services.cypher_generator_agent.app.repair.notices import render_user_visible_notices
from services.cypher_generator_agent.app.retrieval.models import CandidateRetrievalResult, SemanticCandidate
from services.cypher_generator_agent.app.retrieval.retriever import CandidateRetriever
from services.cypher_generator_agent.app.semantic_model.loader import load_graph_semantic_model
from services.cypher_generator_agent.app.understanding.models import (
    GroundedUnderstanding,
    GroundedUnderstandingFailure,
)
from services.cypher_generator_agent.app.understanding.grounded_understanding import GroundedUnderstandingSelector
from services.cypher_generator_agent.app.validation.coverage import CoverageReport
from services.cypher_generator_agent.app.validation.semantic_validator import SemanticValidator

def run_pipeline(
    *,
    question: str,
    qa_id: str | None = None,
    generation_run_id: str,
    _model_path: Path | None = None,
    _value_index_path: Path | None = None,
    _path_pattern_template_overrides_for_tests: Mapping[str, str] | None = None,
) -> GenerationOutput:
    question_id = qa_id or generation_run_id
    trace = GraphTraceBuilder(
        trace_id=generation_run_id,
        question_id=question_id,
        generation_run_id=generation_run_id,
        source_question=question,
    )

    settings = get_settings()
    model_path = _model_path or settings.graph_model_path
    value_index_path = _value_index_path or settings.value_index_path

    try:
        return _run_pipeline_steps(
            trace=trace,
            question=question,
            question_id=question_id,
            generation_run_id=generation_run_id,
            model_path=model_path,
            value_index_path=value_index_path,
            settings=settings,
            path_pattern_template_overrides_for_tests=_path_pattern_template_overrides_for_tests,
        )
    except Exception as exc:
        return _unexpected_failure(trace, exc)


def _run_pipeline_steps(
    *,
    trace: GraphTraceBuilder,
    question: str,
    question_id: str,
    generation_run_id: str,
    model_path: Path,
    value_index_path: Path,
    settings: Settings,
    path_pattern_template_overrides_for_tests: Mapping[str, str] | None,
) -> GenerationOutput:
    llm_client = _structured_llm_client_from_settings(settings) if settings.llm_enabled else None

    load_result = _run_stage(
        trace,
        stage=StageName.GRAPH_MODEL_LOADER,
        input_payload={"model_path": str(model_path)},
        action=lambda: load_graph_semantic_model(model_path),
        output_payload=lambda result: {
            "model_name": result.registry.model.name,
            "model_checksum": result.model_checksum,
            "vertices": len(result.registry.model.vertices),
            "edges": len(result.registry.model.edges),
            "path_patterns": len(result.registry.model.path_patterns),
        },
    )
    registry = load_result.registry
    trace._semantic_model = {  # noqa: SLF001 - IR-12 wires model metadata after loading it.
        "name": registry.model.name,
        "checksum": load_result.model_checksum,
    }

    input_gate = _run_stage(
        trace,
        stage=StageName.INPUT_CLARIFICATION_GATE,
        input_payload={"question": question},
        action=lambda: _input_clarification_gate(question),
    )
    if input_gate.get("status") == "clarification_required":
        return _clarification(
            trace,
            question=str(input_gate.get("question") or "请补充澄清信息。"),
        )

    decomposition = _run_stage(
        trace,
        stage=StageName.QUESTION_DECOMPOSER,
        input_payload={"question": question},
        action=lambda: _decompose_question(
            question=question,
            settings=settings,
            llm_client=llm_client,
        ),
    )
    if decomposition_output := _output_from_decomposition_outcome(trace, decomposition):
        return decomposition_output
    decomposition = _decomposition_payload(decomposition)

    retrieval_result = _run_stage(
        trace,
        stage=StageName.CANDIDATE_RETRIEVAL,
        input_payload=decomposition,
        action=lambda: CandidateRetriever(registry).retrieve(decomposition),
        output_payload=lambda result: result.model_dump(mode="json"),
        metrics=lambda result: {"candidate_count": len(result.candidates)},
    )
    decomposition = _with_literal_requests_from_candidates(decomposition, retrieval_result)

    literal_results = _run_stage(
        trace,
        stage=StageName.LITERAL_RESOLVER,
        input_payload={"literal_requests": decomposition["literal_requests"]},
        action=lambda: _resolve_literals(
            decomposition["literal_requests"],
            question=question,
            trace_id=generation_run_id,
            resolver=LiteralResolver(
                registry,
                StaticValueIndex.from_path(value_index_path),
            ),
        ),
        output_payload=lambda results: [result.model_dump(mode="json") for result in results],
        metrics=lambda results: {"literal_count": len(results)},
    )
    unresolved_literals = [result for result in literal_results if not result.resolved]
    if unresolved_literals:
        return _handle_repair_decision(
            trace,
            decision=_run_repair_controller_stage(
                trace,
                question=question,
                selected_bindings={},
                validator_errors=[
                    _literal_unresolved_issue(result).model_dump(mode="json")
                    for result in unresolved_literals
                ],
            ),
        )

    grounded = _run_grounded_understanding_stage(
        trace,
        decomposition=decomposition,
        retrieval_result=retrieval_result,
        literal_results=literal_results,
        settings=settings,
        llm_client=llm_client,
        attempt_no=1,
    )
    if grounded_output := _output_from_grounded_outcome(trace, grounded):
        return grounded_output
    grounded = _grounded_binder_payload(grounded)
    repair_history: list[dict[str, Any]] = []
    repair_attempt_no = 1

    while True:
        try:
            plan = _run_stage(
                trace,
                stage=StageName.SEMANTIC_BINDER,
                input_payload=grounded,
                action=lambda: SemanticBinder(registry).bind(grounded, candidates=retrieval_result),
                output_payload=lambda result: result.model_dump(mode="json"),
            )
        except BindingValidationError as exc:
            return _failure(trace, reason="semantic_match_rejected", message=str(exc))

        validation_result = _run_stage(
            trace,
            stage=StageName.SEMANTIC_VALIDATOR,
            input_payload={
                "binding_plan": plan.model_dump(mode="json"),
                "coverage": decomposition["coverage"],
            },
            action=lambda: SemanticValidator(registry).validate(plan, coverage=decomposition["coverage"]),
            output_payload=lambda result: result.model_dump(mode="json"),
        )
        if not validation_result.is_valid:
            decision = _run_repair_controller_stage(
                trace,
                question=question,
                selected_bindings=plan.model_dump(mode="json"),
                validator_errors=[
                    issue.model_dump(mode="json")
                    for issue in validation_result.errors
                ],
                assumptions=validation_result.assumptions,
                attempt_no=repair_attempt_no,
                history=repair_history,
            )
            if _can_reground_with_llm(decision, llm_client):
                repair_history.append(_repair_history_item(plan.model_dump(mode="json"), repair_attempt_no, decision))
                repair_attempt_no += 1
                grounded = _run_grounded_understanding_stage(
                    trace,
                    decomposition=decomposition,
                    retrieval_result=retrieval_result,
                    literal_results=literal_results,
                    settings=settings,
                    llm_client=llm_client,
                    repair_context=decision.repair_prompt_delta,
                    attempt_no=repair_attempt_no,
                )
                if grounded_output := _output_from_grounded_outcome(trace, grounded):
                    return grounded_output
                grounded = _grounded_binder_payload(grounded)
                continue
            return _handle_repair_decision(
                trace,
                decision=decision,
                fallback_details={"validation": validation_result.model_dump(mode="json")},
            )
        user_visible_notices = render_user_visible_notices(validation_result.assumptions)

        try:
            dsl = _run_stage(
                trace,
                stage=StageName.DSL_BUILDER,
                input_payload=plan.model_dump(mode="json"),
                action=lambda: RestrictedDslBuilder(registry).build(
                    plan,
                    source_question=question,
                    query_id=question_id,
                ),
            )
            ast = _run_stage(
                trace,
                stage=StageName.DSL_PARSER,
                input_payload=dsl,
                action=lambda: parse_restricted_query_dsl(dsl, registry),
                output_payload=lambda result: {
                    "query_shape": result.query_shape.value,
                    "operation_count": len(result.operations),
                },
            )
            compiler = CypherCompiler(
                registry,
                _path_pattern_template_overrides_for_tests=path_pattern_template_overrides_for_tests,
            )
            compilation = _run_stage(
                trace,
                stage=StageName.CYPHER_COMPILER,
                input_payload={"query_shape": ast.query_shape.value},
                action=lambda: compiler.compile_draft(ast),
                output_payload=lambda result: {
                    "schema_version": result.schema_version,
                    "cypher": result.cypher,
                    "parameters": result.parameters,
                    "expected_return_aliases": result.expected_return_aliases,
                },
            )
            validation_result = _run_cypher_self_validation_stage(
                trace,
                cypher=compilation.cypher,
                expected_return_aliases=compilation.expected_return_aliases,
                validator=CypherSelfValidator(registry),
            )
            if not validation_result.valid:
                return _handle_repair_decision(
                    trace,
                    decision=_run_repair_controller_stage(
                        trace,
                        question=question,
                        selected_bindings=plan.model_dump(mode="json"),
                        cypher_validation_errors=[
                            error.model_dump(mode="json")
                            for error in validation_result.errors
                        ],
                        attempt_no=repair_attempt_no,
                        history=repair_history,
                    ),
                    fallback_details={"self_validation": validation_result.model_dump(mode="json")},
                )
        except (CypherCompilerError, RestrictedDslValidationError, ValueError) as exc:
            return _failure(trace, reason="compiler_shape_mismatch", message=str(exc))

        return _generated(trace, dsl=dsl, cypher=compilation.cypher, user_visible_notices=user_visible_notices)


def _run_stage(
    trace: GraphTraceBuilder,
    *,
    stage: StageName,
    input_payload: Any,
    action: Callable[[], Any],
    output_payload: Callable[[Any], Any] | None = None,
    metrics: Callable[[Any], dict[str, Any]] | None = None,
) -> Any:
    started = perf_counter()
    try:
        result = action()
    except Exception as exc:
        trace.add_stage(
            stage=stage,
            status="failed",
            duration_ms=_duration_ms(started),
            input_ref=inline_ref(input_payload),
            errors=[{"type": exc.__class__.__name__, "message": str(exc)}],
        )
        raise

    output = output_payload(result) if output_payload is not None else result
    trace.add_stage(
        stage=stage,
        status="success",
        duration_ms=_duration_ms(started),
        input_ref=inline_ref(input_payload),
        output_ref=inline_ref(output),
        metrics=metrics(result) if metrics is not None else {},
    )
    return result


def _structured_llm_client_from_settings(settings: Settings) -> Any:
    if settings.llm_provider != "openai_compatible":
        raise ValueError(f"unsupported LLM provider {settings.llm_provider!r}")
    if settings.llm_base_url is None:
        raise ValueError("CYPHER_GENERATOR_AGENT_LLM_BASE_URL is required when LLM is enabled")
    if settings.llm_api_key is None:
        raise ValueError("CYPHER_GENERATOR_AGENT_LLM_API_KEY is required when LLM is enabled")
    return OpenAICompatibleStructuredLLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key.get_secret_value(),
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        timeout_seconds=settings.llm_timeout_seconds,
    )


def _input_clarification_gate(question: str) -> dict[str, Any]:
    normalized = question.strip()
    if not normalized:
        return {
            "status": "clarification_required",
            "reason": "empty_question",
            "question": "请补充您想查询的对象和条件。",
        }

    for term in ("它", "这个", "那个", "这些", "那些"):
        if term in normalized:
            return {
                "status": "clarification_required",
                "reason": "missing_referent",
                "term": term,
                "question": f"请说明“{term}”指的是哪个设备、服务、隧道或端口。",
            }

    return {"status": "pass"}


def _decompose_question(
    *,
    question: str,
    settings: Settings,
    llm_client: Any | None,
) -> Any:
    if llm_client is None:
        return _mock_decompose(question)
    return QuestionDecomposer(
        llm_client,
        max_schema_retries=settings.llm_max_schema_retries,
    ).decompose(question)


def _select_grounded_understanding(
    *,
    decomposition: dict[str, Any],
    retrieval_result: CandidateRetrievalResult,
    literal_results: list[LiteralResolverResult],
    settings: Settings,
    llm_client: Any | None,
    repair_context: Mapping[str, Any] | None = None,
) -> Any:
    if llm_client is None:
        return _mock_understand(decomposition, literal_results)
    deterministic = _deterministic_grounding_from_slots(
        decomposition=decomposition,
        retrieval_result=retrieval_result,
        literal_results=literal_results,
    )
    if deterministic is not None:
        return deterministic
    return GroundedUnderstandingSelector(
        llm_client,
        max_schema_retries=settings.llm_max_schema_retries,
    ).select(
        question_decomposition=decomposition,
        candidates=retrieval_result,
        literal_results=literal_results,
        repair_context=repair_context,
    )


def _deterministic_grounding_from_slots(
    *,
    decomposition: Mapping[str, Any],
    retrieval_result: CandidateRetrievalResult,
    literal_results: list[LiteralResolverResult],
) -> dict[str, Any] | None:
    candidates = list(retrieval_result.candidates)
    vertex_ids = _candidate_ids(candidates, "vertex")
    edge_candidates = [candidate for candidate in candidates if candidate.semantic_type == "edge"]
    literal_payloads = [result.model_dump(mode="json") for result in literal_results]
    filters = _filters_from_literal_results(literal_results)
    selected_properties = _property_refs_from_filters(filters)
    coverage = decomposition.get("coverage") or _coverage(covered=_string_list(decomposition.get("substantive_terms")))

    if _is_count_slot(decomposition):
        target_vertex = _count_target_vertex(decomposition, vertex_ids, literal_results)
        if target_vertex is None:
            return None
        id_property = _vertex_id_property(target_vertex, candidates)
        selected_properties = _append_unique_property_ref(
            selected_properties,
            {"owner": target_vertex, "name": id_property},
        )
        return {
            "query_shape": "ad_hoc_aggregate",
            "selected_vertices": [target_vertex],
            "selected_properties": selected_properties,
            "selected_literals": literal_payloads,
            "filters": filters,
            "group_by": [],
            "measures": [
                {
                    "alias": f"{_snake_case(target_vertex)}_count",
                    "function": "count",
                    "target": _snake_case(target_vertex),
                    "property": {"owner": target_vertex, "name": id_property},
                }
            ],
            "projection": [],
            "coverage": coverage,
        }

    connecting_edge = _best_connecting_edge(vertex_ids, edge_candidates)
    if connecting_edge is not None:
        from_vertex = str(connecting_edge.metadata["from_vertex"])
        to_vertex = str(connecting_edge.metadata["to_vertex"])
        projection_vertex = _projection_vertex_for_traversal([from_vertex, to_vertex], literal_results)
        return {
            "query_shape": "single_hop",
            "selected_vertices": [from_vertex, to_vertex],
            "selected_edges": [{"name": connecting_edge.semantic_id, "direction": "forward"}],
            "selected_properties": selected_properties,
            "selected_literals": literal_payloads,
            "filters": filters,
            "projection": [{"semantic_type": "vertex", "name": projection_vertex}],
            "coverage": coverage,
        }

    if len(vertex_ids) == 1:
        return {
            "query_shape": "vertex_lookup",
            "selected_vertices": [vertex_ids[0]],
            "selected_properties": selected_properties,
            "selected_literals": literal_payloads,
            "filters": filters,
            "projection": [{"semantic_type": "vertex", "name": vertex_ids[0]}],
            "coverage": coverage,
        }

    return None


def _candidate_ids(candidates: list[SemanticCandidate], semantic_type: str) -> list[str]:
    ids: list[str] = []
    for candidate in candidates:
        if candidate.semantic_type == semantic_type and candidate.semantic_id not in ids:
            ids.append(candidate.semantic_id)
    return ids


def _filters_from_literal_results(results: list[LiteralResolverResult]) -> list[dict[str, Any]]:
    filters: list[dict[str, Any]] = []
    for result in results:
        if not result.resolved or result.expected_property is None:
            continue
        owner = result.expected_vertex or result.expected_edge
        if owner is None:
            continue
        filters.append(
            {
                "owner": owner,
                "property": result.expected_property,
                "operator": "=",
                "raw_literal": result.raw_literal,
            }
        )
    return filters


def _property_refs_from_filters(filters: list[dict[str, Any]]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for item in filters:
        refs = _append_unique_property_ref(
            refs,
            {"owner": str(item["owner"]), "name": str(item["property"])},
        )
    return refs


def _append_unique_property_ref(
    refs: list[dict[str, str]],
    item: dict[str, str],
) -> list[dict[str, str]]:
    if item not in refs:
        refs.append(item)
    return refs


def _is_count_slot(decomposition: Mapping[str, Any]) -> bool:
    return str(decomposition.get("intent_type") or "").strip() == "count" or str(
        decomposition.get("output_shape") or ""
    ).strip() == "scalar"


def _count_target_vertex(
    decomposition: Mapping[str, Any],
    vertex_ids: list[str],
    literal_results: list[LiteralResolverResult],
) -> str | None:
    for result in literal_results:
        if result.expected_vertex in vertex_ids:
            return result.expected_vertex
    question = str(decomposition.get("original_question") or decomposition.get("question") or "")
    if "台" in question and "NetworkElement" in vertex_ids:
        return "NetworkElement"
    return vertex_ids[0] if vertex_ids else None


def _vertex_id_property(vertex_name: str, candidates: list[SemanticCandidate]) -> str:
    for candidate in candidates:
        if candidate.semantic_type == "vertex" and candidate.semantic_id == vertex_name:
            return str(candidate.metadata.get("id_property") or "id")
    return "id"


def _best_connecting_edge(
    vertex_ids: list[str],
    edges: list[SemanticCandidate],
) -> SemanticCandidate | None:
    vertices = set(vertex_ids)
    connecting = [
        edge
        for edge in edges
        if edge.metadata.get("from_vertex") in vertices and edge.metadata.get("to_vertex") in vertices
    ]
    if not connecting:
        return None
    return max(connecting, key=lambda edge: (edge.score, _edge_match_priority(edge), edge.semantic_id))


def _edge_match_priority(edge: SemanticCandidate) -> int:
    if edge.match_type == "exact":
        return 3
    if edge.match_type == "synonym":
        return 2
    if edge.match_type == "text":
        return 1
    return 0


def _projection_vertex_for_traversal(
    vertices: list[str],
    literal_results: list[LiteralResolverResult],
) -> str:
    filtered_owners = {result.expected_vertex or result.expected_edge for result in literal_results}
    for vertex in reversed(vertices):
        if vertex not in filtered_owners:
            return vertex
    return vertices[-1]


def _snake_case(value: str) -> str:
    text = value.replace("-", "_")
    text = "".join(f"_{char.lower()}" if char.isupper() else char for char in text)
    return text.strip("_")


def _run_grounded_understanding_stage(
    trace: GraphTraceBuilder,
    *,
    decomposition: dict[str, Any],
    retrieval_result: CandidateRetrievalResult,
    literal_results: list[LiteralResolverResult],
    settings: Settings,
    llm_client: Any | None,
    attempt_no: int,
    repair_context: Mapping[str, Any] | None = None,
) -> Any:
    input_payload: dict[str, Any] = {
        "decomposition": decomposition,
        "resolved_literals": [result.model_dump(mode="json") for result in literal_results],
        "attempt_no": attempt_no,
    }
    if repair_context:
        input_payload["repair_context"] = dict(repair_context)
    return _run_stage(
        trace,
        stage=StageName.GROUNDED_UNDERSTANDING,
        input_payload=input_payload,
        action=lambda: _select_grounded_understanding(
            decomposition=decomposition,
            retrieval_result=retrieval_result,
            literal_results=literal_results,
            settings=settings,
            llm_client=llm_client,
            repair_context=repair_context,
        ),
    )


def _with_literal_requests_from_candidates(
    decomposition: dict[str, Any],
    retrieval_result: CandidateRetrievalResult,
) -> dict[str, Any]:
    if decomposition.get("literal_requests"):
        return decomposition

    literal_candidates = _literal_candidate_payloads(decomposition)
    requests = [
        request
        for request in (
            _literal_request_from_candidate(literal, retrieval_result.candidates)
            for literal in literal_candidates
        )
        if request is not None
    ]
    if not requests:
        requests = _literal_requests_from_value_candidates(decomposition, retrieval_result.candidates)
    if not requests:
        return decomposition

    enriched = dict(decomposition)
    enriched["literal_requests"] = requests
    return enriched


def _literal_candidate_payloads(decomposition: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_candidates = decomposition.get("literal_candidate_objects") or decomposition.get("literal_candidates") or []
    if not isinstance(raw_candidates, list):
        return []
    payloads: list[dict[str, Any]] = []
    for item in raw_candidates:
        if isinstance(item, Mapping):
            text = item.get("text") or item.get("raw_literal") or item.get("value")
            if not text:
                continue
            payloads.append(
                {
                    "text": str(text),
                    "kind_hint": _normalize_literal_kind_hint(
                        item.get("kind_hint") or item.get("literal_kind_hint")
                    ),
                    "attached_to": str(item.get("attached_to") or item.get("owner") or ""),
                }
            )
        elif isinstance(item, str):
            payloads.append({"text": item, "kind_hint": "unknown", "attached_to": ""})
    return payloads


def _literal_request_from_candidate(
    literal: Mapping[str, Any],
    candidates: list[SemanticCandidate],
) -> dict[str, Any] | None:
    raw_literal = str(literal.get("text") or "").strip()
    if not raw_literal:
        return None

    attached_owners = _attached_vertex_names(str(literal.get("attached_to") or ""), candidates)
    id_request = _id_literal_request(raw_literal, literal, attached_owners, candidates)
    if id_request is not None:
        return id_request

    property_candidate = _best_literal_property_candidate(literal, candidates)
    if property_candidate is None or property_candidate.owner is None:
        return None

    owner_kind = _candidate_owner_kind(property_candidate.owner, candidates)
    if owner_kind is None:
        return None

    return {
        "raw_literal": raw_literal,
        owner_kind: property_candidate.owner,
        "expected_property": property_candidate.semantic_name,
        "literal_kind_hint": _normalize_literal_kind_hint(literal.get("kind_hint")),
    }


def _literal_requests_from_value_candidates(
    decomposition: Mapping[str, Any],
    candidates: list[SemanticCandidate],
) -> list[dict[str, Any]]:
    vertex_ids = {
        candidate.semantic_id
        for candidate in candidates
        if candidate.semantic_type == "vertex"
    }
    requests: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for candidate in candidates:
        if candidate.semantic_type != "property" or candidate.owner not in vertex_ids:
            continue
        if not candidate.metadata.get("valid_values"):
            continue
        for evidence in candidate.evidence:
            if evidence.source not in {"valid_values", "value_synonyms"}:
                continue
            raw_literal = str(evidence.term).strip()
            if not raw_literal or raw_literal not in str(
                decomposition.get("original_question") or decomposition.get("question") or ""
            ):
                continue
            if not _evidence_supports_literal_value(raw_literal, evidence.source, evidence.matched_text):
                continue
            if _is_vertex_surface_term(raw_literal, candidates):
                continue
            key = (candidate.owner or "", candidate.semantic_name, raw_literal)
            if key in seen:
                continue
            seen.add(key)
            requests.append(
                {
                    "raw_literal": raw_literal,
                    "expected_vertex": candidate.owner,
                    "expected_property": candidate.semantic_name,
                    "literal_kind_hint": "enum",
                }
            )
    return requests


def _evidence_supports_literal_value(raw_literal: str, source: str, matched_text: str) -> bool:
    if source == "value_synonyms":
        return _norm(raw_literal) == _norm(matched_text)
    if source == "valid_values":
        return _literal_value_matches(raw_literal, matched_text)
    return False


def _is_vertex_surface_term(raw_literal: str, candidates: list[SemanticCandidate]) -> bool:
    normalized = _norm(raw_literal)
    for candidate in candidates:
        if candidate.semantic_type != "vertex":
            continue
        if _norm(candidate.semantic_name) == normalized:
            return True
        for evidence in candidate.evidence:
            if _norm(evidence.term) == normalized or _norm(evidence.matched_text) == normalized:
                return True
    return False


def _id_literal_request(
    raw_literal: str,
    literal: Mapping[str, Any],
    attached_owners: set[str],
    candidates: list[SemanticCandidate],
) -> dict[str, Any] | None:
    if _normalize_literal_kind_hint(literal.get("kind_hint")) != "id" and not _looks_like_id_literal(raw_literal):
        return None

    vertex_candidates = [
        candidate
        for candidate in candidates
        if candidate.semantic_type == "vertex" and candidate.semantic_id in attached_owners
    ]
    if not vertex_candidates:
        vertex_candidates = [
            candidate
            for candidate in candidates
            if candidate.semantic_type == "vertex" and _id_prefix_matches(raw_literal, candidate.semantic_id)
        ]
    if not vertex_candidates:
        return None

    vertex = max(vertex_candidates, key=lambda candidate: (candidate.score, candidate.semantic_id))
    id_property = str(vertex.metadata.get("id_property") or "id")
    return {
        "raw_literal": raw_literal,
        "expected_vertex": vertex.semantic_id,
        "expected_property": id_property,
        "literal_kind_hint": "id",
    }


def _best_literal_property_candidate(
    literal: Mapping[str, Any],
    candidates: list[SemanticCandidate],
) -> SemanticCandidate | None:
    raw_literal = str(literal.get("text") or "")
    kind_hint = _normalize_literal_kind_hint(literal.get("kind_hint"))
    attached_to = str(literal.get("attached_to") or "")
    attached_owners = _attached_vertex_names(attached_to, candidates)
    property_candidates = [
        candidate
        for candidate in candidates
        if candidate.semantic_type == "property" and candidate.owner is not None
    ]
    if not property_candidates:
        return None
    return max(
        property_candidates,
        key=lambda candidate: _literal_property_score(raw_literal, kind_hint, attached_owners, candidate),
    )


def _literal_property_score(
    raw_literal: str,
    kind_hint: str,
    attached_owners: set[str],
    candidate: SemanticCandidate,
) -> tuple[int, float, str]:
    score = 0
    valid_values = candidate.metadata.get("valid_values", [])
    if any(_literal_value_matches(raw_literal, value) for value in valid_values):
        score += 100
    if valid_values and kind_hint in {"enum", "enum_or_name", "unknown"}:
        score += 30
    if candidate.owner in attached_owners:
        score += 25
    if candidate.semantic_name == "id" and (kind_hint == "id" or _looks_like_id_literal(raw_literal)):
        score += 5
    if candidate.semantic_name == "id" and kind_hint != "id" and not _looks_like_id_literal(raw_literal):
        score -= 50
    return (score, candidate.score, candidate.semantic_id)


def _literal_value_matches(raw_literal: str, candidate_value: Any) -> bool:
    raw = _norm(raw_literal)
    candidate = _norm(candidate_value)
    if not raw or not candidate:
        return False
    return raw == candidate or _contains_with_ascii_boundaries(raw, candidate) or _contains_with_ascii_boundaries(candidate, raw)


def _contains_with_ascii_boundaries(haystack: str, needle: str) -> bool:
    start = haystack.find(needle)
    while start != -1:
        end = start + len(needle)
        before = haystack[start - 1] if start > 0 else ""
        after = haystack[end] if end < len(haystack) else ""
        if not _is_ascii_word_char(before) and not _is_ascii_word_char(after):
            return True
        start = haystack.find(needle, start + 1)
    return False


def _is_ascii_word_char(value: str) -> bool:
    return bool(value) and (value.isascii() and (value.isalnum() or value == "_"))


def _attached_vertex_names(attached_to: str, candidates: list[SemanticCandidate]) -> set[str]:
    if not attached_to:
        return set()
    attached = _norm(attached_to)
    owners: set[str] = set()
    for candidate in candidates:
        if candidate.semantic_type != "vertex":
            continue
        if _norm(candidate.semantic_name) == attached:
            owners.add(candidate.semantic_id)
            continue
        for evidence in candidate.evidence:
            if _norm(evidence.term) == attached or _norm(evidence.matched_text) == attached:
                owners.add(candidate.semantic_id)
    return owners


def _candidate_owner_kind(owner: str, candidates: list[SemanticCandidate]) -> str | None:
    for candidate in candidates:
        if candidate.semantic_type == "vertex" and candidate.semantic_id == owner:
            return "expected_vertex"
        if candidate.semantic_type == "edge" and candidate.semantic_id == owner:
            return "expected_edge"
    return None


def _norm(value: Any) -> str:
    return str(value).casefold().strip().replace("_", " ").replace("-", " ")


def _normalize_literal_kind_hint(value: Any) -> str:
    normalized = str(value or "unknown").casefold().strip().replace("-", "_").replace(" ", "_")
    if normalized in {"enum", "enum_or_name", "id", "name", "time", "numeric", "unknown"}:
        return normalized
    if normalized in {"identifier", "identity", "key", "primary_key"}:
        return "id"
    if normalized in {"number", "integer", "float", "decimal", "amount", "capacity", "bandwidth", "latency"}:
        return "numeric"
    if normalized in {"date", "datetime", "timestamp", "recent", "latest"}:
        return "time"
    if normalized in {"enum_value", "status", "type", "category", "level", "tier", "qos"}:
        return "enum"
    if normalized in {"entity_name", "label", "display_name"}:
        return "name"
    return "unknown"


def _looks_like_id_literal(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z]+-[A-Za-z0-9-]+", value.strip()))


def _id_prefix_matches(raw_literal: str, semantic_id: str) -> bool:
    prefix = raw_literal.split("-", 1)[0].casefold()
    aliases = {
        "ne": {"networkelement", "network_element"},
        "tun": {"tunnel"},
        "svc": {"service"},
        "port": {"port"},
    }
    return semantic_id.casefold() in aliases.get(prefix, set())


def _duration_ms(started: float) -> int:
    return max(0, int((perf_counter() - started) * 1000))


def _run_cypher_self_validation_stage(
    trace: GraphTraceBuilder,
    *,
    cypher: str,
    expected_return_aliases: list[str],
    validator: CypherSelfValidator,
) -> CypherSelfValidationResult:
    started = perf_counter()
    result = validator.validate_generated_query(
        cypher,
        expected_return_aliases=expected_return_aliases,
    )
    trace.add_stage(
        stage=StageName.CYPHER_SELF_VALIDATION,
        status="success" if result.valid else "failed",
        duration_ms=_duration_ms(started),
        input_ref=inline_ref({"cypher": cypher, "expected_return_aliases": expected_return_aliases}),
        output_ref=inline_ref(result.model_dump(mode="json")),
        errors=[error.model_dump(mode="json") for error in result.errors],
        warnings=[warning.model_dump(mode="json") for warning in result.warnings],
    )
    return result


def _run_repair_controller_stage(
    trace: GraphTraceBuilder,
    *,
    question: str,
    selected_bindings: dict[str, Any],
    validator_errors: list[dict[str, Any]] | None = None,
    cypher_validation_errors: list[dict[str, Any]] | None = None,
    assumptions: list[dict[str, Any]] | None = None,
    attempt_no: int = 1,
    history: list[dict[str, Any]] | None = None,
) -> RepairDecision:
    payload = {
        "schema_version": "repair_controller_input_v1",
        "trace_id": trace._trace_id,  # noqa: SLF001 - pipeline owns the trace builder lifecycle.
        "question": question,
        "attempt_no": attempt_no,
        "selected_bindings": selected_bindings,
        "normalized_dsl": None,
        "validator_errors": validator_errors or [],
        "cypher_validation_errors": cypher_validation_errors or [],
        "history": history or [],
        "assumptions": assumptions or [],
    }
    return _run_stage(
        trace,
        stage=StageName.REPAIR_CONTROLLER,
        input_payload=payload,
        action=lambda: RepairController().decide(payload),
        output_payload=lambda result: result.model_dump(mode="json"),
    )


def _can_reground_with_llm(decision: RepairDecision, llm_client: Any | None) -> bool:
    return decision.decision == "repair_with_llm" and llm_client is not None


def _repair_history_item(
    selected_bindings: dict[str, Any],
    attempt_no: int,
    decision: RepairDecision,
) -> dict[str, Any]:
    return {
        "attempt_no": attempt_no,
        "fingerprint": from_binding_plan(selected_bindings),
        "error_code": decision.reason_code,
    }


def _output_from_decomposition_outcome(
    trace: GraphTraceBuilder,
    result: Any,
) -> GenerationOutput | None:
    if isinstance(result, QuestionDecompositionClarification):
        return _clarification(trace, question=result.clarification.question)
    if isinstance(result, QuestionDecompositionFailure):
        return _failure(trace, reason=result.reason, message=result.message)
    if isinstance(result, Mapping):
        status = result.get("status")
        if status == "clarification_required":
            clarification = result.get("clarification")
            question = _clarification_question_from_payload(clarification) or str(
                result.get("clarification_question") or "请补充澄清信息。"
            )
            return _clarification(trace, question=question)
        if status in {"generation_failed", "service_failed"}:
            return _failure(
                trace,
                reason=str(result.get("reason") or "semantic_contract_unaligned"),
                message=str(result.get("message") or result.get("reason") or status),
            )
    return None


def _decomposition_payload(result: Any) -> dict[str, Any]:
    if isinstance(result, QuestionDecomposition):
        payload = result.model_dump(mode="json")
        payload["literal_candidate_objects"] = list(payload.get("literal_candidates", []))
        payload["literal_candidates"] = [
            candidate["text"]
            for candidate in payload.get("literal_candidates", [])
            if isinstance(candidate, dict) and candidate.get("text")
        ]
        payload.setdefault("literal_requests", [])
        payload.setdefault("coverage", _coverage(covered=payload.get("substantive_terms", [])))
        return _normalize_decomposition_slots(payload)
    if isinstance(result, Mapping):
        return _normalize_decomposition_slots(dict(result))
    raise TypeError(f"question decomposer returned unsupported payload: {result!r}")


def _normalize_decomposition_slots(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    literal_objects = list(
        normalized.get("literal_candidate_objects") or normalized.get("literal_candidates") or []
    )
    target_concepts = _string_list(normalized.get("target_concepts"))
    substantive_terms = _string_list(normalized.get("substantive_terms"))

    for literal in literal_objects:
        if not isinstance(literal, Mapping):
            continue
        attached_to = str(literal.get("attached_to") or "").strip()
        if attached_to:
            target_concepts = _append_unique_term(target_concepts, attached_to)
            substantive_terms = _append_unique_term(substantive_terms, attached_to)
        text = str(literal.get("text") or literal.get("raw_literal") or literal.get("value") or "").strip()
        if text:
            substantive_terms = _append_unique_term(substantive_terms, text)

    question = str(normalized.get("original_question") or normalized.get("question") or "")
    for classifier, concept in _classifier_surface_concepts(question).items():
        target_concepts = _append_unique_term(target_concepts, concept)
        substantive_terms = _append_unique_term(substantive_terms, classifier)
        substantive_terms = _append_unique_term(substantive_terms, concept)

    normalized["target_concepts"] = target_concepts
    normalized["substantive_terms"] = substantive_terms
    normalized.setdefault("coverage", _coverage(covered=substantive_terms))
    return normalized


def _classifier_surface_concepts(question: str) -> dict[str, str]:
    concepts: dict[str, str] = {}
    if "台" in question:
        concepts["台"] = "设备"
    return concepts


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _append_unique_term(values: list[str], term: str) -> list[str]:
    if term not in values:
        values.append(term)
    return values


def _output_from_grounded_outcome(
    trace: GraphTraceBuilder,
    result: Any,
) -> GenerationOutput | None:
    if isinstance(result, GroundedUnderstandingFailure):
        return _failure(trace, reason=result.reason, message=result.message)
    grounded = _coerce_grounded_understanding(result)
    if grounded is None:
        return None
    if grounded.status == "grounded":
        return None
    if grounded.status == "unsupported_query_shape":
        message = grounded.unsupported.message if grounded.unsupported is not None else "Unsupported query shape."
        return _failure(
            trace,
            reason="unsupported_query_shape",
            message=message,
            details={
                "grounded_understanding": grounded.model_dump(mode="json"),
                "reason_code": grounded.unsupported.reason_code if grounded.unsupported else "unsupported_query_shape",
            },
        )
    if grounded.status == "clarification_required":
        return _clarification(trace, question="请补充澄清信息。")
    return _failure(
        trace,
        reason="semantic_match_rejected",
        message=f"Grounded understanding returned non-grounded status {grounded.status}.",
    )


def _grounded_binder_payload(result: Any) -> dict[str, Any]:
    grounded = _coerce_grounded_understanding(result)
    if grounded is not None:
        return grounded.to_binder_payload()
    if isinstance(result, Mapping):
        return dict(result)
    raise TypeError(f"grounded understanding returned unsupported payload: {result!r}")


def _coerce_grounded_understanding(result: Any) -> GroundedUnderstanding | None:
    if isinstance(result, GroundedUnderstanding):
        return result
    if isinstance(result, Mapping) and result.get("schema_version") == "grounded_understanding_v1":
        return GroundedUnderstanding.model_validate(result)
    return None


def _clarification_question_from_payload(payload: Any) -> str | None:
    if payload is None:
        return None
    if hasattr(payload, "question"):
        return str(payload.question)
    if isinstance(payload, Mapping):
        question = payload.get("question") or payload.get("question_zh")
        return str(question) if question else None
    return None


def _mock_decompose(question: str) -> dict[str, Any]:
    if "svc-gold-001" in question and "服务" in question and "隧道" in question:
        return {
            "schema_version": "question_decomposition_v1",
            "original_question": question,
            "target_concepts": ["Service", "Tunnel", "服务", "隧道"],
            "relation_phrases": ["使用隧道", "SERVICE_USES_TUNNEL"],
            "literal_candidates": ["svc-gold-001"],
            "semantic_terms": ["Service.id", "SERVICE_USES_TUNNEL"],
            "substantive_terms": ["服务", "svc-gold-001", "使用", "隧道"],
            "literal_requests": [
                {
                    "raw_literal": "svc-gold-001",
                    "expected_vertex": "Service",
                    "expected_property": "id",
                    "literal_kind_hint": "id",
                }
            ],
            "coverage": _coverage(covered=["服务", "svc-gold-001", "使用", "隧道"]),
            "mock_intent": "service_id_tunnels",
        }

    if ("Gold" in question or "Platinum" in question) and "服务" in question and "隧道" in question:
        service_tier = "Gold" if "Gold" in question else "Platinum"
        return {
            "schema_version": "question_decomposition_v1",
            "original_question": question,
            "target_concepts": ["Service", "Tunnel", "服务", "隧道"],
            "relation_phrases": ["使用隧道", "SERVICE_USES_TUNNEL"],
            "literal_candidates": [service_tier],
            "semantic_terms": ["Service.quality_of_service"],
            "substantive_terms": [service_tier, "服务", "使用", "隧道"],
            "literal_requests": [
                {
                    "raw_literal": service_tier,
                    "expected_vertex": "Service",
                    "expected_property": "quality_of_service",
                    "literal_kind_hint": "enum",
                }
            ],
            "coverage": _coverage(covered=[service_tier, "服务", "使用", "隧道"]),
            "mock_intent": "gold_service_tunnels",
        }

    if "tun-mpls-001" in question and "隧道" in question and "设备" in question:
        return {
            "schema_version": "question_decomposition_v1",
            "original_question": question,
            "target_concepts": ["Tunnel", "NetworkElement", "隧道", "设备"],
            "relation_phrases": ["经过", "PATH_THROUGH"],
            "literal_candidates": ["tun-mpls-001"],
            "semantic_terms": ["Tunnel.id", "tunnel_full_path"],
            "substantive_terms": ["隧道", "tun-mpls-001", "经过", "设备"],
            "literal_requests": [
                {
                    "raw_literal": "tun-mpls-001",
                    "expected_vertex": "Tunnel",
                    "expected_property": "id",
                    "literal_kind_hint": "id",
                }
            ],
            "coverage": _coverage(covered=["隧道", "tun-mpls-001", "经过", "设备"]),
            "mock_intent": "tunnel_full_path",
        }

    if "ne-0001" in question and "隧道" in question and "经过" in question:
        return {
            "schema_version": "question_decomposition_v1",
            "original_question": question,
            "target_concepts": ["Tunnel", "NetworkElement", "隧道", "设备"],
            "relation_phrases": ["经过", "PATH_THROUGH"],
            "literal_candidates": ["ne-0001"],
            "semantic_terms": ["NetworkElement.id", "PATH_THROUGH"],
            "substantive_terms": ["隧道", "经过", "设备", "ne-0001"],
            "literal_requests": [
                {
                    "raw_literal": "ne-0001",
                    "expected_vertex": "NetworkElement",
                    "expected_property": "id",
                    "literal_kind_hint": "id",
                }
            ],
            "coverage": _coverage(covered=["隧道", "经过", "设备", "ne-0001"]),
            "mock_intent": "tunnels_through_device",
        }

    if "设备" in question and "端口" in question and ("ne-0001" in question or "ne-9999" in question):
        device_id = "ne-0001" if "ne-0001" in question else "ne-9999"
        return {
            "schema_version": "question_decomposition_v1",
            "original_question": question,
            "target_concepts": ["NetworkElement", "Port", "设备", "端口"],
            "relation_phrases": ["HAS_PORT"],
            "literal_candidates": [device_id],
            "semantic_terms": ["NetworkElement.id", "HAS_PORT"],
            "substantive_terms": ["设备", device_id, "端口"],
            "literal_requests": [
                {
                    "raw_literal": device_id,
                    "expected_vertex": "NetworkElement",
                    "expected_property": "id",
                    "literal_kind_hint": "id",
                }
            ],
            "coverage": _coverage(covered=["设备", device_id, "端口"]),
            "mock_intent": "device_ports",
        }

    if "down" in question and "端口" in question:
        return {
            "schema_version": "question_decomposition_v1",
            "original_question": question,
            "target_concepts": ["Port", "端口"],
            "relation_phrases": [],
            "literal_candidates": ["down"],
            "semantic_terms": ["Port.status"],
            "substantive_terms": ["当前", "down", "端口"],
            "literal_requests": [
                {
                    "raw_literal": "down",
                    "expected_vertex": "Port",
                    "expected_property": "status",
                    "literal_kind_hint": "enum",
                }
            ],
            "coverage": _coverage(covered=["当前", "down", "端口"]),
            "mock_intent": "down_ports",
        }

    if "防火墙" in question and ("多少" in question or "数量" in question):
        return {
            "schema_version": "question_decomposition_v1",
            "original_question": question,
            "target_concepts": ["NetworkElement", "防火墙", "设备"],
            "relation_phrases": [],
            "literal_candidates": ["防火墙"],
            "semantic_terms": ["device_count", "NetworkElement.elem_type"],
            "substantive_terms": ["全网", "多少", "防火墙"],
            "literal_requests": [
                {
                    "raw_literal": "防火墙",
                    "expected_vertex": "NetworkElement",
                    "expected_property": "elem_type",
                    "literal_kind_hint": "enum",
                }
            ],
            "coverage": _coverage(covered=["全网", "多少", "防火墙"]),
            "mock_intent": "firewall_device_count",
        }

    if "按设备类型" in question and "设备数量" in question:
        return {
            "schema_version": "question_decomposition_v1",
            "original_question": question,
            "target_concepts": ["NetworkElement", "设备"],
            "relation_phrases": [],
            "literal_candidates": [],
            "semantic_terms": ["device_count", "NetworkElement.elem_type"],
            "substantive_terms": ["按设备类型", "统计", "设备数量"],
            "literal_requests": [],
            "coverage": _coverage(covered=["按设备类型", "统计", "设备数量"]),
            "mock_intent": "device_count_by_elem_type",
        }

    if "端口最多" in question and "设备" in question:
        return {
            "schema_version": "question_decomposition_v1",
            "original_question": question,
            "target_concepts": ["NetworkElement", "Port", "设备", "端口"],
            "relation_phrases": ["HAS_PORT"],
            "literal_candidates": [],
            "semantic_terms": ["port_count", "NetworkElement.id"],
            "substantive_terms": ["端口最多", "5", "设备"],
            "literal_requests": [],
            "coverage": _coverage(covered=["端口最多", "5", "设备"]),
            "mock_intent": "top_n_devices_by_port_count",
        }

    if "先按状态统计端口" in question and "最多" in question:
        return {
            "schema_version": "question_decomposition_v1",
            "original_question": question,
            "target_concepts": ["Port", "端口"],
            "relation_phrases": [],
            "literal_candidates": [],
            "semantic_terms": ["Port.status", "Port.id"],
            "substantive_terms": ["先按状态", "统计端口", "最多"],
            "literal_requests": [],
            "coverage": _coverage(covered=["先按状态", "统计端口", "最多"]),
            "mock_intent": "two_step_port_status_count",
        }

    if "按状态" in question and "端口数量" in question:
        return {
            "schema_version": "question_decomposition_v1",
            "original_question": question,
            "target_concepts": ["Port", "端口"],
            "relation_phrases": [],
            "literal_candidates": [],
            "semantic_terms": ["Port.status", "Port.id"],
            "substantive_terms": ["按状态", "统计", "端口数量"],
            "literal_requests": [],
            "coverage": _coverage(covered=["按状态", "统计", "端口数量"]),
            "mock_intent": "port_count_by_status",
        }

    return {
        "schema_version": "question_decomposition_v1",
        "original_question": question,
        "target_concepts": ["Service"],
        "relation_phrases": [],
        "literal_candidates": [],
        "semantic_terms": ["Service"],
        "substantive_terms": ["收入", "增长"] if ("收入" in question or "增长" in question) else [question],
        "literal_requests": [],
        "coverage": _coverage(uncovered=["收入", "增长"] if ("收入" in question or "增长" in question) else [question]),
        "mock_intent": "coverage_failure",
    }


def _coverage(
    *,
    covered: list[str] | None = None,
    uncovered: list[str] | None = None,
) -> dict[str, Any]:
    covered_terms = covered or []
    uncovered_terms = uncovered or []
    return CoverageReport(
        substantive_terms={
            "total": len(covered_terms) + len(uncovered_terms),
            "covered": len(covered_terms),
            "uncovered": uncovered_terms,
        }
    ).model_dump(mode="json")


def _resolve_literals(
    literal_requests: list[dict[str, Any]],
    *,
    question: str,
    trace_id: str,
    resolver: LiteralResolver,
) -> list[LiteralResolverResult]:
    results: list[LiteralResolverResult] = []
    for payload in literal_requests:
        payload = {
            **payload,
            "literal_kind_hint": _normalize_literal_kind_hint(payload.get("literal_kind_hint")),
        }
        request = LiteralResolverRequest(
            **payload,
            question_context=question,
            trace_id=trace_id,
        )
        results.append(resolver.resolve(request))
    return results


def _mock_understand(
    decomposition: dict[str, Any],
    literal_results: list[LiteralResolverResult],
) -> dict[str, Any]:
    intent = decomposition["mock_intent"]
    literal_payloads = [result.model_dump(mode="json") for result in literal_results]
    if intent == "service_id_tunnels":
        return {
            "query_shape": "single_hop",
            "selected_vertices": ["Service", "Tunnel"],
            "selected_edges": ["SERVICE_USES_TUNNEL"],
            "selected_properties": [{"owner": "Service", "name": "id"}],
            "selected_literals": literal_payloads,
            "filters": [
                {
                    "owner": "Service",
                    "property": "id",
                    "operator": "=",
                    "raw_literal": "svc-gold-001",
                }
            ],
            "projection": [{"semantic_type": "vertex", "name": "Tunnel"}],
        }

    if intent == "gold_service_tunnels":
        return {
            "query_shape": "single_hop",
            "selected_vertices": ["Service", "Tunnel"],
            "selected_edges": ["SERVICE_USES_TUNNEL"],
            "selected_properties": [{"owner": "Service", "name": "quality_of_service"}],
            "selected_literals": literal_payloads,
            "filters": [
                {
                    "owner": "Service",
                    "property": "quality_of_service",
                    "operator": "=",
                    "raw_literal": "Gold",
                }
            ],
            "projection": [{"semantic_type": "vertex", "name": "Tunnel"}],
        }

    if intent == "tunnel_full_path":
        return {
            "query_shape": "named_path_pattern",
            "selected_vertices": ["Tunnel"],
            "selected_path_patterns": ["tunnel_full_path"],
            "selected_properties": [{"owner": "Tunnel", "name": "id"}],
            "selected_literals": literal_payloads,
            "filters": [
                {
                    "owner": "Tunnel",
                    "property": "id",
                    "operator": "=",
                    "raw_literal": "tun-mpls-001",
                }
            ],
            "projection": [
                {"alias": "device", "source": "path.device"},
                {"alias": "hop", "source": "path.hop"},
            ],
            "assumptions": [{"type": "path_pattern_selected", "name": "tunnel_full_path"}],
        }

    if intent == "tunnels_through_device":
        return {
            "query_shape": "variable_path_traversal",
            "selected_vertices": ["Tunnel", "NetworkElement"],
            "selected_edges": ["PATH_THROUGH"],
            "selected_properties": [{"owner": "NetworkElement", "name": "id"}],
            "selected_literals": literal_payloads,
            "filters": [
                {
                    "owner": "NetworkElement",
                    "property": "id",
                    "operator": "=",
                    "raw_literal": "ne-0001",
                }
            ],
            "projection": [{"semantic_type": "vertex", "name": "Tunnel"}],
        }

    if intent == "device_ports":
        return {
            "query_shape": "single_hop",
            "selected_vertices": ["NetworkElement", "Port"],
            "selected_edges": ["HAS_PORT"],
            "selected_properties": [{"owner": "NetworkElement", "name": "id"}],
            "selected_literals": literal_payloads,
            "filters": [
                {
                    "owner": "NetworkElement",
                    "property": "id",
                    "operator": "=",
                    "raw_literal": decomposition["literal_candidates"][0],
                }
            ],
            "projection": [{"semantic_type": "vertex", "name": "Port"}],
        }

    if intent == "down_ports":
        return {
            "query_shape": "vertex_lookup",
            "selected_vertices": ["Port"],
            "selected_properties": [{"owner": "Port", "name": "status"}],
            "selected_literals": literal_payloads,
            "filters": [
                {
                    "owner": "Port",
                    "property": "status",
                    "operator": "=",
                    "raw_literal": "down",
                }
            ],
            "projection": [{"semantic_type": "vertex", "name": "Port"}],
        }

    if intent == "firewall_device_count":
        return {
            "query_shape": "metric_aggregate",
            "selected_metrics": ["device_count"],
            "selected_properties": [{"owner": "NetworkElement", "name": "elem_type"}],
            "selected_literals": literal_payloads,
            "filters": [
                {
                    "owner": "NetworkElement",
                    "property": "elem_type",
                    "operator": "=",
                    "raw_literal": "防火墙",
                }
            ],
            "projection": [{"alias": "device_count", "source": "metric.device_count"}],
        }

    if intent == "device_count_by_elem_type":
        return {
            "query_shape": "metric_aggregate",
            "selected_metrics": ["device_count"],
            "selected_properties": [{"owner": "NetworkElement", "name": "elem_type"}],
            "group_by": [
                {
                    "alias": "elem_type",
                    "target": "ne",
                    "property": {"owner": "NetworkElement", "name": "elem_type"},
                }
            ],
            "projection": [
                {"alias": "elem_type", "source": "group.elem_type"},
                {"alias": "device_count", "source": "metric.device_count"},
            ],
        }

    if intent == "port_count_by_status":
        return {
            "query_shape": "ad_hoc_aggregate",
            "selected_vertices": ["Port"],
            "selected_properties": [
                {"owner": "Port", "name": "status"},
                {"owner": "Port", "name": "id"},
            ],
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
            "projection": [
                {"alias": "status", "source": "group.status"},
                {"alias": "port_count", "source": "measure.port_count"},
            ],
        }

    if intent == "top_n_devices_by_port_count":
        return {
            "query_shape": "top_n",
            "selected_metrics": ["port_count"],
            "selected_properties": [{"owner": "NetworkElement", "name": "id"}],
            "group_by": [
                {
                    "alias": "device",
                    "target": "ne",
                    "property": {"owner": "NetworkElement", "name": "id"},
                }
            ],
            "projection": [
                {"alias": "device", "source": "group.device"},
                {"alias": "port_count", "source": "metric.port_count"},
            ],
            "sort": [{"source": "metric.port_count", "direction": "desc"}],
            "limit": 5,
        }

    if intent == "two_step_port_status_count":
        return {
            "query_shape": "two_step_aggregate",
            "selected_vertices": ["Port"],
            "selected_properties": [
                {"owner": "Port", "name": "status"},
                {"owner": "Port", "name": "id"},
            ],
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
            "projection": [
                {"alias": "status", "source": "port_status_counts.status"},
                {"alias": "port_count", "source": "port_status_counts.port_count"},
            ],
            "sort": [{"source": "port_status_counts.port_count", "direction": "desc"}],
            "limit": 5,
        }

    return {
        "query_shape": "vertex_lookup",
        "selected_vertices": ["Service"],
    }


def _failure(
    trace: GraphTraceBuilder,
    *,
    reason: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> GenerationOutput:
    failure: dict[str, Any] = {
        "reason": reason,
        "message": message,
        "suggested_rewrites": [],
    }
    if details:
        failure["details"] = details
    status = _status_for_failure_reason(reason)
    _add_output_stage(
        trace,
        status=status,
        payload={"status": status, "failure": failure},
        errors=[{"code": reason, "message": message}],
    )
    return trace.finalize_failure(status=status, failure=failure)


def _clarification(
    trace: GraphTraceBuilder,
    *,
    question: str,
    user_visible_notices: list[str] | None = None,
) -> GenerationOutput:
    clarification = {"question": question}
    _add_output_stage(
        trace,
        status="clarification_required",
        payload={"status": "clarification_required", "clarification": clarification},
    )
    return trace.finalize_clarification(
        clarification=clarification,
        user_visible_notices=user_visible_notices or [],
    )


def _handle_repair_decision(
    trace: GraphTraceBuilder,
    *,
    decision: RepairDecision,
    fallback_details: dict[str, Any] | None = None,
) -> GenerationOutput:
    if decision.decision == "ask_user" and decision.clarification is not None:
        return _clarification(
            trace,
            question=decision.clarification.question or decision.clarification.question_zh or "请补充澄清信息。",
            user_visible_notices=decision.derived_user_visible_notices,
        )
    if decision.decision == "unsupported":
        return _failure(
            trace,
            reason="unsupported_query_shape",
            message=decision.reason_code,
            details=fallback_details,
        )
    if decision.decision == "generation_failed":
        return _failure(
            trace,
            reason=decision.reason_code,
            message=decision.stop_reason or decision.reason_code,
            details=fallback_details,
        )
    if decision.decision == "repair_with_llm":
        return _failure(
            trace,
            reason="semantic_match_rejected",
            message=f"Repair with LLM is not connected in deterministic pipeline: {decision.reason_code}",
            details={"repair_decision": decision.model_dump(mode="json"), **(fallback_details or {})},
        )
    return _failure(
        trace,
        reason="semantic_contract_unaligned",
        message=f"Unexpected repair decision {decision.decision}",
        details={"repair_decision": decision.model_dump(mode="json"), **(fallback_details or {})},
    )


def _generated(
    trace: GraphTraceBuilder,
    *,
    dsl: dict[str, Any],
    cypher: str,
    user_visible_notices: list[str] | None = None,
) -> GenerationOutput:
    _add_output_stage(
        trace,
        status="generated",
        payload={"status": "generated", "has_dsl": True, "has_cypher": True},
    )
    return trace.finalize_generated(
        dsl=dsl,
        cypher=cypher,
        user_visible_notices=user_visible_notices or [],
    )


def _unexpected_failure(trace: GraphTraceBuilder, exc: Exception) -> GenerationOutput:
    reason = "knowledge_context_unavailable" if _last_stage_name(trace) == "graph_model_loader" else "semantic_contract_unaligned"
    return _failure(trace, reason=reason, message=str(exc))


def _add_output_stage(
    trace: GraphTraceBuilder,
    *,
    status: str,
    payload: dict[str, Any],
    errors: list[dict[str, Any]] | None = None,
) -> None:
    trace.add_stage(
        stage=StageName.OUTPUT,
        status="success" if status == "generated" else "failed",
        duration_ms=0,
        output_ref=inline_ref(payload),
        errors=errors or [],
    )


def _status_for_failure_reason(reason: str) -> str:
    if reason in set(ServiceFailureReason.__args__):
        return "service_failed"
    if reason == "unsupported_query_shape":
        return "unsupported_query_shape"
    if reason not in set(GenerationFailureReason.__args__):
        return "service_failed"
    return "generation_failed"


def _literal_unresolved_issue(result: LiteralResolverResult) -> RepairIssue:
    expected = ".".join(
        part
        for part in [result.expected_vertex or result.expected_edge, result.expected_property]
        if part
    )
    return RepairIssue(
        code="literal_unresolved",
        message=f"literal {result.raw_literal!r} could not be resolved for {expected}",
        severity="error",
        repairable=False,
        action="ask_user",
        details={
            "literal": result.raw_literal,
            "property": expected,
            "alternatives": [
                alternative.model_dump(mode="json")
                for alternative in result.alternatives
            ],
        },
    )


def _last_stage_name(trace: GraphTraceBuilder) -> str | None:
    stages = getattr(trace, "_stages", [])
    if not stages:
        return None
    return str(stages[-1].stage)
