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
MAP_PROJECTION_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\s*\{[^{}]*\}")
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
    _validate_no_projection_comprehension_fragments(parsed, errors)
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


def _validate_no_projection_comprehension_fragments(
    parsed: ParsedCypher,
    errors: list[CypherValidationIssue],
) -> None:
    for location in _iter_map_projection_locations(parsed):
        errors.append(
            validation_error(
                DIALECT_FAILURE_CODE,
                "map projection is not allowed in target dialect static subset",
                "dialect",
                location,
            )
        )
    for location in _iter_pattern_comprehension_locations(parsed.cypher):
        errors.append(
            validation_error(
                DIALECT_FAILURE_CODE,
                "pattern comprehension is not allowed in target dialect static subset",
                "dialect",
                location,
            )
        )


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
        for match in _iter_unquoted_matches(pattern, parsed.cypher):
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


def _iter_unquoted_matches(pattern: re.Pattern[str], text: str):
    for match in pattern.finditer(text):
        if _inside_string(text, match.start()):
            continue
        yield match


def _iter_map_projection_locations(parsed: ParsedCypher) -> list[str]:
    locations: list[str] = []
    for clause in parsed.clauses:
        if clause.name not in {"RETURN", "WITH"}:
            continue
        clause_body = clause.text[len(clause.name) :].strip()
        for match in _iter_unquoted_matches(MAP_PROJECTION_RE, clause_body):
            locations.append(match.group(0))
    return locations


def _iter_pattern_comprehension_locations(text: str) -> list[str]:
    locations: list[str] = []
    for start, end in _iter_square_bracket_spans(text):
        body = text[start + 1 : end]
        if "|" not in body:
            continue
        scan_body = _replace_string_literals(body)
        if re.search(r"\([^)]*\)\s*(?:<-|--|-)\s*(?:\[[^\[\]]*\]\s*)?(?:->|-)?\s*\([^)]*\)", scan_body):
            locations.append(text[start : end + 1])
    return locations


def _iter_square_bracket_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    stack: list[int] = []
    for index, char in enumerate(text):
        if _inside_string(text, index):
            continue
        if char == "[":
            stack.append(index)
            continue
        if char == "]" and stack:
            start = stack.pop()
            spans.append((start, index))
    return spans


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


def _replace_string_literals(text: str) -> str:
    chars = list(text)
    quote: str | None = None
    escaped = False
    for index, char in enumerate(chars):
        if escaped:
            chars[index] = " "
            escaped = False
            continue
        if char == "\\":
            if quote:
                chars[index] = " "
            escaped = True
            continue
        if quote:
            chars[index] = " "
            if char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            chars[index] = " "
            quote = char
    return "".join(chars)
