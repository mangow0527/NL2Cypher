from __future__ import annotations

import re

from .models import PreflightCheck


_WRITE_OPERATION_PATTERN = re.compile(
    r"(^|\s)(CREATE|MERGE|SET|DELETE|DETACH\s+DELETE|REMOVE|DROP|LOAD\s+CSV)\b",
    re.IGNORECASE,
)
_CALL_PATTERN = re.compile(r"(^|\s)CALL\b", re.IGNORECASE)
_READ_START_PATTERN = re.compile(r"^(MATCH|WITH)\b", re.IGNORECASE)


def run_preflight_check(cypher: str) -> PreflightCheck:
    query = cypher.strip()
    if not query:
        return PreflightCheck(accepted=False, reason="empty_output")
    if _has_multiple_statements(query):
        return PreflightCheck(accepted=False, reason="multiple_statements")
    if _has_unclosed_string(query):
        return PreflightCheck(accepted=False, reason="unclosed_string")
    if _has_unbalanced_brackets(query):
        return PreflightCheck(accepted=False, reason="unbalanced_brackets")
    if _WRITE_OPERATION_PATTERN.search(_mask_string_literals(query)):
        return PreflightCheck(accepted=False, reason="write_operation")

    masked_query = _mask_string_literals(query)
    if _CALL_PATTERN.search(masked_query):
        return PreflightCheck(accepted=False, reason="unsupported_call")
    if not _READ_START_PATTERN.match(query.lstrip()):
        return PreflightCheck(accepted=False, reason="unsupported_start_clause")
    return PreflightCheck(accepted=True)


def _has_multiple_statements(query: str) -> bool:
    parts = [part.strip() for part in _split_semicolon_outside_strings(query)]
    return len([part for part in parts if part]) > 1


def _split_semicolon_outside_strings(query: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    for char in query:
        if quote:
            current.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            current.append(char)
        elif char == ";":
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def _has_unclosed_string(query: str) -> bool:
    quote: str | None = None
    escaped = False
    for char in query:
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in {"'", '"'}:
            quote = char
    return quote is not None


def _has_unbalanced_brackets(query: str) -> bool:
    pairs = {")": "(", "]": "[", "}": "{"}
    openers = set(pairs.values())
    stack: list[str] = []
    quote: str | None = None
    escaped = False
    for char in query:
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
        elif char in openers:
            stack.append(char)
        elif char in pairs:
            if not stack or stack.pop() != pairs[char]:
                return True
    return bool(stack)


def _mask_string_literals(query: str) -> str:
    masked: list[str] = []
    quote: str | None = None
    escaped = False
    for char in query:
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
                masked.append(char)
                continue
            masked.append(" ")
        elif char in {"'", '"'}:
            quote = char
            masked.append(char)
        else:
            masked.append(char)
    return "".join(masked)
