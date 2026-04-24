"""Compatibility exports for cross-service contract tests.

Production service code should use service-local models.
"""

from pydantic import BaseModel, Field

from services.query_generator_agent.app.models import (
    GeneratedCypherSubmissionRequest,
    GenerationRunResult,
    PreflightCheck,
    QAQuestionRequest,
)
from services.repair_agent.app.models import (
    KRSSAnalysisRecord,
    KRSSIssueTicketResponse,
    KnowledgeRepairSuggestionRequest,
    KnowledgeType,
)
from services.testing_agent.app.models import (
    ActualAnswer,
    CypherGenerationRequest,
    DiagnosticSummary,
    DiagnosticTag,
    Difficulty,
    DimensionStatus,
    DispatchStatus,
    EvaluationDimensions,
    EvaluationMetrics,
    EvaluationState,
    EvaluationSubmissionRequest,
    EvaluationSubmissionResponse,
    EvaluationSummary,
    ExpectedAnswer,
    FailureClass,
    GenerationEvidence,
    GeneratedCypher,
    GenerationContext,
    GenerationProcessingStatus,
    ImprovementAssessment,
    ImprovementDimensions,
    ImprovementDimensionStatus,
    IssueTicket,
    KnowledgeContext,
    KnowledgePackage,
    QuestionAlignmentMetrics,
    QAGoldenRequest,
    QAGoldenResponse,
    RepairPlanState,
    ResultCorrectnessMetrics,
    RootCauseType,
    SchemaAlignmentMetrics,
    Severity,
    SyntaxValidityMetrics,
    TuGraphExecutionResult,
    Verdict,
)


class PromptSnapshotResponse(BaseModel):
    id: str
    input_prompt_snapshot: str
    attempt_no: int = Field(default=1, ge=1)


__all__ = [
    "ActualAnswer",
    "CypherGenerationRequest",
    "DiagnosticSummary",
    "DiagnosticTag",
    "Difficulty",
    "DimensionStatus",
    "DispatchStatus",
    "EvaluationDimensions",
    "EvaluationMetrics",
    "EvaluationState",
    "EvaluationSubmissionRequest",
    "EvaluationSubmissionResponse",
    "EvaluationSummary",
    "ExpectedAnswer",
    "FailureClass",
    "GenerationEvidence",
    "GeneratedCypher",
    "GenerationContext",
    "GenerationProcessingStatus",
    "ImprovementAssessment",
    "ImprovementDimensionStatus",
    "ImprovementDimensions",
    "IssueTicket",
    "KRSSAnalysisRecord",
    "KRSSIssueTicketResponse",
    "KnowledgeContext",
    "KnowledgePackage",
    "KnowledgeRepairSuggestionRequest",
    "KnowledgeType",
    "QuestionAlignmentMetrics",
    "PromptSnapshotResponse",
    "GeneratedCypherSubmissionRequest",
    "GenerationRunResult",
    "PreflightCheck",
    "QAGoldenRequest",
    "QAGoldenResponse",
    "QAQuestionRequest",
    "RepairPlanState",
    "ResultCorrectnessMetrics",
    "RootCauseType",
    "SchemaAlignmentMetrics",
    "Severity",
    "SyntaxValidityMetrics",
    "TuGraphExecutionResult",
    "Verdict",
]
