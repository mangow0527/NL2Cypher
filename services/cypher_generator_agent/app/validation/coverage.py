from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CoverageBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SubstantiveTermsCoverage(CoverageBase):
    total: int = 0
    covered: int = 0
    uncovered: list[str] = Field(default_factory=list)


class StopwordTermsCoverage(CoverageBase):
    ignored: list[str] = Field(default_factory=list)


class ModalityTermsCoverage(CoverageBase):
    warning_only: list[str] = Field(default_factory=list)


class TimeTermsCoverage(CoverageBase):
    covered: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)


class UnparsedTermsCoverage(CoverageBase):
    unresolved: list[str] = Field(default_factory=list)


class SlotCoverage(CoverageBase):
    required: list[str] = Field(default_factory=list)
    covered: list[str] = Field(default_factory=list)
    uncovered: list[str] = Field(default_factory=list)


class SlotTermsCoverage(CoverageBase):
    projection: SlotCoverage = Field(default_factory=SlotCoverage)
    filter: SlotCoverage = Field(default_factory=SlotCoverage)
    group_by: SlotCoverage = Field(default_factory=SlotCoverage)
    order_by: SlotCoverage = Field(default_factory=SlotCoverage)


class CoverageReport(CoverageBase):
    substantive_terms: SubstantiveTermsCoverage = Field(default_factory=SubstantiveTermsCoverage)
    stopword_terms: StopwordTermsCoverage = Field(default_factory=StopwordTermsCoverage)
    modality_terms: ModalityTermsCoverage = Field(default_factory=ModalityTermsCoverage)
    time_terms: TimeTermsCoverage = Field(default_factory=TimeTermsCoverage)
    unparsed_terms: UnparsedTermsCoverage = Field(default_factory=UnparsedTermsCoverage)
    slot_terms: SlotTermsCoverage = Field(default_factory=SlotTermsCoverage)


def build_coverage_report(payload: CoverageReport | Mapping[str, Any] | None = None) -> CoverageReport:
    if payload is None:
        return CoverageReport()
    if isinstance(payload, CoverageReport):
        return payload
    return CoverageReport.model_validate(payload)
