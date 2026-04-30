from __future__ import annotations

from services.repair_agent.app.analysis import build_diagnosis_context
from services.repair_agent.app.prompting import build_repair_diagnosis_prompt
from services.testing_agent.app.models import (
    ActualPayload,
    EvaluationSummary,
    ExecutionAccuracy,
    ExecutionResult,
    ExpectedPayload,
    GenerationEvidence,
    GLEUSignal,
    GrammarMetric,
    IssueTicket,
    JaroWinklerSimilaritySignal,
    PrimaryMetrics,
    SecondarySignals,
    SemanticCheck,
    StrictCheck,
)


def _make_ticket(prompt_snapshot: str) -> IssueTicket:
    return IssueTicket(
        ticket_id="ticket-prompting-001",
        id="q-prompting",
        difficulty="L3",
        question="Which services use tunnel T1?",
        expected=ExpectedPayload(
            cypher="MATCH (s:Service)-[:SERVICE_USES_TUNNEL]->(t:Tunnel {name:'T1'}) RETURN s",
            answer=[],
        ),
        actual=ActualPayload(
            generated_cypher="MATCH (s:Service) RETURN s",
            execution=ExecutionResult(success=True, rows=[], row_count=0, error_message=None, elapsed_ms=12),
        ),
        evaluation=EvaluationSummary(
            verdict="fail",
            primary_metrics=PrimaryMetrics(
                grammar=GrammarMetric(score=1, parser_error=None, message=None),
                execution_accuracy=ExecutionAccuracy(
                    score=0,
                    reason="not_equivalent",
                    strict_check=StrictCheck(
                        status="fail",
                        message="The generated query ignored the tunnel relation.",
                        order_sensitive=False,
                        expected_row_count=1,
                        actual_row_count=0,
                    ),
                    semantic_check=SemanticCheck(
                        status="fail",
                        message="The query intent is not equivalent.",
                        raw_output=None,
                    ),
                ),
            ),
            secondary_signals=SecondarySignals(
                gleu=GLEUSignal(score=0.41, tokenizer="whitespace", min_n=1, max_n=4),
                jaro_winkler_similarity=JaroWinklerSimilaritySignal(
                    score=0.78,
                    normalization="lightweight",
                    library="jellyfish",
                ),
            ),
        ),
        generation_evidence=GenerationEvidence(
            generation_run_id="run-prompting-001",
            attempt_no=1,
            input_prompt_snapshot=prompt_snapshot,
        ),
    )


def test_build_repair_diagnosis_prompt_contains_diagnosis_work_order_and_compacted_context():
    repeated_line = "- Few-shot: Service uses Tunnel via SERVICE_USES_TUNNEL."
    prompt_snapshot = "\n".join(
        [
            "## System Rules",
            repeated_line,
            repeated_line,
            "## Business Knowledge",
            "- Tunnel means a network tunnel.",
        ]
    )
    ticket = _make_ticket(prompt_snapshot)
    context = build_diagnosis_context(ticket, prompt_snapshot)

    system_prompt, user_prompt = build_repair_diagnosis_prompt(context, ticket=ticket)

    assert "知识修复诊断器" in system_prompt
    assert "repairable" in system_prompt
    assert "non_repairable_reason" in system_prompt
    assert "IssueTicketSummary:" in user_prompt
    assert "DiagnosisContext:" in user_prompt
    assert "诊断顺序" in user_prompt
    assert "知识类型选择规则" in user_prompt
    assert "判断 prompt_evidence 的规则" in user_prompt
    assert '"input_prompt_snapshot"' not in user_prompt
    assert user_prompt.count(repeated_line) == 1


def test_build_repair_diagnosis_prompt_requires_chinese_suggestion_and_reasoning_fields():
    ticket = _make_ticket("## Prompt\n- Service uses Tunnel via SERVICE_USES_TUNNEL.")
    context = build_diagnosis_context(ticket, ticket.generation_evidence.input_prompt_snapshot)

    system_prompt, user_prompt = build_repair_diagnosis_prompt(context, ticket=ticket)
    prompt = system_prompt + "\n" + user_prompt

    assert "suggestion、rationale、non_repairable_reason 必须使用中文" in prompt
    assert "不能使用英文修复建议或英文原因说明" in prompt
