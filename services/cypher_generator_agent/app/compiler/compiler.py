from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re

from services.cypher_generator_agent.app.cypher_validation import (
    CypherSelfValidationResult,
    CypherSelfValidator,
)
from services.cypher_generator_agent.app.dsl.ast import (
    AggregateOperation,
    Dimension,
    Filter,
    FilterSubqueryOperation,
    Measure,
    MetricAggregateOperation,
    Projection,
    ProjectionItem,
    RestrictedQueryAst,
    RoleReference,
    SubqueryOperation,
    TraverseEdgeOperation,
    UsePathPatternOperation,
    VariablePathOperation,
)
from services.cypher_generator_agent.app.dsl.models import QueryShape
from services.cypher_generator_agent.app.semantic_model import GraphSemanticRegistry

from .projection import extract_return_aliases, projection_aliases, projection_item_alias
from .projection import extract_parameter_names, is_cypher_identifier
from .templates import get_path_pattern_template


CYPHER_COMPILATION_RESULT_SCHEMA_VERSION = "cypher_compilation_result_v1"
SUPPORTED_QUERY_SHAPES = {
    QueryShape.VERTEX_LOOKUP,
    QueryShape.SINGLE_HOP_TRAVERSAL,
    QueryShape.NAMED_PATH_PATTERN,
    QueryShape.VARIABLE_PATH_TRAVERSAL,
    QueryShape.METRIC_AGGREGATE,
    QueryShape.AD_HOC_AGGREGATE,
    QueryShape.TOP_N,
    QueryShape.TWO_STEP_AGGREGATE,
}
ROLE_VARIABLES = {
    "Service": "svc",
    "Tunnel": "tun",
    "NetworkElement": "ne",
    "Port": "port",
}
OPERATOR_CYPHER = {
    "eq": "=",
    "neq": "<>",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "in": "IN",
    "contains": "CONTAINS",
}


class CypherCompilerError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        validation_result: CypherSelfValidationResult | None = None,
    ) -> None:
        self.validation_result = validation_result
        super().__init__(message)


@dataclass(frozen=True)
class CypherCompilationDraft:
    schema_version: str
    cypher: str
    parameters: dict[str, object]
    expected_return_aliases: list[str]


@dataclass(frozen=True)
class CypherCompilationResult:
    schema_version: str
    cypher: str
    parameters: dict[str, object]
    validation_result: CypherSelfValidationResult


