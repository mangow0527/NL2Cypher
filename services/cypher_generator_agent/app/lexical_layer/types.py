from __future__ import annotations


CANONICAL_MENTION_TYPES = frozenset(
    {
        "OPERATION",
        "VALUE",
        "OBJECT",
        "RELATION",
        "ATTRIBUTE",
        "LITERAL_VALUE",
        "COMPARISON_OPERATOR",
        "QUANTIFIER",
        "TIME_EXPRESSION",
    }
)

STRUCTURED_MENTION_TYPES = frozenset(
    {
        "LITERAL_VALUE",
        "COMPARISON_OPERATOR",
        "QUANTIFIER",
        "TIME_EXPRESSION",
    }
)

NON_EMITTED_ENTRY_TYPES = frozenset({"SYNONYM", "SYNONYM_GROUP"})


def normalize_mention_type(mention_type: str) -> str:
    raw = str(mention_type or "").strip()
    if raw in CANONICAL_MENTION_TYPES or raw in NON_EMITTED_ENTRY_TYPES:
        return raw
    raise ValueError(f"unsupported mention_type: {mention_type!r}")


def normalize_expected_mention_type(mention_type: str | None) -> str | None:
    if not mention_type:
        return None
    raw = str(mention_type).strip()
    if raw in CANONICAL_MENTION_TYPES:
        return raw
    raise ValueError(f"unsupported expected mention_type: {mention_type!r}")


def is_emitted_mention_type(mention_type: str) -> bool:
    return normalize_mention_type(mention_type) in CANONICAL_MENTION_TYPES
