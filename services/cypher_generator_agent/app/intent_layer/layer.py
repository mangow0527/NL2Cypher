from __future__ import annotations

from dataclasses import dataclass
import inspect
from typing import Any

import yaml

from services.cypher_generator_agent.app.infrastructure import resource_paths
from services.cypher_generator_agent.app.intent_layer.models import Intent, IntentOutput, InitialShapeField

from .recognition import IntentRecognitionResult, get_hybrid_intent_recognizer


@dataclass(frozen=True)
class _LayeredLLMSelection:
    recognition: IntentRecognitionResult | None
    selections: tuple[object, ...]


class IntentLayer:
    def __init__(self, *, recognizer: object | None = None, llm_selector: object | None = None) -> None:
        self.recognizer = recognizer or get_hybrid_intent_recognizer()
        self.llm_selector = llm_selector
        self.taxonomy = yaml.safe_load(resource_paths.intent_taxonomy_path().read_text(encoding="utf-8")) or {}
        self.taxonomy_version = int(self.taxonomy.get("version", 0))

    def run(
        self,
        *,
        core_question: str | None = None,
        shape_signals: tuple[Any, ...] = (),
    ) -> IntentOutput:
        if core_question is None:
            raise ValueError("core_question is required")

        recognition = _recognize(self.recognizer, core_question, shape_signals)
        llm_selection = None
        llm_stage_selections: tuple[object, ...] = ()
        if getattr(recognition, "decision", None) == "fallback_llm" and self.llm_selector is not None:
            layered_selection = self._select_with_llm(core_question, shape_signals)
            llm_stage_selections = layered_selection.selections
            llm_selection = llm_stage_selections[-1] if llm_stage_selections else None
            if layered_selection.recognition is not None:
                recognition = layered_selection.recognition

        intent_candidates = tuple(self._intent_candidates(recognition))
        if recognition.primary_intent is None or recognition.secondary_intent is None:
            intent = Intent(
                primary="unknown",
                secondary="unknown",
                source=recognition.source,
                decision=recognition.decision,
                confidence=recognition.confidence,
                clarify_origin=getattr(recognition, "clarify_origin", None) or "intent_recognition",
                clarify_reason=getattr(recognition, "clarify_reason", None) or "intent_not_identified",
                failed_fields=_failed_intent_fields(recognition),
                candidate_intents=getattr(recognition, "candidate_intents", ()) or intent_candidates,
                evidence=getattr(recognition, "evidence", None),
            )
            initial_shape: dict[str, InitialShapeField] = {}
            planning_prompt_text = ""
        else:
            intent = Intent(
                primary=recognition.primary_intent,
                secondary=recognition.secondary_intent,
                source=recognition.source,
                decision=recognition.decision,
                confidence=recognition.confidence,
            )
            initial_shape = self._initial_shape(intent, shape_signals)
            _, secondary_entry = self._intent_entries(recognition.primary_intent, recognition.secondary_intent)
            planning_prompt_text = str(secondary_entry["planning_prompt_text"]).strip()

        diagnostics: dict[str, Any] = {
            "taxonomy_version": self.taxonomy_version,
            "recognizer_source": recognition.source,
            "recognizer_decision": recognition.decision,
            "recognizer_primary": recognition.primary_intent,
            "recognizer_secondary": recognition.secondary_intent,
            "recognizer_confidence": recognition.confidence,
        }
        if recognition.primary_intent is not None and recognition.secondary_intent is not None:
            diagnostics["planning_prompt_text"] = planning_prompt_text
        if llm_selection is not None:
            diagnostics.update(
                {
                    "llm_prompt_name": llm_selection.prompt_name,
                    "llm_prompt_version": llm_selection.prompt_version,
                    "llm_prompt_hash": llm_selection.prompt_hash,
                    "llm_rendered_prompt_hash": llm_selection.rendered_prompt_hash,
                    "llm_rendered_prompt": getattr(llm_selection, "rendered_prompt", ""),
                    "llm_raw_response": llm_selection.raw_response,
                    "llm_stage_count": len(llm_stage_selections),
                    "llm_stages": [
                        {
                            "prompt_name": selection.prompt_name,
                            "decision": selection.parsed.get("decision"),
                            "candidate_id": selection.parsed.get("candidate_id"),
                            "rendered_prompt_hash": selection.rendered_prompt_hash,
                            "rendered_prompt": getattr(selection, "rendered_prompt", ""),
                            "raw_response": getattr(selection, "raw_response", ""),
                        }
                        for selection in llm_stage_selections
                    ],
                }
            )

        return IntentOutput(
            intent=intent,
            planning_prompt_text=planning_prompt_text,
            initial_shape=initial_shape,
            candidates=intent_candidates,
            rule_signals_used=_signal_texts(shape_signals),
            diagnostics=diagnostics,
        )

    def _initial_shape(
        self,
        intent: Intent,
        shape_signals: tuple[Any, ...],
    ) -> dict[str, InitialShapeField]:
        primary_entry, secondary_entry = self._intent_entries(intent.primary, intent.secondary)
        profile = {
            **dict(primary_entry.get("shape_profile") or {}),
            **dict(secondary_entry.get("shape_profile") or {}),
        }
        answer_type = secondary_entry.get("default_answer_type") or primary_entry.get("default_answer_type") or "record_table"
        signal_tags = _signal_tags(shape_signals)
        signal_overrides = _shape_signal_overrides(signal_tags)
        aggregation_functions = tuple(
            profile.get("aggregation_functions") or _aggregation_functions_from_signals(intent, shape_signals)
        )
        shape: dict[str, InitialShapeField] = {
            "answer_type": InitialShapeField(
                value=answer_type,
                source="taxonomy.secondary.default_answer_type"
                if secondary_entry.get("default_answer_type")
                else "taxonomy.primary.default_answer_type",
                decision="accept",
                confidence=1.0,
            ),
            "aggregation_functions": InitialShapeField(
                value=aggregation_functions,
                source="shape_signal" if _aggregation_functions_from_signals(intent, shape_signals) else "taxonomy.shape_profile",
                decision="accept",
                confidence=1.0,
                derived_from=_signal_ids_for_tags(shape_signals, {"aggregation_hint", "count_hint"}),
            ),
        }
        for field in (
            "projection_expected",
            "aggregation_required",
            "group_by_required",
            "order_required",
            "limit_required",
            "time_grain_required",
            "path_answer_required",
            "existence_answer_required",
            "relation_resolution_expected",
        ):
            signal_value = signal_overrides.get(field, False)
            value = bool(profile.get(field, False) or signal_value)
            shape[field] = InitialShapeField(
                value=value,
                source="shape_signal"
                if signal_value and not profile.get(field, False)
                else (
                    "taxonomy.secondary.shape_profile"
                    if field in secondary_entry.get("shape_profile", {})
                    else "taxonomy.primary.shape_profile"
                ),
                decision="pending" if field == "relation_resolution_expected" and value else "accept",
                confidence=0.8 if field == "relation_resolution_expected" and value else 1.0,
                derived_from=_signal_ids_for_shape_field(shape_signals, field) if signal_value else (),
                pending_until="step_3_3" if field == "relation_resolution_expected" and value else None,
            )
        quantifier_effects = _quantifier_effects(shape_signals)
        if quantifier_effects:
            shape["quantifier_effects"] = InitialShapeField(
                value=quantifier_effects,
                source="shape_signal.quantifier",
                decision="accept",
                confidence=1.0,
                derived_from=tuple(item["mention_id"] for item in quantifier_effects),
            )
        if any(item.get("semantic") == "no_implicit_filter" for item in quantifier_effects):
            shape["filter_level_hint"] = InitialShapeField(
                value="explicit_only_no_implicit",
                source="shape_signal.quantifier",
                decision="accept",
                confidence=1.0,
                derived_from=tuple(
                    item["mention_id"] for item in quantifier_effects if item.get("semantic") == "no_implicit_filter"
                ),
            )
        return shape

    def _intent_entries(self, primary_intent: str, secondary_intent: str) -> tuple[dict[str, Any], dict[str, Any]]:
        for primary_entry in self.taxonomy.get("intents", []):
            if primary_entry.get("primary_intent") != primary_intent:
                continue
            for secondary_entry in primary_entry.get("secondary_intents", []):
                if secondary_entry.get("secondary_intent") == secondary_intent:
                    return primary_entry, secondary_entry
            return primary_entry, {}
        return {}, {}

    def _intent_candidates(self, recognition: object) -> tuple[dict[str, object], ...]:
        candidates: list[dict[str, object]] = []
        for primary_entry in self.taxonomy.get("intents", []):
            primary_id = str(primary_entry.get("primary_intent"))
            for secondary_entry in primary_entry.get("secondary_intents", []):
                candidates.append(
                    {
                        "id": f"C{len(candidates) + 1}",
                        "primary": primary_id,
                        "secondary": str(secondary_entry.get("secondary_intent")),
                        "label": str(secondary_entry.get("name_zh") or secondary_entry.get("secondary_intent")),
                    }
                )
        if getattr(recognition, "primary_intent", None) and getattr(recognition, "secondary_intent", None):
            selected = [
                item
                for item in candidates
                if item["primary"] == recognition.primary_intent and item["secondary"] == recognition.secondary_intent
            ]
            return tuple(selected or candidates[:4])
        return tuple(candidates[:4])

    def _select_with_llm(
        self,
        core_question: str,
        shape_signals: tuple[Any, ...],
    ) -> _LayeredLLMSelection:
        if self.llm_selector is None:
            raise RuntimeError("llm_selector is required for intent fallback")
        selections: list[object] = []

        primary_candidates = self._primary_candidates()
        primary_selection = self._select_intent_candidate(core_question, shape_signals, primary_candidates)
        selections.append(primary_selection)
        selected_primary = _accepted_candidate(primary_candidates, primary_selection)
        if selected_primary is None:
            return _LayeredLLMSelection(recognition=None, selections=tuple(selections))

        secondary_candidates = self._secondary_candidates(str(selected_primary["primary"]))
        secondary_selection = self._select_intent_candidate(core_question, shape_signals, secondary_candidates)
        selections.append(secondary_selection)
        selected_secondary = _accepted_candidate(secondary_candidates, secondary_selection)
        if selected_secondary is None:
            return _LayeredLLMSelection(recognition=None, selections=tuple(selections))

        return _LayeredLLMSelection(
            recognition=IntentRecognitionResult(
                primary_intent=str(selected_secondary["primary"]),
                secondary_intent=str(selected_secondary["secondary"]),
                confidence=0.8,
                source="llm",
                decision="accept",
            ),
            selections=tuple(selections),
        )

    def _select_intent_candidate(
        self,
        core_question: str,
        shape_signals: tuple[Any, ...],
        candidates: tuple[dict[str, object], ...],
    ) -> object:
        return self.llm_selector.select(
            "intent_selection",
            {
                "question": core_question,
                "intent_candidate_list_with_ids": _candidate_list_with_ids(candidates),
                "signal_list_with_ids": _signal_list_with_ids(shape_signals, candidates),
                "allowed_candidate_ids": [str(candidate["id"]) for candidate in candidates],
                "allowed_signal_ids": [signal.signal_id for signal in shape_signals] or ["S1"],
            },
        )

    def _primary_candidates(self) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "id": f"C{index}",
                "primary": str(primary_entry.get("primary_intent")),
                "secondary": None,
                "label": str(primary_entry.get("name_zh") or primary_entry.get("primary_intent")),
            }
            for index, primary_entry in enumerate(self.taxonomy.get("intents", []), start=1)
        )

    def _secondary_candidates(self, primary_intent: str) -> tuple[dict[str, object], ...]:
        primary_entry, _ = self._intent_entries(primary_intent, "")
        return tuple(
            {
                "id": f"C{index}",
                "primary": primary_intent,
                "secondary": str(secondary_entry.get("secondary_intent")),
                "label": str(secondary_entry.get("name_zh") or secondary_entry.get("secondary_intent")),
            }
            for index, secondary_entry in enumerate(primary_entry.get("secondary_intents", []), start=1)
        )


