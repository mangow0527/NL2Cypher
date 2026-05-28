from __future__ import annotations

import re

from services.cypher_generator_agent.app.dsl.ast import Projection, ProjectionItem


RETURN_BODY_RE = re.compile(
    r"\bRETURN\b(?P<body>.*?)(?:\bORDER\s+BY\b|\bLIMIT\b|\bSKIP\b|$)",
    flags=re.IGNORECASE | re.DOTALL,
)
RETURN_ALIAS_RE = re.compile(r"\bAS\s+(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\s*$", flags=re.IGNORECASE)
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PROPERTY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.(?P<property>[A-Za-z_][A-Za-z0-9_]*)$")
PARAMETER_RE = re.compile(r"(?<![A-Za-z0-9_])\$(?P<name>[A-Za-z_][A-Za-z0-9_]*)")


def projection_aliases(projection: Projection) -> list[str]:
    aliases: list[str] = []
    for item in projection.items:
        aliases.append(projection_item_alias(item))
    return aliases


def projection_item_alias(item: ProjectionItem) -> str:
    if item.alias:
        return item.alias
    if item.property is not None:
        return item.property.name
    if item.source is not None:
        return item.source.name
    if item.vertex_full and item.target is not None:
        return item.target.alias
    raise ValueError("projection item must include alias, property, or source")


def extract_return_aliases(cypher: str) -> list[str]:
    match = RETURN_BODY_RE.search(cypher)
    if match is None:
        return []

    aliases: list[str] = []
    for raw_item in match.group("body").split(","):
        expression = raw_item.strip()
        if not expression:
            continue
        alias_match = RETURN_ALIAS_RE.search(expression)
        if alias_match:
            aliases.append(alias_match.group("alias"))
            continue
        if IDENTIFIER_RE.fullmatch(expression):
            aliases.append(expression)
            continue
        property_match = PROPERTY_RE.fullmatch(expression)
        if property_match:
            aliases.append(property_match.group("property"))
    return aliases


def extract_parameter_names(cypher: str) -> set[str]:
    return {match.group("name") for match in PARAMETER_RE.finditer(cypher)}


def is_cypher_identifier(value: str) -> bool:
    return IDENTIFIER_RE.fullmatch(value) is not None