class CypherCompiler:
    def __init__(
        self,
        registry: GraphSemanticRegistry,
        *,
        _path_pattern_template_overrides_for_tests: Mapping[str, str] | None = None,
    ) -> None:
        self.registry = registry
        self._path_pattern_template_overrides_for_tests = _path_pattern_template_overrides_for_tests
        self.validator = CypherSelfValidator(registry)

    def compile_draft(self, ast: RestrictedQueryAst) -> CypherCompilationDraft:
        if ast.query_shape not in SUPPORTED_QUERY_SHAPES:
            raise CypherCompilerError(f"unsupported query_shape: {ast.query_shape.value}")

        if ast.query_shape is QueryShape.VERTEX_LOOKUP:
            cypher, parameters = self._compile_vertex_lookup(ast)
        elif ast.query_shape is QueryShape.SINGLE_HOP_TRAVERSAL:
            cypher, parameters = self._compile_single_hop(ast)
        elif ast.query_shape is QueryShape.NAMED_PATH_PATTERN:
            cypher, parameters = self._compile_named_path_pattern(ast)
        elif ast.query_shape is QueryShape.VARIABLE_PATH_TRAVERSAL:
            cypher, parameters = self._compile_variable_path(ast)
        elif ast.query_shape is QueryShape.METRIC_AGGREGATE:
            cypher, parameters = self._compile_metric_aggregate(ast)
        elif ast.query_shape is QueryShape.AD_HOC_AGGREGATE:
            cypher, parameters = self._compile_ad_hoc_aggregate(ast)
        elif ast.query_shape is QueryShape.TOP_N:
            cypher, parameters = self._compile_top_n(ast)
        elif ast.query_shape is QueryShape.TWO_STEP_AGGREGATE:
            cypher, parameters = self._compile_two_step_aggregate(ast)
        else:
            raise CypherCompilerError(f"unsupported query_shape: {ast.query_shape.value}")

        return CypherCompilationDraft(
            schema_version=CYPHER_COMPILATION_RESULT_SCHEMA_VERSION,
            cypher=cypher,
            parameters=parameters,
            expected_return_aliases=projection_aliases(ast.projection),
        )

    def compile(self, ast: RestrictedQueryAst) -> CypherCompilationResult:
        draft = self.compile_draft(ast)
        validation_result = self.validator.validate_generated_query(
            draft.cypher,
            expected_return_aliases=draft.expected_return_aliases,
        )
        if not validation_result.valid:
            raise CypherCompilerError("compiled Cypher self-validation failed", validation_result=validation_result)
        return CypherCompilationResult(
            schema_version=CYPHER_COMPILATION_RESULT_SCHEMA_VERSION,
            cypher=draft.cypher,
            parameters=draft.parameters,
            validation_result=validation_result,
        )

    def _compile_vertex_lookup(self, ast: RestrictedQueryAst) -> tuple[str, dict[str, object]]:
        role = _single_vertex_role(ast)
        variable = _variable_for_owner(role.vertex_name, used=set())
        role_variables = {role.alias: variable}
        parameters = _ParameterBuilder()

        clauses = [f"MATCH ({variable}:{role.vertex_name})"]
        where = _compile_filters(ast.filters, role_variables, parameters)
        if where:
            clauses.append(f"WHERE {' AND '.join(where)}")
        clauses.append(_compile_return(ast.projection, role_variables))
        return "\n".join(clauses), parameters.values

    def _compile_metric_aggregate(self, ast: RestrictedQueryAst) -> tuple[str, dict[str, object]]:
        operation = _single_operation(ast, MetricAggregateOperation)
        metric = self.registry.get_metric(operation.metric_name)
        if not metric.pattern or not metric.expression:
            raise CypherCompilerError("metric_aggregate compiler requires pattern + expression metric")

        aliases = _metric_aliases(metric.pattern)
        parameters = _ParameterBuilder()
        role_variables = {
            dimension.target_alias: dimension.target_alias for dimension in operation.group_by
        }
        for filter_item in operation.filters:
            if filter_item.target is None:
                raise CypherCompilerError("metric_aggregate filters require metric target alias")
            role_variables[filter_item.target.alias] = filter_item.target.alias
        for alias in aliases:
            role_variables.setdefault(alias, alias)

        source_expressions: dict[tuple[str, str], str] = {
            ("metric", operation.metric_name): metric.expression,
        }
        for dimension in operation.group_by:
            source_expressions[("group", dimension.alias)] = (
                f"{dimension.target_alias}.{dimension.property.name}"
            )

        clauses = [f"MATCH {metric.pattern}"]
        where = _compile_filters(operation.filters, role_variables, parameters)
        if where:
            clauses.append(f"WHERE {' AND '.join(where)}")
        clauses.append(_compile_source_return(ast.projection, source_expressions))
        _append_order_limit(clauses, ast, source_expressions)
        return "\n".join(clauses), parameters.values

    def _compile_ad_hoc_aggregate(self, ast: RestrictedQueryAst) -> tuple[str, dict[str, object]]:
        operation = _single_operation(ast, AggregateOperation)
        roles = _aggregate_roles(operation, ast.filters)
        role_variables = _role_variables(roles.values())
        parameters = _ParameterBuilder()
        source_expressions = _aggregate_source_expressions(
            operation.group_by,
            operation.measures,
            role_variables,
        )

        clauses = [_compile_aggregate_match(roles, role_variables)]
        where = _compile_filters(ast.filters, role_variables, parameters)
        if where:
            clauses.append(f"WHERE {' AND '.join(where)}")
        clauses.append(_compile_source_return(ast.projection, source_expressions))
        _append_order_limit(clauses, ast, source_expressions)
        return "\n".join(clauses), parameters.values

    def _compile_top_n(self, ast: RestrictedQueryAst) -> tuple[str, dict[str, object]]:
        primary_operation = ast.operations[0] if ast.operations else None
        if isinstance(primary_operation, MetricAggregateOperation):
            return self._compile_metric_aggregate(ast)
        if isinstance(primary_operation, AggregateOperation):
            return self._compile_ad_hoc_aggregate(ast)
        raise CypherCompilerError("top_n requires aggregate or metric_aggregate operation")

    def _compile_two_step_aggregate(self, ast: RestrictedQueryAst) -> tuple[str, dict[str, object]]:
        subquery = _single_operation(ast, SubqueryOperation)
        roles = _aggregate_roles_from_parts(subquery.group_by, subquery.measures, [])
        role_variables = _role_variables(roles.values())
        parameters = _ParameterBuilder()
        source_expressions = _aggregate_source_expressions(
            subquery.group_by,
            subquery.measures,
            role_variables,
        )

        clauses = [_compile_aggregate_match(roles, role_variables)]
        clauses.append(_compile_with(subquery.group_by, subquery.measures, source_expressions))

        filter_where = _compile_filter_subqueries(ast, subquery, parameters)
        if filter_where:
            clauses.append(f"WHERE {' AND '.join(filter_where)}")

        subquery_sources = {
            (subquery.bind_as, dimension.alias): dimension.alias for dimension in subquery.group_by
        }
        subquery_sources.update(
            {
                (subquery.bind_as, measure.alias): measure.alias
                for measure in subquery.measures
            }
        )
        clauses.append(_compile_source_return(ast.projection, subquery_sources))
        _append_order_limit(clauses, ast, subquery_sources)
        return "\n".join(clauses), parameters.values

    def _compile_single_hop(self, ast: RestrictedQueryAst) -> tuple[str, dict[str, object]]:
        operation = _single_operation(ast, TraverseEdgeOperation)
        used: set[str] = set()
        from_var = _variable_for_owner(operation.from_role.vertex_name, used=used)
        to_var = _variable_for_owner(operation.to_role.vertex_name, used=used)
        role_variables = {
            operation.from_role.alias: from_var,
            operation.to_role.alias: to_var,
        }
        parameters = _ParameterBuilder()

        if operation.direction == "forward":
            match_clause = (
                f"MATCH ({from_var}:{operation.from_role.vertex_name})"
                f"-[:{operation.edge_role.edge_name}]->"
                f"({to_var}:{operation.to_role.vertex_name})"
            )
        elif operation.direction == "backward":
            match_clause = (
                f"MATCH ({from_var}:{operation.from_role.vertex_name})"
                f"<-[:{operation.edge_role.edge_name}]-"
                f"({to_var}:{operation.to_role.vertex_name})"
            )
        else:
            raise CypherCompilerError(f"unsupported traversal direction: {operation.direction}")

        clauses = [match_clause]
        where = _compile_filters(ast.filters, role_variables, parameters)
        if where:
            clauses.append(f"WHERE {' AND '.join(where)}")
        clauses.append(_compile_return(ast.projection, role_variables))
        return "\n".join(clauses), parameters.values

    def _compile_named_path_pattern(self, ast: RestrictedQueryAst) -> tuple[str, dict[str, object]]:
        operation = _single_operation(ast, UsePathPatternOperation)
        cypher = _get_path_pattern_template_for_compile(
            self.registry,
            operation.path_pattern_name,
            self._path_pattern_template_overrides_for_tests,
        )
        expected_aliases = projection_aliases(ast.projection)
        actual_aliases = extract_return_aliases(cypher)
        if actual_aliases != expected_aliases:
            raise CypherCompilerError(
                "path_pattern RETURN aliases must match DSL projection aliases: "
                f"expected {expected_aliases}, got {actual_aliases}"
            )
        parameters = {key: value.effective_value for key, value in operation.parameters.items()}
        _validate_template_parameters(cypher, parameters)
        return cypher, parameters

    def _compile_variable_path(self, ast: RestrictedQueryAst) -> tuple[str, dict[str, object]]:
        operation = _single_operation(ast, VariablePathOperation)
        if len(operation.allowed_edges) != 1:
            raise CypherCompilerError("variable_path compiler MVP requires exactly one allowed edge")
        if operation.max_hops > 8:
            raise CypherCompilerError("variable_path max_hops must be <= 8")

        used: set[str] = set()
        start_var = _variable_for_owner(operation.start.vertex_name, used=used)
        through_var = _variable_for_owner(operation.through.vertex_name, used=used)
        role_variables = {
            operation.start.alias: start_var,
            operation.through.alias: through_var,
        }
        parameters = _ParameterBuilder()
        edge_name = operation.allowed_edges[0]

        clauses = [
            (
                f"MATCH {operation.bind_as} = ({start_var}:{operation.start.vertex_name})"
                f"-[:{edge_name}*{operation.min_hops}..{operation.max_hops}]->"
                f"({through_var}:{operation.through.vertex_name})"
            )
        ]
        where = _compile_filters([*operation.through_filters, *ast.filters], role_variables, parameters)
        if where:
            clauses.append(f"WHERE {' AND '.join(where)}")
        clauses.append(_compile_return(ast.projection, role_variables))
        return "\n".join(clauses), parameters.values


