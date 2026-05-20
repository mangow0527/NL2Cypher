from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml

from services.cypher_generator_agent.app import resource_paths


class RawHit(Protocol):
    hit_id: str
    canonical_id: str
    mention_type: str
    surface: str
    span_start: int
    span_end: int
    match_source: str

    @property
    def length(self) -> int: ...

    def to_dict(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class DictionaryPriorities:
    by_type: dict[str, int]
    by_canonical_id: dict[str, int]
    match_source_priorities: dict[str, int]
    max_overrides: int
    override_semantics: str

    @classmethod
    def from_default_resources(cls) -> "DictionaryPriorities":
        return cls.from_path(resource_paths.lexer_dictionary_priorities_path())

    @classmethod
    def from_path(cls, path: Path) -> "DictionaryPriorities":
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        dictionary = payload.get("dictionary_priorities", {}) or {}
        ci_rule = dictionary.get("ci_rules", dictionary.get("ci_rule", {})) or {}
        return cls(
            by_type={str(key): int(value) for key, value in (dictionary.get("by_type", {}) or {}).items()},
            by_canonical_id={
                str(key): int(value) for key, value in (dictionary.get("by_canonical_id", {}) or {}).items()
            },
            match_source_priorities={
                str(key): int(value) for key, value in (payload.get("match_source_priorities", {}) or {}).items()
            },
            max_overrides=int(ci_rule.get("max_overrides", 0)),
            override_semantics=str(payload.get("override_semantics", "replace")),
        )

    def source_priority(self, hit: RawHit) -> int:
        return self.match_source_priorities.get(hit.match_source, 0)

    def dictionary_priority(self, hit: RawHit) -> int:
        return self.by_canonical_id.get(hit.canonical_id, self.by_type.get(hit.mention_type, 0))


@dataclass(frozen=True)
class DiscardedHit:
    hit: dict[str, Any]
    discarded_reason: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"hit": dict(self.hit), "discarded_reason": dict(self.discarded_reason)}


@dataclass(frozen=True)
class OverlapResolution:
    selected: tuple[RawHit, ...]
    discarded: tuple[DiscardedHit, ...]
    total_conflict_clusters: int

    def selected_to_dicts(self) -> tuple[dict[str, Any], ...]:
        return tuple(hit.to_dict() for hit in self.selected)

    def discarded_to_dicts(self) -> tuple[dict[str, Any], ...]:
        return tuple(item.to_dict() for item in self.discarded)

    def summary(self, total_raw_hits: int) -> dict[str, int]:
        return {
            "total_raw_hits": total_raw_hits,
            "total_conflict_clusters": self.total_conflict_clusters,
            "total_selected": len(self.selected),
            "total_discarded": len(self.discarded),
        }


class OverlapResolver:
    def __init__(self, priorities: DictionaryPriorities) -> None:
        self.priorities = priorities

    def resolve(self, raw_hits: tuple[RawHit, ...]) -> OverlapResolution:
        clusters = _build_conflict_clusters(raw_hits)
        selected: list[RawHit] = []
        discarded: list[DiscardedHit] = []
        for cluster in clusters:
            cluster_selected: list[RawHit] = []
            for hit in self._ranked_hits(cluster):
                winner = _first_overlapping(hit, cluster_selected)
                if winner is None:
                    cluster_selected.append(hit)
                    selected.append(hit)
                    continue
                discarded.append(
                    DiscardedHit(
                        hit=hit.to_dict(),
                        discarded_reason=self._discard_reason(loser=hit, winner=winner),
                    )
                )
        return OverlapResolution(
            selected=tuple(sorted(selected, key=lambda item: (item.span_start, item.span_end, item.canonical_id))),
            discarded=tuple(discarded),
            total_conflict_clusters=sum(1 for cluster in clusters if len(cluster) > 1),
        )

    def _select_winner(self, cluster: list[RawHit]) -> RawHit:
        return self._ranked_hits(cluster)[0]

    def _ranked_hits(self, cluster: list[RawHit]) -> list[RawHit]:
        return sorted(
            cluster,
            key=lambda hit: (
                -self.priorities.source_priority(hit),
                -self.priorities.dictionary_priority(hit),
                -hit.length,
                hit.canonical_id,
                hit.span_start,
                hit.span_end,
                hit.surface,
                hit.hit_id,
            ),
        )

    def _discard_reason(self, *, loser: RawHit, winner: RawHit) -> dict[str, Any]:
        if _is_duplicate(loser, winner):
            code = "DUPLICATE_OF_RETAINED_HIT"
            message = f"与保留命中 {winner.hit_id} 完全重复"
        elif self.priorities.source_priority(loser) < self.priorities.source_priority(winner):
            code = "WEAKER_MATCH_SOURCE_THAN_OVERLAPPING_HIT"
            message = f"被更强来源的命中 {winner.hit_id} 覆盖"
        elif self.priorities.dictionary_priority(loser) < self.priorities.dictionary_priority(winner):
            code = "LOWER_PRIORITY_THAN_OVERLAPPING_HIT"
            message = f"被更高词典优先级的命中 {winner.hit_id} 覆盖"
        elif loser.length < winner.length:
            code = "SHORTER_THAN_OVERLAPPING_HIT"
            message = f"被更长的命中 {winner.hit_id} 覆盖"
        else:
            code = "STABLE_TIE_BREAKER_LOST"
            message = f"稳定排序后被命中 {winner.hit_id} 覆盖"
        return {"code": code, "message": message, "winning_hit_id": winner.hit_id}


def _build_conflict_clusters(raw_hits: tuple[RawHit, ...]) -> list[list[RawHit]]:
    if not raw_hits:
        return []
    ordered = sorted(raw_hits, key=lambda item: (item.span_start, item.span_end, item.canonical_id, item.hit_id))
    clusters: list[list[RawHit]] = []
    current: list[RawHit] = []
    current_end = -1
    for hit in ordered:
        if not current or hit.span_start >= current_end:
            if current:
                clusters.append(current)
            current = [hit]
            current_end = hit.span_end
            continue
        current.append(hit)
        current_end = max(current_end, hit.span_end)
    if current:
        clusters.append(current)
    return clusters


def _is_duplicate(left: RawHit, right: RawHit) -> bool:
    return (
        left.span_start == right.span_start
        and left.span_end == right.span_end
        and left.canonical_id == right.canonical_id
        and left.surface == right.surface
        and left.match_source == right.match_source
    )


def _first_overlapping(hit: RawHit, selected: list[RawHit]) -> RawHit | None:
    for winner in selected:
        if hit.span_start < winner.span_end and winner.span_start < hit.span_end:
            return winner
    return None
