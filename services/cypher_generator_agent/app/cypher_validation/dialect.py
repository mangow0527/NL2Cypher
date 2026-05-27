from __future__ import annotations

import re

from .models import CypherValidationIssue, validation_error
from .parser import ParsedCypher


DIALECT_FAILURE_CODE = "target_dialect_static_error"
MAX_VARIABLE_PATH_HOPS = 8
REL_PATTERN_RE = re.compile(r"\[(?P<body>[^\[\]]*)\]")
VARIABLE_LENGTH_RE = re.compile(r"\*(?P<range>\d*(?:\.\.\d*)?)?")
ALLOWED_FUNCTIONS = frozenset(
    {
        "avg",
        "coalesce",
        "collect",
        "count",
        "max",
        "min",
        "sum",
        "tofloat",
        "tointeger",
        "tostring",
    }
)
FUNCTION_CALL_RE = re.compile(r"(?P<name>[A-Za-z_][A-Za-z0-9_.]*)\s*\(")
CLAUSE_KEYWORDS = frozenset({"MATCH", "WHERE", "WITH", "RETURN", "ORDER", "LIMIT", "SKIP", "UNWIND"})
DYNAMIC_SCHEMA_RES = (
    re.compile(r"[\(\[][^\{\}\)\]]*:\s*\$"),
    re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\s*\[\s*\$[A-Za-z_][A-Za-z0-9_]*\s*\]"),
)
UNSUPPORTED_READ_FRAGMENTS = tuple(
    sorted(
        {
            "OPTIONAL MATCH",
            "USING INDEX",
            "USING SCAN",
            "USING JOIN",
            "UNION ALL",
            "UNION",
            "WHERE EXISTS",
            "DROP DATABASE",
        },
        key=lambda value: (-len(value.split()), -len(value)),
    )
)


def validate_target_dialect(parsed: ParsedCypher) -> list[CypherValidationIssue]:
    errors: list[CypherValidationIssue] = []
    _validate_unsupported_read_fragments(parsed, errors)
    _validate_no_dynamic_schema_references(parsed, errors)
    _validate_function_allowlist(parsed, errors)
    for match in REL_PATTERN_RE.finditer(parsed.cypher):
        body = match.group("body")
        variable_length = VARIABLE_LENGTH_RE.search(body)
        if variable_length is None:
            continue
        range_text = variable_length.group("range") or ""
        max_hops = _max_hops(range_text)
        if max_hops is None:
            errors.append(
                validation_error(
                    DIALECT_FAILURE_CODE,
                    "variable path must include an explicit max_hops upper bound",
                    "dialect",
                    match.group(0),
                )
            )
            continue
        if max_hops > MAX_VARIABLE_PATH_HOPS:
            errors.append(
                validation_error(
                    DIALECT_FAILURE_CODE,
                    f"variable path max_hops must be <= {MAX_VARIABLE_PATH_HOPS}",
                    "dialect",
                    match.group(0),
                )
            )
    return errors


def _validate_unsupported_read_fragments(
    parsed: ParsedCypher,
    errors: list[CypherValidationIssue],
) -> None:
    for name, start in _find_unsupported_read_fragments(parsed.cypher):
        errors.append(
            validation_error(
                DIALECT_FAILURE_CODE,
                f"read fragment {name} is not allowed in target dialect static subset",
                "dialect",
                f"char:{start}",
            )
        )


def _validate_no_dynamic_schema_references(
    parsed: ParsedCypher,
    errors: list[CypherValidationIssue],
) -> None:
    for pattern in DYNAMIC_SCHEMA_RES:
        for match in pattern.finditer(parsed.cypher):
            errors.append(
                validation_error(
                    DIALECT_FAILURE_CODE,
                    "dynamic label, relationship type, or property reference is not allowed",
                    "dialect",
                    match.group(0),
                )
            )


def _validate_function_allowlist(
    parsed: ParsedCypher,
    errors: list[CypherValidationIssue],
) -> None:
    for match in FUNCTION_CALL_RE.finditer(parsed.cypher):
        name = match.group("name")
        if name.upper() in CLAUSE_KEYWORDS:
            continue
        normalized = name.lower()
        if normalized in ALLOWED_FUNCTIONS:
            continue
        errors.append(
            validation_error(
                DIALECT_FAILURE_CODE,
                f"function {name} is not allowed in target dialect static subset",
                "dialect",
                name,
            )
        )


def _find_unsupported_read_fragments(cypher: str) -> list[tuple[str, int]]:
    findings: list[tuple[str, int]] = []
    upper = cypher.upper()
    index = 0
    while index < len(cypher):
        if _inside_string(cypher, index) or not _is_word_boundary(cypher, index, left=True):
            index += 1
            continue
        for phrase in UNSUPPORTED_READ_FRAGMENTS:
            pattern = r"\s+".join(re.escape(part) for part in phrase.split())
            match = re.match(pattern, upper[index:])
            if match is None:
                continue
            end = index + match.end()
            if end <= len(cypher) and _is_word_boundary(cypher, end, left=False):
                findings.append((phrase, index))
                index = end
                break
        else:
            index += 1
    return findings


def _max_hops(range_text: str) -> int | None:
    if not range_text:
        return None
    if ".." not in range_text:
        return int(range_text) if range_text else None
    _, upper = range_text.split("..", 1)
    return int(upper) if upper else None


def _is_word_boundary(text: str, index: int, *, left: bool) -> bool:
    if left:
        return index == 0 or not _is_identifier_char(text[index - 1])
    return index >= len(text) or not _is_identifier_char(text[index])


def _is_identifier_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def _inside_string(text: str, index: int) -> bool:
    quote: str | None = None
    escaped = False
    for char in text[:index]:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
    return quote is not None