def _aggregation_functions_from_signals(
    intent: Intent,
    shape_signals: tuple[Any, ...],
) -> tuple[str, ...]:
    tags = _signal_tags(shape_signals)
    if intent.secondary == "count_metric_query" or "count_hint" in tags:
        return ("count",)
    return ()


def _recognize(recognizer: object, core_question: str, shape_signals: tuple[Any, ...]) -> object:
    recognize = getattr(recognizer, "recognize")
    if _accepts_shape_signals(recognize):
        return recognize(core_question, shape_signals=shape_signals)
    return recognize(core_question)


def _accepts_shape_signals(callable_obj: object) -> bool:
    try:
        signature = inspect.signature(callable_obj)
    except (TypeError, ValueError):
        return True
    return any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD or name == "shape_signals"
        for name, parameter in signature.parameters.items()
    )


def _failed_intent_fields(recognition: object) -> tuple[str, ...]:
    explicit_fields = getattr(recognition, "failed_fields", ())
    if explicit_fields:
        return tuple(str(field) for field in explicit_fields)
    fields: list[str] = []
    if getattr(recognition, "primary_intent", None) is None:
        fields.append("primary_intent")
    if getattr(recognition, "secondary_intent", None) is None:
        fields.append("secondary_intent")
    return tuple(fields)


