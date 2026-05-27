from __future__ import annotations

import re

from .models import CypherValidationIssue, validation_error
from .parser import ParsedCypher


DIALECT_FAILURE_CODE = "target_dialect_static_error"
MAX_VARIABLE_PATH_HOPS = 8
REL_PATTERN_RE = re.compile(r"\[(?P<body>[^\[\]]*)\]")
VARIABLE_LENGTH_RE = re.compile(r"\*(?P<range>\d*(?:\.\.\d*)?)?")


def validate_target_dialect(parsed: ParsedCypher) -> list[CypherValidationIssue]:
    errors: list[CypherValidationIssue] = []
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


def _max_hops(range_text: str) -> int | None:
    if not range_text:
        return None
    if ".." not in range_text:
        return int(range_text) if range_text else None
    _, upper = range_text.split("..", 1)
    return int(upper) if upper else None
