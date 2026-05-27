from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from time import perf_counter
from typing import Any

from services.cypher_generator_agent.app.binding import BindingValidationError, SemanticBinder
from services.cypher_generator_agent.app.compiler import CypherCompiler, CypherCompilerError
from services.cypher_generator_agent.app.core.errors import GenerationFailureReason, ServiceFailureReason
from services.cypher_generator_agent.app.core.result import GenerationOutput
from services.cypher_generator_agent.app.cypher_validation import CypherSelfValidator
from services.cypher_generator_agent.app.cypher_validation.models import CypherSelfValidationResult
from services.cypher_generator_agent.app.dsl.builder import RestrictedDslBuilder
from services.cypher_generator_agent.app.dsl.parser import RestrictedDslValidationError, parse_restricted_query_dsl
from services.cypher_generator_agent.app.literals.models import LiteralResolverRequest, LiteralResolverResult
from services.cypher_generator_agent.app.literals.resolver import LiteralResolver
from services.cypher_generator_agent.app.literals.value_index import StaticValueIndex
from services.cypher_generator_agent.app.observability.stages import StageName
from services.cypher_generator_agent.app.observability.trace import GraphTraceBuilder, inline_ref
from services.cypher_generator_agent.app.repair.controller import RepairController
from services.cypher_generator_agent.app.repair.models import RepairDecision, RepairIssue
from services.cypher_generator_agent.app.retrieval.retriever import CandidateRetriever
from services.cypher_generator_agent.app.semantic_model.loader import load_graph_semantic_model
from services.cypher_generator_agent.app.validation.coverage import CoverageReport
from services.cypher_generator_agent.app.validation.semantic_validator import SemanticValidator


_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
_MODEL_PATH = _FIXTURE_DIR / "network_topology_graph_model.yaml"
_VALUE_INDEX_PATH = _FIXTURE_DIR / "value_index.json"


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

    model_path = _model_path or _MODEL_PATH
    value_index_path = _value_index_path or _VALUE_INDEX_PATH

    try:
        return _run_pipeline_steps(
            trace=trace,
            question=question,
            question_id=question_id,
            generation_run_id=generation_run_id,
            model_path=model_path,
            value_index_path=value_index_path,
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
    path_pattern_template_overrides_for_tests: Mapping[str, str] | None,
) -> GenerationOutput:
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

    decomposition = _run_stage(
        trace,
        stage=StageName.QUESTION_DECOMPOSER,
        input_payload={"question": question},
        action=lambda: _mock_decompose(question),
    )

    retrieval_result = _run_stage(
        trace,
        stage=StageName.CANDIDATE_RETRIEVAL,
        input_payload=decomposition,
        action=lambda: CandidateRetriever(registry).retrieve(decomposition),
        output_payload=lambda result: result.model_dump(mode="json"),
        metrics=lambda result: {"candidate_count": len(result.candidates)},
    )

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

    grounded = _run_stage(
        trace,
        stage=StageName.GROUNDED_UNDERSTANDING,
        input_payload={
            "decomposition": decomposition,
            "resolved_literals": [result.model_dump(mode="json") for result in literal_results],
        },
        action=lambda: _mock_understand(decomposition, literal_results),
    )

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
        return _handle_repair_decision(
            trace,
            decision=_run_repair_controller_stage(
                trace,
                question=question,
                selected_bindings=plan.model_dump(mode="json"),
                validator_errors=[
                    issue.model_dump(mode="json")
                    for issue in validation_result.errors
                ],
                assumptions=validation_result.assumptions,
            ),
            fallback_details={"validation": validation_result.model_dump(mode="json")},
        )

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
                ),
                fallback_details={"self_validation": validation_result.model_dump(mode="json")},
            )
    except (CypherCompilerError, RestrictedDslValidationError, ValueError) as exc:
        return _failure(trace, reason="compiler_shape_mismatch", message=str(exc))

    return _generated(trace, dsl=dsl, cypher=compilation.cypher)


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
) -> RepairDecision:
    payload = {
        "schema_version": "repair_controller_input_v1",
        "trace_id": trace._trace_id,  # noqa: SLF001 - pipeline owns the trace builder lifecycle.
        "question": question,
        "attempt_no": 1,
        "selected_bindings": selected_bindings,
        "normalized_dsl": None,
        "validator_errors": validator_errors or [],
        "cypher_validation_errors": cypher_validation_errors or [],
        "history": [],
        "assumptions": assumptions or [],
    }
    return _run_stage(
        trace,
        stage=StageName.REPAIR_CONTROLLER,
        input_payload=payload,
        action=lambda: RepairController().decide(payload),
        output_payload=lambda result: result.model_dump(mode="json"),
    )


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
) -> GenerationOutput:
    _add_output_stage(
        trace,
        status="generated",
        payload={"status": "generated", "has_dsl": True, "has_cypher": True},
    )
    return trace.finalize_generated(dsl=dsl, cypher=cypher)


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