class _ParameterBuilder:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def add(self, base_name: str, value: object) -> str:
        name = _sanitize_identifier(base_name)
        if name not in self.values:
            self.values[name] = value
            return name

        index = 2
        while f"{name}_{index}" in self.values:
            index += 1
        unique_name = f"{name}_{index}"
        self.values[unique_name] = value
        return unique_name


def compile_restricted_query_ast(
    ast: RestrictedQueryAst,
    registry: GraphSemanticRegistry,
) -> CypherCompilationResult:
    return CypherCompiler(registry).compile(ast)


def _single_operation(ast: RestrictedQueryAst, expected_type):
    matches = [operation for operation in ast.operations if isinstance(operation, expected_type)]
    if len(matches) != 1:
        raise CypherCompilerError(f"expected exactly one {expected_type.__name__} operation")
    return matches[0]


def _single_vertex_role(ast: RestrictedQueryAst):
    roles = []
    for filter_item in ast.filters:
        if filter_item.target is not None:
            roles.append(filter_item.target)
    for item in ast.projection.items:
        if item.target is not None:
            roles.append(item.target)

    unique: dict[str, object] = {}
    for role in roles:
        unique[role.alias] = role
    if len(unique) != 1:
        raise CypherCompilerError("vertex_lookup requires exactly one vertex role")
    return next(iter(unique.values()))


