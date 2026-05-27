from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from services.cypher_generator_agent.app.cypher_validation import (
    CypherSelfValidationResult,
    CypherSelfValidator,
)
from services.cypher_generator_agent.app.dsl.ast import (
    Filter,
    Projection,
    ProjectionItem,
    RestrictedQueryAst,
    TraverseEdgeOperation,
    UsePathPatternOperation,
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

    def compile(self, ast: RestrictedQueryAst) -> CypherCompilationResult:
        if ast.query_shape not in SUPPORTED_QUERY_SHAPES:
            raise CypherCompilerError(f"unsupported query_shape: {ast.query_shape.value}")

        if ast.query_shape is QueryShape.VERTEX_LOOKUP:
            cypher, parameters = self._compile_vertex_lookup(ast)
        elif ast.query_shape is QueryShape.SINGLE_HOP_TRAVERSAL:
            cypher, parameters = self._compile_single_hop(ast)
        elif ast.query_shape is QueryShape.NAMED_PATH_PATTERN:
            cypher, parameters = self._compile_named_path_pattern(ast)
        else:
            raise CypherCompilerError(f"unsupported query_shape: {ast.query_shape.value}")

        validation_result = self.validator.validate_generated_query(cypher)
        if not validation_result.valid:
            raise CypherCompilerError("compiled Cypher self-validation failed", validation_result=validation_result)
        return CypherCompilationResult(
            schema_version=CYPHER_COMPILATION_RESULT_SCHEMA_VERSION,
            cypher=cypher,
            parameters=parameters,
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


def _compile_projection_item(item: ProjectionItem, role_variables: Mapping[str, str]) -> str:
    if item.target is None or item.property is None:
        raise CypherCompilerError("target/property projection is required for generated query compiler MVP")
    variable = role_variables[item.target.alias]
    alias = projection_item_alias(item)
    if not is_cypher_identifier(alias):
        raise CypherCompilerError(f"invalid projection alias: {alias}")
    return f"{variable}.{item.property.name} AS {alias}"


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
