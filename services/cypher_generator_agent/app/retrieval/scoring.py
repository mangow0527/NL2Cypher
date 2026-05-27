from __future__ import annotations

import re
from dataclasses import dataclass

from .index import IndexedText, SemanticSearchDocument
from .models import CandidateEvidence, MatchType


EXACT_SCORE = 1.0
SYNONYM_SCORE = 0.92
TEXT_CONTAINS_SCORE = 0.72
TEXT_TOKEN_SCORE = 0.64


@dataclass(frozen=True)
class ScoredMatch:
    score: float
    match_type: MatchType
    evidence: CandidateEvidence


class DeterministicCandidateScorer:
    def best_match(self, document: SemanticSearchDocument, terms: list[str]) -> ScoredMatch | None:
        matches: list[ScoredMatch] = []
        for term in terms:
            if not term.strip():
                continue
            exact_match = _best_exact_match(term, document.exact_names)
            if exact_match:
                matches.append(exact_match)
                continue

            synonym_match = _best_synonym_match(term, document.synonyms)
            if synonym_match:
                matches.append(synonym_match)
                continue

            text_match = _best_text_match(term, document.text_fields)
            if text_match:
                matches.append(text_match)

        if not matches:
            return None
        return max(matches, key=lambda match: _match_sort_key(match))


def _best_exact_match(term: str, exact_names: tuple[IndexedText, ...]) -> ScoredMatch | None:
    normalized_term = _normalize(term)
    for exact_name in exact_names:
        if normalized_term == _normalize(exact_name.text):
            return ScoredMatch(
                score=EXACT_SCORE,
                match_type="exact",
                evidence=CandidateEvidence(term=term, source=exact_name.field, matched_text=exact_name.text),
            )
    return None


def _best_synonym_match(term: str, synonyms: tuple[IndexedText, ...]) -> ScoredMatch | None:
    normalized_term = _normalize(term)
    for synonym in synonyms:
        if normalized_term == _normalize(synonym.text):
            return ScoredMatch(
                score=SYNONYM_SCORE,
                match_type="synonym",
                evidence=CandidateEvidence(term=term, source=synonym.field, matched_text=synonym.text),
            )
    return None


def _best_text_match(term: str, texts: tuple[IndexedText, ...]) -> ScoredMatch | None:
    matches: list[ScoredMatch] = []
    for text in texts:
        score = _text_score(term, text.text)
        if score is None:
            continue
        matches.append(
            ScoredMatch(
                score=score,
                match_type="text",
                evidence=CandidateEvidence(term=term, source=text.field, matched_text=text.text),
            )
        )
    if not matches:
        return None
    return max(matches, key=lambda match: _match_sort_key(match))


def _text_score(term: str, text: str) -> float | None:
    normalized_term = _normalize(term)
    normalized_text = _normalize(text)
    if len(normalized_term) >= 2 and normalized_term in normalized_text:
        return TEXT_CONTAINS_SCORE

    term_tokens = set(_tokens(normalized_term))
    if not term_tokens:
        return None
    text_tokens = set(_tokens(normalized_text))
    if term_tokens <= text_tokens:
        return TEXT_TOKEN_SCORE
    return None


def _match_sort_key(match: ScoredMatch) -> tuple[float, int]:
    priority = {"exact": 3, "synonym": 2, "text": 1, "embedding": 0}[match.match_type]
    return (match.score, priority)


def _normalize(text: str) -> str:
    lowered = text.casefold()
    normalized = re.sub(r"[_\-./:]+", " ", lowered)
    return re.sub(r"\s+", " ", normalized).strip()


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", text)
