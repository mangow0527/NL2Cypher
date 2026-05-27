from __future__ import annotations

from dataclasses import dataclass
import re

from .models import CypherValidationIssue, validation_error


ALLOWED_READ_CLAUSES = {"MATCH", "WHERE", "WITH", "RETURN", "ORDER BY", "LIMIT", "SKIP", "UNWIND"}
MUTATING_CLAUSES = {
    "CREATE",
    "MERGE",
    "SET",
    "DELETE",
    "DETACH DELETE",
    "REMOVE",
    "CALL",
    "LOAD CSV",
    "FOREACH",
    "CREATE INDEX",
    "DROP INDEX",
    "CREATE CONSTRAINT",
    "DROP CONSTRAINT",
}
KNOWN_CLAUSES = ALLOWED_READ_CLAUSES | MUTATING_CLAUSES
CLAUSE_PHRASES = tuple(sorted(KNOWN_CLAUSES, key=lambda value: (-len(value.split()), -len(value))))
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
SYNTAX_FAILURE_CODE = "cypher_syntax_invalid"


@dataclass(frozen=True)
class Clause:
    name: str
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class ParsedCypher:
    cypher: str
    clauses: list[Clause]


def parse_cypher(cypher: str) -> tuple[ParsedCypher | None, list[CypherValidationIssue]]:
    statement = cypher.strip()
    if not statement:
        return None, [_syntax_error("cypher must not be empty")]

    if _contains_unquoted_semicolon(cypher):
        return None, [_syntax_error("cypher must contain exactly one statement without semicolon chaining")]

    unsupported_fragment = _find_unsupported_read_fragment(cypher)
    if unsupported_fragment is not None:
        name, start = unsupported_fragment
        return None, [_syntax_error(f"unsupported Cypher read fragment: {name}", f"char:{start}")]

    starts = _find_clause_starts(cypher)
    if not starts:
        return None, [_syntax_error("cypher must start with a supported clause")]

    leading_text = cypher[: starts[0][0]].strip()
    if leading_text:
        return None, [_syntax_error("cypher must start with a supported clause", f"char:{0}")]

    clauses: list[Clause] = []
    for index, (start, name) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(cypher)
        text = cypher[start:end].strip()
        clauses.append(Clause(name=name, text=text, start=start, end=end))

    return ParsedCypher(cypher=cypher, clauses=clauses), []


def _syntax_error(message: str, location: str = "$") -> CypherValidationIssue:
    return validation_error(SYNTAX_FAILURE_CODE, message, "syntax", location)


def _contains_unquoted_semicolon(text: str) -> bool:
    for index, char in enumerate(text):
        if char == ";" and not _inside_string(text, index):
            return True
    return False


def _find_clause_starts(cypher: str) -> list[tuple[int, str]]:
    starts: list[tuple[int, str]] = []
    upper = cypher.upper()
    index = 0
    while index < len(cypher):
        if _inside_string(cypher, index) or not _is_word_boundary(cypher, index, left=True):
            index += 1
            continue
        matched = _match_clause_at(upper, cypher, index)
        if matched is None:
            index += 1
            continue
        starts.append((index, matched))
        index += len(matched)
    return starts


def _find_unsupported_read_fragment(cypher: str) -> tuple[str, int] | None:
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
                return phrase, index
        index += 1
    return None


def _match_clause_at(upper: str, original: str, index: int) -> str | None:
    for phrase in CLAUSE_PHRASES:
        pattern = r"\s+".join(re.escape(part) for part in phrase.split())
        match = re.match(pattern, upper[index:])
        if match is None:
            continue
        end = index + match.end()
        if end <= len(original) and _is_word_boundary(original, end, left=False):
            return phrase
    return None


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
