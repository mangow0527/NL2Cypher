from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from services.cypher_generator_agent.app.binding.models import (
    BindingPlan,
    FilterBinding,
    LiteralBinding,
)
from services.cypher_generator_agent.app.semantic_model import GraphSemanticRegistry

from .parser import parse_restricted_query_dsl


class RestrictedDslBuilder:
    def __init__(self, registry: GraphSemanticRegistry) -> None:
        self.registry = registry

    def build(
        self,
        plan: BindingPlan,
        *,
        source_question: str,
        query_id: str,
    ) -> dict[str, Any]:
        self._reject_uncompiled_sort_limit(plan)
        if plan.query_shape == "single_hop_traversal":
            dsl = self._build_single_hop(plan, source_question=source_question, query_id=query_id)
        elif plan.query_shape == "named_path_pattern":
            dsl = self._build_named_path_pattern(plan, source_question=source_question, query_id=query_id)
        else:
            raise ValueError(f"unsupported query_shape for restricted DSL builder: {plan.query_shape}")

        parse_restricted_query_dsl(dsl, self.registry)
        return dsl

    def _reject_uncompiled_sort_limit(self, plan: BindingPlan) -> None:
        if plan.sort or plan.limit is not None:
            raise ValueError(
                f"{plan.query_shape} sort/limit is not supported until the Cypher compiler consumes it"
            )

    def _build_single_hop(
        self,
        plan: BindingPlan,
        *,
        source_question: str,
        query_id: str,
    ) -> dict[str, Any]:
        if len(plan.vertex_bindings) < 2 or not plan.edge_bindings:
            raise ValueError("single_hop_traversal requires start/end vertices and one edge")

        start = plan.vertex_bindings[0]
        end = plan.vertex_bindings[1]
        edge = plan.edge_bindings[0]
        role_by_owner = {start.name: "start", end.name: "end"}

        dsl = self._base_payload(plan, source_question=source_question, query_id=query_id)
        dsl["bindings"] = {
            "start": {"vertex_name": start.name},
            "edge": {"edge_name": edge.name},
            "end": {"vertex_name": end.name},
        }
        dsl["operations"] = [
            {
                "op": "traverse_edge",
                "from": "start",
                "edge": "edge",
                "to": "end",
                "direction": edge.direction,
            }
        ]
        self._add_filters_projection_sort_limit(dsl, plan, role_by_owner=role_by_owner, include_filters=True)
        return dsl

    def _build_named_path_pattern(
        self,
        plan: BindingPlan,
        *,
        source_question: str,
        query_id: str,
    ) -> dict[str, Any]:
        if not plan.path_pattern_bindings:
            raise ValueError("named_path_pattern requires one path pattern binding")

        primary_vertex = plan.vertex_bindings[0] if plan.vertex_bindings else None
        path_pattern_name = plan.path_pattern_bindings[0].name
        dsl = self._base_payload(plan, source_question=source_question, query_id=query_id)
        dsl["bindings"] = (
            {"primary_vertex": {"vertex_name": primary_vertex.name}}
            if primary_vertex is not None
            else {}
        )
        dsl["operations"] = [
            {
                "op": "use_path_pattern",
                "path_pattern_name": path_pattern_name,
                "bind_as": "path",
                "parameters": self._path_pattern_parameters(
                    plan,
                    path_pattern_name,
                    primary_vertex.name if primary_vertex else None,
                ),
            }
        ]
        self._add_filters_projection_sort_limit(dsl, plan, role_by_owner={}, include_filters=False)
        return dsl

    def _base_payload(
        self,
        plan: BindingPlan,
        *,
        source_question: str,
        query_id: str,
    ) -> dict[str, Any]:
        dsl: dict[str, Any] = {
            "schema_version": "restricted_query_dsl_v1",
            "query_id": query_id,
            "query_shape": plan.query_shape,
            "source_question": source_question,
            "bindings": {},
            "operations": [],
        }
        if plan.assumptions:
            dsl["assumptions"] = plan.assumptions
        return dsl

    def _add_filters_projection_sort_limit(
        self,
        dsl: dict[str, Any],
        plan: BindingPlan,
        *,
        role_by_owner: dict[str, str],
        include_filters: bool,
    ) -> None:
        if include_filters:
            filters = [self._filter_item(item, role_by_owner) for item in plan.filters]
            if filters:
                dsl["filters"] = filters

        dsl["projection"] = {"items": self._projection_items(plan, role_by_owner)}

        if plan.sort:
            dsl["operations"].append({"op": "sort", "by": [self._sort_item(item) for item in plan.sort]})
        if plan.limit is not None:
            dsl["operations"].append({"op": "limit", "value": plan.limit})

    def _filter_item(
        self,
        item: FilterBinding,
        role_by_owner: dict[str, str],
    ) -> dict[str, Any]:
        filter_item: dict[str, Any] = {
            "property": {"owner": item.owner, "name": item.property},
            "operator": item.operator,
            "value": self._value_from_filter(item),
        }
        target = role_by_owner.get(item.owner)
        if target is not None:
            filter_item["target"] = target
        return filter_item

    def _projection_items(
        self,
        plan: BindingPlan,
        role_by_owner: dict[str, str],
    ) -> list[dict[str, Any]]:
        return [self._projection_item(item, role_by_owner) for item in plan.projection]

    def _projection_item(
        self,
        item: Mapping[str, Any],
        role_by_owner: dict[str, str],
    ) -> dict[str, Any]:
        if "source" in item:
            projection = {"source": item["source"]}
            if item.get("alias") is not None:
                projection["alias"] = item["alias"]
            return projection

        property_ref = item.get("property")
        if isinstance(property_ref, Mapping):
            projection = {
                "target": self._projection_target(item, property_ref, role_by_owner),
                "property": {"owner": property_ref["owner"], "name": property_ref["name"]},
            }
            if item.get("alias") is not None:
                projection["alias"] = item["alias"]
            return projection

        if item.get("semantic_type") == "vertex":
            vertex_name = str(item["name"])
            vertex = self.registry.get_vertex(vertex_name)
            id_property = vertex.id_property
            return {
                "alias": item.get("alias") or f"{_snake_case(vertex_name)}_{id_property}",
                "target": role_by_owner[vertex_name],
                "property": {"owner": vertex_name, "name": id_property},
            }

        if item.get("semantic_type") == "property":
            owner = str(item["owner"])
            name = str(item["name"])
            projection = {
                "alias": item.get("alias") or name,
                "target": role_by_owner[owner],
                "property": {"owner": owner, "name": name},
            }
            return projection

        raise ValueError(f"unsupported projection item for restricted DSL builder: {item!r}")

    def _projection_target(
        self,
        item: Mapping[str, Any],
        property_ref: Mapping[str, Any],
        role_by_owner: dict[str, str],
    ) -> str:
        target = item.get("target")
        if target in role_by_owner.values():
            return str(target)
        owner = str(property_ref["owner"])
        return role_by_owner.get(owner, str(target))

    def _sort_item(self, item: Mapping[str, Any]) -> dict[str, Any]:
        if "source" not in item:
            raise ValueError(f"restricted DSL sort item requires a source reference: {item!r}")
        return {"source": item["source"], "direction": item.get("direction", "asc")}

    def _value_from_filter(self, item: FilterBinding) -> dict[str, Any]:
        if item.literal is not None:
            return self._value_from_literal(item.literal)
        return {
            "raw": item.raw_literal,
            "normalized": item.value,
            "resolver_match_type": None,
        }

    def _value_from_literal(self, literal: LiteralBinding) -> dict[str, Any]:
        return {
            "raw": literal.raw_literal,
            "normalized": literal.normalized_value if literal.normalized_value is not None else literal.value,
            "resolver_match_type": literal.match_type,
        }

    def _path_pattern_parameters(
        self,
        plan: BindingPlan,
        path_pattern_name: str,
        primary_vertex_name: str | None,
    ) -> dict[str, Any]:
        path_pattern = self.registry.get_path_pattern(path_pattern_name)
        parameters: dict[str, Any] = {}
        consumed_filters: set[int] = set()
        for parameter in path_pattern.parameters:
            literal = self._literal_for_parameter(plan, parameter.name, primary_vertex_name)
            if literal is not None:
                parameters[parameter.name] = self._value_from_literal(literal)
                consumed_filters.update(
                    self._filter_indices_for_parameter(plan, parameter.name, primary_vertex_name)
                )
                continue

            filter_index, filter_item = self._filter_for_parameter(plan, parameter.name, primary_vertex_name)
            if filter_item is not None:
                parameters[parameter.name] = self._value_from_filter(filter_item)
                if filter_index is not None:
                    consumed_filters.add(filter_index)
        self._raise_on_unrepresented_path_filters(plan, consumed_filters, path_pattern_name)
        return parameters

    def _literal_for_parameter(
        self,
        plan: BindingPlan,
        parameter_name: str,
        primary_vertex_name: str | None,
    ) -> LiteralBinding | None:
        for literal in plan.literal_bindings:
            if self._matches_parameter(parameter_name, literal.owner, literal.property, primary_vertex_name):
                return literal
        for filter_item in plan.filters:
            if filter_item.literal is not None and self._matches_parameter(
                parameter_name,
                filter_item.owner,
                filter_item.property,
                primary_vertex_name,
            ):
                return filter_item.literal
        return None

    def _filter_for_parameter(
        self,
        plan: BindingPlan,
        parameter_name: str,
        primary_vertex_name: str | None,
    ) -> tuple[int | None, FilterBinding | None]:
        for index, filter_item in enumerate(plan.filters):
            if self._filter_matches_parameter(filter_item, parameter_name, primary_vertex_name):
                return index, filter_item
        return None, None

    def _filter_indices_for_parameter(
        self,
        plan: BindingPlan,
        parameter_name: str,
        primary_vertex_name: str | None,
    ) -> set[int]:
        return {
            index
            for index, filter_item in enumerate(plan.filters)
            if self._filter_matches_parameter(filter_item, parameter_name, primary_vertex_name)
        }

    def _filter_matches_parameter(
        self,
        filter_item: FilterBinding,
        parameter_name: str,
        primary_vertex_name: str | None,
    ) -> bool:
        return filter_item.operator == "eq" and self._matches_parameter(
            parameter_name,
            filter_item.owner,
            filter_item.property,
            primary_vertex_name,
        )

    def _raise_on_unrepresented_path_filters(
        self,
        plan: BindingPlan,
        consumed_filters: set[int],
        path_pattern_name: str,
    ) -> None:
        unrepresented = [
            f"{filter_item.owner}.{filter_item.property}"
            for index, filter_item in enumerate(plan.filters)
            if index not in consumed_filters
        ]
        if unrepresented:
            raise ValueError(
                f"named_path_pattern {path_pattern_name} filters cannot be represented "
                f"by template parameters: {', '.join(unrepresented)}"
            )

    def _matches_parameter(
        self,
        parameter_name: str,
        owner: str | None,
        property_name: str,
        primary_vertex_name: str | None,
    ) -> bool:
        if owner is None:
            return parameter_name == property_name

        expected_names = {property_name, f"{_snake_case(owner)}_{property_name}"}
        if primary_vertex_name == owner:
            id_property = self.registry.get_vertex(owner).id_property
            if property_name == id_property:
                expected_names.add(f"{_snake_case(owner)}_id")
        return parameter_name in expected_names


def _snake_case(value: str) -> str:
    value = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return value.replace("-", "_").lower()