def _compile_filters(
    filters: list[Filter],
    role_variables: Mapping[str, str],
    parameters: _ParameterBuilder,
) -> list[str]:
    compiled: list[str] = []
    for filter_item in filters:
        if filter_item.target is None:
            raise CypherCompilerError("filter target is required for compiler MVP")
        variable = role_variables[filter_item.target.alias]
        operator = OPERATOR_CYPHER.get(filter_item.operator)
        if operator is None:
            raise CypherCompilerError(f"unsupported filter operator: {filter_item.operator}")
        parameter_name = parameters.add(filter_item.property.name, filter_item.value.effective_value)
        compiled.append(f"{variable}.{filter_item.property.name} {operator} ${parameter_name}")
    return compiled


def _compile_return(projection: Projection, role_variables: Mapping[str, str]) -> str:
    items = [_compile_projection_item(item, role_variables) for item in projection.items]
    return f"RETURN {', '.join(items)}"


def _compile_source_return(
    projection: Projection,
    source_expressions: Mapping[tuple[str, str], str],
) -> str:
    items = [_compile_source_projection_item(item, source_expressions) for item in projection.items]
    return f"RETURN {', '.join(items)}"


def _compile_source_projection_item(
    item: ProjectionItem,
    source_expressions: Mapping[tuple[str, str], str],
) -> str:
    if item.source is None:
        raise CypherCompilerError("source projection is required for aggregate compiler MVP")
    expression = source_expressions.get((item.source.namespace, item.source.name))
    if expression is None:
        raise CypherCompilerError(f"unknown aggregate projection source: {item.source.raw}")
    alias = projection_item_alias(item)
    if not is_cypher_identifier(alias):
        raise CypherCompilerError(f"invalid projection alias: {alias}")
    return f"{expression} AS {alias}"