def _signal_tags(shape_signals: tuple[Any, ...]) -> set[str]:
    return {tag for signal in shape_signals for tag in signal.supports}


def _quantifier_effects(shape_signals: tuple[Any, ...]) -> list[dict[str, Any]]:
    effects: list[dict[str, Any]] = []
    for signal in shape_signals:
        supports = tuple(str(value) for value in getattr(signal, "supports", ()) or ())
        if "quantifier" not in supports:
            continue
        canonical_id = next((value for value in supports if value.startswith("QUANT_")), "")
        semantic = _quantifier_semantic(supports)
        if not canonical_id:
            continue
        effects.append(
            {
                "mention_id": str(getattr(signal, "signal_id", "")),
                "canonical_id": canonical_id,
                "semantic": semantic,
                "affects_intent": "affects_intent" in supports,
            }
        )
    return effects


def _quantifier_semantic(supports: tuple[str, ...]) -> str:
    for value in ("no_implicit_filter", "not_exists", "existential_scope"):
        if value in supports:
            return value
    return ""


def _shape_signal_overrides(signal_tags: set[str]) -> dict[str, bool]:
    return {
        "projection_expected": bool(signal_tags.intersection({"answer_projection_region", "project_marker"})),
        "aggregation_required": bool(signal_tags.intersection({"aggregation_hint", "count_hint"})),
        "group_by_required": "group_by_hint" in signal_tags,
        "order_required": bool(signal_tags.intersection({"ranking_hint", "order_hint"})),
        "limit_required": "limit_hint" in signal_tags,
        "time_grain_required": "time_grain_hint" in signal_tags,
        "path_answer_required": bool(
            signal_tags.intersection({"path_answer_hint", "path_enumeration_hint", "topology_answer_hint"})
        ),
        "existence_answer_required": "existence_hint" in signal_tags,
    }


