from __future__ import annotations

from dataclasses import dataclass

from .background_strip import strip_background
from .clarity_gate import judge_clarity
from .compound_detection import detect_compound_query
from .noise_handling import handle_noise
from .phrase_detection import detect_phrase_signals
from .self_correction import apply_self_correction
from .text_cleaning import clean_text


@dataclass(frozen=True)
class QuestionPreprocessingResult:
    accepted: bool
    original_question: str
    cleaned_question: str
    question_after_correction: str | None
    core_candidate: str | None
    core_question: str | None
    retrieval_question: str | None
    clarification: dict[str, object] | None
    diagnostics: dict[str, object | None]

    def to_dict(self) -> dict[str, object | None]:
        return {
            "accepted": self.accepted,
            "original_question": self.original_question,
            "cleaned_question": self.cleaned_question,
            "question_after_correction": self.question_after_correction,
            "core_candidate": self.core_candidate,
            "core_question": self.core_question,
            "retrieval_question": self.retrieval_question,
            "clarification": self.clarification,
            "diagnostics": self.diagnostics,
        }


def preprocess_question(original_question: str) -> QuestionPreprocessingResult:
    """独立预处理编排器：只串联 7 个预处理步骤，不调用 Cypher 生成链路。"""

    text_cleaning = clean_text(original_question)
    phrase_detection = detect_phrase_signals(text_cleaning)
    self_correction = apply_self_correction(
        phrase_detection.cleaned_question,
        phrase_detection.phrase_spans,
        phrase_detection.scope_signals,
    )
    diagnostics: dict[str, object | None] = {
        "text_cleaning": text_cleaning.to_dict(),
        "phrase_detection": phrase_detection.to_dict(),
        "self_correction": self_correction.to_dict(),
        "background_strip": None,
        "compound_detection": None,
        "noise_handling": None,
        "clarity_gate": None,
    }

    if self_correction.status == "clarification_required":
        return QuestionPreprocessingResult(
            accepted=False,
            original_question=original_question,
            cleaned_question=text_cleaning.cleaned_question,
            question_after_correction=None,
            core_candidate=None,
            core_question=None,
            retrieval_question=None,
            clarification=self_correction.clarification,
            diagnostics=diagnostics,
        )

    question_after_correction = self_correction.question_after_correction or text_cleaning.cleaned_question
    background_strip = strip_background(question_after_correction)
    diagnostics["background_strip"] = background_strip.to_dict()

    compound_detection = detect_compound_query(background_strip.core_candidate)
    diagnostics["compound_detection"] = compound_detection.to_dict()
    if not compound_detection.can_continue:
        return QuestionPreprocessingResult(
            accepted=False,
            original_question=original_question,
            cleaned_question=text_cleaning.cleaned_question,
            question_after_correction=question_after_correction,
            core_candidate=background_strip.core_candidate,
            core_question=None,
            retrieval_question=None,
            clarification=compound_detection.clarification,
            diagnostics=diagnostics,
        )

    noise_handling = handle_noise(background_strip.core_candidate)
    diagnostics["noise_handling"] = noise_handling.to_dict()

    clarity_gate = judge_clarity(
        noise_handling.core_question,
        noise_handling.retrieval_question,
        diagnostics,
    )
    diagnostics["clarity_gate"] = clarity_gate.to_dict()

    return QuestionPreprocessingResult(
        accepted=clarity_gate.accepted,
        original_question=original_question,
        cleaned_question=text_cleaning.cleaned_question,
        question_after_correction=question_after_correction,
        core_candidate=background_strip.core_candidate if clarity_gate.accepted else None,
        core_question=noise_handling.core_question if clarity_gate.accepted else None,
        retrieval_question=noise_handling.retrieval_question if clarity_gate.accepted else None,
        clarification=clarity_gate.clarification,
        diagnostics=diagnostics,
    )