def _append_order_limit(
    clauses: list[str],
    ast: RestrictedQueryAst,
    source_expressions: Mapping[tuple[str, str], str],
) -> None:
    if ast.sort:
        source_aliases = _projection_source_aliases(ast.projection)
        order_items = []
        for sort_item in ast.sort:
            key = (sort_item.source.namespace, sort_item.source.name)
            expression = source_aliases.get(key) or source_expressions.get(key)
            if expression is None:
                raise CypherCompilerError(f"unknown sort source: {sort_item.source.raw}")
            order_items.append(f"{expression} {sort_item.direction.upper()}")
        clauses.append(f"ORDER BY {', '.join(order_items)}")
    if ast.limit is not None:
        clauses.append(f"LIMIT {ast.limit}")


def _projection_source_aliases(projection: Projection) -> dict[tuple[str, str], str]:
    aliases: dict[tuple[str, str], str] = {}
    for item in projection.items:
        if item.source is None:
            continue
        alias = projection_item_alias(item)
        if not is_cypher_identifier(alias):
            raise CypherCompilerError(f"invalid projection alias: {alias}")
        aliases[(item.source.namespace, item.source.name)] = alias
    return aliases


def _compile_projection_item(item: ProjectionItem, role_variables: Mapping[str, str]) -> str:
    if item.target is None or item.property is None:
        raise CypherCompilerError("target/property projection is required for generated query compiler MVP")
    variable = role_variables[item.target.alias]
    alias = projection_item_alias(item)
    if not is_cypher_identifier(alias):
        raise CypherCompilerError(f"invalid projection alias: {alias}")
    return f"{variable}.{item.property.name} AS {alias}"


def _compile_with(
    group_by: list[Dimension],
    measures: list[Measure],
    source_expressions: Mapping[tuple[str, str], str],
) -> str:
    items: list[str] = []
    for dimension in group_by:
        items.append(f"{source_expressions[('group', dimension.alias)]} AS {dimension.alias}")
    for measure in measures:
        items.append(f"{source_expressions[('measure', measure.alias)]} AS {measure.alias}")
    return f"WITH {', '.join(items)}"


def _compile_filter_subqueries(
    ast: RestrictedQueryAst,
    subquery: SubqueryOperation,
    parameters: _ParameterBuilder,
) -> list[str]:
    output_aliases = {dimension.alias for dimension in subquery.group_by} | {
        measure.alias for measure in subquery.measures
    }
    compiled: list[str] = []
    for operation in ast.operations:
        if not isinstance(operation, FilterSubqueryOperation):
            continue
        if operation.source != subquery.bind_as:
            raise CypherCompilerError(f"filter_subquery source not found: {operation.source}")
        if operation.predicate.property not in output_aliases:
            raise CypherCompilerError(f"filter_subquery output not found: {operation.predicate.property}")
        operator = OPERATOR_CYPHER.get(operation.predicate.operator)
        if operator is None:
            raise CypherCompilerError(f"unsupported filter_subquery operator: {operation.predicate.operator}")
        parameter_name = parameters.add(operation.predicate.property, operation.predicate.value.effective_value)
        compiled.append(f"{operation.predicate.property} {operator} ${parameter_name}")
    return compiled