def _signal_ids_for_shape_field(shape_signals: tuple[Any, ...], field: str) -> tuple[str, ...]:
    field_tags = {
        "projection_expected": {"answer_projection_region", "project_marker"},
        "aggregation_required": {"aggregation_hint", "count_hint"},
        "group_by_required": {"group_by_hint"},
        "order_required": {"ranking_hint", "order_hint"},
        "limit_required": {"limit_hint"},
        "time_grain_required": {"time_grain_hint"},
        "path_answer_required": {"path_answer_hint", "path_enumeration_hint", "topology_answer_hint"},
        "existence_answer_required": {"existence_hint"},
    }.get(field, set())
    return _signal_ids_for_tags(shape_signals, field_tags)


def _signal_ids_for_tags(shape_signals: tuple[Any, ...], tags: set[str]) -> tuple[str, ...]:
    if not tags:
        return ()
    return tuple(signal.signal_id for signal in shape_signals if tags.intersection(signal.supports))


def _signal_texts(shape_signals: tuple[Any, ...]) -> tuple[str, ...]:
    return tuple(signal.text for signal in shape_signals)


def _accepted_candidate(candidates: tuple[dict[str, object], ...], selection: object) -> dict[str, object] | None:
    parsed = getattr(selection, "parsed", {})
    if not isinstance(parsed, dict) or parsed.get("decision") != "accept":
        return None
    return _candidate_by_id(candidates, str(parsed.get("candidate_id")))