def _aggregate_roles(
    operation: AggregateOperation,
    filters: list[Filter],
) -> dict[str, object]:
    return _aggregate_roles_from_parts(operation.group_by, operation.measures, filters)


def _aggregate_roles_from_parts(
    group_by: list[Dimension],
    measures: list[Measure],
    filters: list[Filter],
) -> dict[str, RoleReference]:
    roles: dict[str, object] = {}
    for dimension in group_by:
        roles[dimension.target.alias] = dimension.target
    for measure in measures:
        roles[measure.target.alias] = measure.target
    for filter_item in filters:
        if filter_item.target is not None:
            roles[filter_item.target.alias] = filter_item.target
    return roles


def _role_variables(roles: object) -> dict[str, str]:
    used: set[str] = set()
    return {
        role.alias: _variable_for_owner(role.vertex_name, used=used)
        for role in roles
    }


def _aggregate_source_expressions(
    group_by: list[Dimension],
    measures: list[Measure],
    role_variables: Mapping[str, str],
) -> dict[tuple[str, str], str]:
    source_expressions: dict[tuple[str, str], str] = {}
    for dimension in group_by:
        source_expressions[("group", dimension.alias)] = (
            f"{role_variables[dimension.target.alias]}.{dimension.property.name}"
        )
    for measure in measures:
        variable = role_variables[measure.target.alias]
        source_expressions[("measure", measure.alias)] = (
            f"{measure.function}({variable}.{measure.property.name})"
        )
    return source_expressions


def _compile_aggregate_match(
    roles: Mapping[str, RoleReference],
    role_variables: Mapping[str, str],
) -> str:
    role_values = list(roles.values())
    if len(role_values) == 1:
        role = role_values[0]
        return f"MATCH ({role_variables[role.alias]}:{role.vertex_name})"
    raise CypherCompilerError(
        "ad_hoc aggregate compiler requires exactly one vertex role; use a metric for edge-connected aggregates"
    )


def _variable_for_owner(owner: str, *, used: set[str]) -> str:
    base = ROLE_VARIABLES.get(owner, owner[:1].lower() or "v")
    variable = base
    index = 2
    while variable in used:
        variable = f"{base}{index}"
        index += 1
    used.add(variable)
    return variable


def _sanitize_identifier(value: str) -> str:
    sanitized = "".join(char if char.isalnum() or char == "_" else "_" for char in value)
    if not sanitized:
        return "param"
    if sanitized[0].isdigit():
        return f"param_{sanitized}"
    return sanitized


def _metric_aliases(pattern: str) -> dict[str, str]:
    return dict(
        match.groups()
        for match in re.finditer(
            r"\(([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([A-Za-z_][A-Za-z0-9_]*)\)",
            pattern,
        )
    )


def _get_path_pattern_template_for_compile(
    registry: GraphSemanticRegistry,
    path_pattern_name: str,
    test_overrides: Mapping[str, str] | None,
) -> str:
    if test_overrides and path_pattern_name in test_overrides:
        return test_overrides[path_pattern_name].strip()
    return get_path_pattern_template(registry, path_pattern_name)


def _validate_template_parameters(cypher: str, parameters: Mapping[str, object]) -> None:
    template_parameters = extract_parameter_names(cypher)
    provided_parameters = set(parameters)
    if template_parameters != provided_parameters:
        raise CypherCompilerError(
            "path_pattern template parameters must match DSL parameters: "
            f"template={sorted(template_parameters)}, provided={sorted(provided_parameters)}"
        )