def _candidate_list_with_ids(candidates: tuple[dict[str, object], ...]) -> str:
    return "\n".join(
        f"{candidate['id']}: {_candidate_intent_label(candidate)} - {candidate['label']}" for candidate in candidates
    )


def _candidate_intent_label(candidate: dict[str, object]) -> str:
    secondary = candidate.get("secondary")
    if secondary is None:
        return str(candidate["primary"])
    return f"{candidate['primary']}.{secondary}"


def _signal_list_with_ids(
    shape_signals: tuple[Any, ...],
    candidates: tuple[dict[str, object], ...],
) -> str:
    candidate_ids = tuple(str(candidate["id"]) for candidate in candidates)
    if not shape_signals:
        return f"S1: 无明确答案形态信号 supports={','.join(candidate_ids)}"
    return "\n".join(
        f"{signal.signal_id}: {signal.text} supports={','.join(_candidate_ids_supported_by_signal(signal, candidates))}"
        for signal in shape_signals
    )


def _candidate_ids_supported_by_signal(
    signal: Any,
    candidates: tuple[dict[str, object], ...],
) -> tuple[str, ...]:
    tags = set(signal.supports)
    supported = [
        str(candidate["id"])
        for candidate in candidates
        if _signal_supports_candidate(tags, str(candidate["primary"]), candidate.get("secondary"))
    ]
    if supported:
        return tuple(supported)
    return tuple(str(candidate["id"]) for candidate in candidates)


def _signal_supports_candidate(tags: set[str], primary: str, secondary: object) -> bool:
    secondary_id = str(secondary) if secondary is not None else None
    if tags.intersection({"answer_projection_region", "project_marker"}):
        return primary in {"record_retrieval_query", "comparison_query", "set_operation_query"} or secondary_id in {
            "attribute_ranking_query",
        }
    if tags.intersection({"path_answer_hint", "path_enumeration_hint", "topology_answer_hint"}):
        return primary == "relationship_path_query" or secondary_id == "path_existence_query"
    if tags.intersection({"aggregation_hint", "count_hint"}):
        return primary in {"metric_query", "breakdown_query", "composition_query", "ranking_query"}
    if "group_by_hint" in tags:
        return primary == "breakdown_query" or secondary_id == "share_breakdown_query"
    if tags.intersection({"ranking_hint", "order_hint", "limit_hint"}):
        return primary == "ranking_query"
    if "time_grain_hint" in tags:
        return primary == "trend_query" or secondary_id == "period_comparison_query"
    if "existence_hint" in tags:
        return primary == "existence_query"
    return True


def _candidate_by_id(candidates: tuple[dict[str, object], ...], candidate_id: str) -> dict[str, object] | None:
    return next((candidate for candidate in candidates if candidate["id"] == candidate_id), None)
