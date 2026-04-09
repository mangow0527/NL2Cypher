from __future__ import annotations

from typing import Dict, List, Optional

from shared.evaluation import compare_answer, extract_labels, extract_relations
from shared.knowledge import DEFAULT_KNOWLEDGE_PACKAGE, build_knowledge_context, build_schema_hint_from_tags
from shared.models import CypherGenerationRequest, GenerationContext, IssueTicket, RepairAction, RepairPlan, RepairPlanEnvelope
from shared.tugraph import TuGraphClient

from services.query_generator_service.app.clients import (
    HeuristicCypherGenerator,
    OpenAICompatibleCypherGenerator,
    QwenGeneratorClient,
)

from .clients import DispatchClient, OpenAICompatibleRepairPlanner
from .config import settings
from .repository import RepairRepository


class RepairService:
    def __init__(
        self,
        repository: RepairRepository,
        generator_client: QwenGeneratorClient,
        tugraph_client: TuGraphClient,
        dispatch_client: DispatchClient,
        llm_planner: Optional[OpenAICompatibleRepairPlanner],
    ) -> None:
        self.repository = repository
        self.generator_client = generator_client
        self.tugraph_client = tugraph_client
        self.dispatch_client = dispatch_client
        self.llm_planner = llm_planner

    async def create_plan(self, issue_ticket: IssueTicket) -> RepairPlanEnvelope:
        root_cause, confidence, summary, actions = self._deterministic_analysis(issue_ticket)
        plan = RepairPlan(
            ticket_id=issue_ticket.ticket_id,
            id=issue_ticket.id,
            root_cause=root_cause,
            confidence=confidence,
            actions=actions,
            state="analyzing",
            analysis_summary=summary,
        )

        if root_cause in {"mixed_issue", "unknown", "knowledge_gap_issue"}:
            plan.state = "counterfactual_checking"
            plan.counterfactuals = await self._run_counterfactuals(issue_ticket)
            root_cause, confidence, summary, actions = self._apply_counterfactuals(issue_ticket, plan.counterfactuals, root_cause)
            plan.root_cause = root_cause
            plan.confidence = confidence
            plan.analysis_summary = summary
            plan.actions = actions

        if self.llm_planner is not None:
            try:
                refined = await self.llm_planner.refine(issue_ticket, plan)
                if refined:
                    plan.root_cause = refined.get("root_cause", plan.root_cause)
                    plan.confidence = float(refined.get("confidence", plan.confidence))
                    plan.analysis_summary = refined.get("analysis_summary", plan.analysis_summary)
                    if isinstance(refined.get("actions"), list) and refined["actions"]:
                        plan.actions = [RepairAction(**item) for item in refined["actions"]]
            except Exception:
                pass

        plan.state = "repair_plan_created"
        self.repository.save_plan(plan)
        await self._dispatch(plan)
        plan.state = "dispatched"
        self.repository.save_plan(plan)
        return RepairPlanEnvelope(status="created", plan=plan)

    def _deterministic_analysis(self, ticket: IssueTicket):
        evidence = list(ticket.evaluation.evidence)
        ambiguous = any(token in ticket.question.lower() for token in ["随便", "看看", "情况", "这个", "那个", "帮我看看"])
        expected_labels = set(extract_labels(ticket.expected.cypher))
        expected_relations = set(extract_relations(ticket.expected.cypher))
        loaded_tags = set(ticket.knowledge_context.loaded_knowledge_tags)
        expected_tag_map = {
            "NetworkElement": "network_element",
            "Port": "port",
            "Service": "service",
            "Tunnel": "tunnel",
            "Protocol": "protocol",
            "Fiber": "fiber",
            "Link": "link",
            "HAS_PORT": "has_port",
            "SERVICE_USES_TUNNEL": "service_uses_tunnel",
        }
        missing_tags = sorted(
            tag for item, tag in expected_tag_map.items() if ((item in expected_labels or item in expected_relations) and tag not in loaded_tags)
        )

        if ambiguous and ticket.evaluation.dimensions.question_alignment == "fail":
            return (
                "qa_question_issue",
                0.9,
                "Question wording is ambiguous and likely under-specifies the target query.",
                [
                    RepairAction(
                        target_service="qa_generation_service",
                        action_type="question_rewrite",
                        instruction="Rewrite the question to explicitly mention target entities, relations, and expected constraints.",
                        evidence=evidence,
                    )
                ],
            )

        if missing_tags:
            return (
                "knowledge_gap_issue",
                0.8,
                f"Loaded knowledge tags do not cover expected concepts: {missing_tags}.",
                [
                    RepairAction(
                        target_service="knowledge_ops_service",
                        action_type="knowledge_enrichment",
                        instruction=(
                            "Enrich the knowledge package so it covers the missing concepts and templates: "
                            + ", ".join(missing_tags)
                        ),
                        evidence=evidence,
                    )
                ],
            )

        if ticket.evaluation.dimensions.syntax_validity == "fail" or ticket.evaluation.dimensions.schema_alignment == "fail":
            return (
                "generator_logic_issue",
                0.85,
                "Generated Cypher is invalid or not aligned with the graph schema.",
                [
                    RepairAction(
                        target_service="query_generator_service",
                        action_type="prompt_adjustment",
                        instruction="Tighten the generation prompt and validation constraints so only valid schema elements are produced.",
                        evidence=evidence,
                    )
                ],
            )

        if ticket.evaluation.dimensions.result_correctness == "fail" and ticket.evaluation.dimensions.question_alignment == "fail":
            return (
                "mixed_issue",
                0.55,
                "Both semantic alignment and final result quality failed; more evidence is needed.",
                [
                    RepairAction(
                        target_service="query_generator_service",
                        action_type="manual_review",
                        instruction="Inspect prompt behavior and reasoning path for this query.",
                        evidence=evidence,
                    ),
                    RepairAction(
                        target_service="qa_generation_service",
                        action_type="manual_review",
                        instruction="Inspect whether the question formulation matches the golden intent.",
                        evidence=evidence,
                    ),
                ],
            )

        return (
            "unknown",
            0.35,
            "Deterministic evidence is insufficient; run counterfactual experiments.",
            [
                RepairAction(
                    target_service="query_generator_service",
                    action_type="manual_review",
                    instruction="Review this item manually after counterfactual experiments.",
                    evidence=evidence,
                )
            ],
        )

    async def _run_counterfactuals(self, ticket: IssueTicket) -> List[Dict[str, object]]:
        experiments: List[Dict[str, object]] = []
        label_names = extract_labels(ticket.expected.cypher)
        experiment_inputs = [
            ("A_same_knowledge", ticket.question, ticket.knowledge_context.loaded_knowledge_tags),
            ("B_expanded_knowledge", ticket.question, DEFAULT_KNOWLEDGE_PACKAGE.knowledge_tags),
            (
                "C_clarified_question",
                f"{ticket.question}。请明确返回与{'、'.join(label_names) or '目标实体'}相关的数据。",
                ticket.knowledge_context.loaded_knowledge_tags,
            ),
        ]
        for name, question, tags in experiment_inputs:
            knowledge_context = build_knowledge_context(list(tags))
            generation = await self.generator_client.generate(
                CypherGenerationRequest(
                    context=GenerationContext(
                        id=ticket.id,
                        question=question,
                        schema_hint=build_schema_hint_from_tags(list(tags)),
                        attempt=1,
                        knowledge_context=knowledge_context,
                    )
                )
            )
            execution = await self.tugraph_client.execute(generation.cypher)
            matches, detail = compare_answer(ticket.expected.answer, execution)
            experiments.append(
                {
                    "experiment": name,
                    "question": question,
                    "knowledge_tags": list(tags),
                    "generated_cypher": generation.cypher,
                    "match_expected": matches,
                    "detail": detail,
                    "execution": execution.model_dump(),
                }
            )
        return experiments

    def _apply_counterfactuals(self, ticket: IssueTicket, experiments: List[Dict[str, object]], default_root: str):
        exp_map = {item["experiment"]: item for item in experiments}
        a_ok = exp_map.get("A_same_knowledge", {}).get("match_expected")
        b_ok = exp_map.get("B_expanded_knowledge", {}).get("match_expected")
        c_ok = exp_map.get("C_clarified_question", {}).get("match_expected")

        if a_ok:
            return (
                "generator_logic_issue",
                0.82,
                "Under the same knowledge conditions, a regenerated query can match the golden answer, pointing to generator-side logic or prompt issues.",
                [
                    RepairAction(
                        target_service="query_generator_service",
                        action_type="prompt_adjustment",
                        instruction="Adjust query generation prompts or decoding constraints to consistently produce the successful counterfactual pattern.",
                        evidence=[str(exp_map["A_same_knowledge"])],
                    )
                ],
            )
        if b_ok and not a_ok:
            return (
                "knowledge_gap_issue",
                0.88,
                "Expanded knowledge enables a successful query while the original knowledge set does not.",
                [
                    RepairAction(
                        target_service="knowledge_ops_service",
                        action_type="knowledge_enrichment",
                        instruction="Add the missing schema and business-term knowledge reflected by the successful expanded-knowledge counterfactual.",
                        evidence=[str(exp_map["B_expanded_knowledge"])],
                    )
                ],
            )
        if c_ok and not a_ok:
            return (
                "qa_question_issue",
                0.86,
                "A lightly clarified question leads to a correct query while the original question does not.",
                [
                    RepairAction(
                        target_service="qa_generation_service",
                        action_type="question_rewrite",
                        instruction="Rewrite future questions to explicitly mention target entities and expected return scope.",
                        evidence=[str(exp_map["C_clarified_question"])],
                    )
                ],
            )
        if b_ok and c_ok:
            return (
                "mixed_issue",
                0.7,
                "Both knowledge enrichment and question clarification improve the outcome, so the issue is mixed.",
                [
                    RepairAction(
                        target_service="knowledge_ops_service",
                        action_type="knowledge_enrichment",
                        instruction="Expand knowledge coverage for this topic.",
                        evidence=[str(exp_map["B_expanded_knowledge"])],
                    ),
                    RepairAction(
                        target_service="qa_generation_service",
                        action_type="question_rewrite",
                        instruction="Improve question specificity for this topic.",
                        evidence=[str(exp_map["C_clarified_question"])],
                    ),
                ],
            )
        return (
            default_root,
            0.4,
            "Counterfactual experiments did not isolate a single dominant source of failure.",
            [
                RepairAction(
                    target_service="query_generator_service",
                    action_type="manual_review",
                    instruction="Escalate this item for manual review with all counterfactual traces attached.",
                    evidence=[str(item) for item in experiments],
                )
            ],
        )

    async def _dispatch(self, plan: RepairPlan) -> None:
        for action in plan.actions:
            payload = plan.model_dump()
            if action.target_service == "query_generator_service":
                url = f"{settings.query_generator_service_url.rstrip('/')}/api/v1/internal/repair-plans"
                await self.dispatch_client.post_json(url, payload)
                action.dispatch_status = "sent"
                self.repository.save_outbox(plan.plan_id, action.target_service, plan.model_dump_json(), "sent")
                continue

            target_url = settings.knowledge_ops_feedback_url if action.target_service == "knowledge_ops_service" else settings.qa_generation_feedback_url
            if target_url:
                await self.dispatch_client.post_json(target_url, payload)
                action.dispatch_status = "sent"
                self.repository.save_outbox(plan.plan_id, action.target_service, plan.model_dump_json(), "sent")
            else:
                action.dispatch_status = "stored_for_later"
                self.repository.save_outbox(plan.plan_id, action.target_service, plan.model_dump_json(), "stored_for_later")

    def get_service_status(self) -> Dict[str, object]:
        return {
            "storage": settings.data_dir,
            "query_generator_service_url": settings.query_generator_service_url,
            "llm_enabled": settings.llm_enabled,
            "llm_model": settings.llm_model_name,
            "mode": "repair_planner",
        }

    def get_plan(self, plan_id: str) -> Optional[RepairPlan]:
        return self.repository.get_plan(plan_id)


llm_generator = None
if (
    settings.generator_llm_enabled
    and settings.generator_llm_base_url
    and settings.generator_llm_api_key
    and settings.generator_llm_model
):
    llm_generator = OpenAICompatibleCypherGenerator(
        base_url=settings.generator_llm_base_url,
        api_key=settings.generator_llm_api_key,
        model=settings.generator_llm_model,
        timeout_seconds=settings.request_timeout_seconds,
        temperature=settings.generator_llm_temperature,
    )

repair_llm = None
if settings.llm_enabled and settings.llm_base_url and settings.llm_api_key and settings.llm_model_name:
    repair_llm = OpenAICompatibleRepairPlanner(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model_name,
        timeout_seconds=settings.request_timeout_seconds,
        temperature=settings.llm_temperature,
    )

repair_service = RepairService(
    repository=RepairRepository(data_dir=settings.data_dir),
    generator_client=QwenGeneratorClient(
        heuristic_generator=HeuristicCypherGenerator(model_name=settings.qwen_model_name),
        llm_generator=llm_generator,
    ),
    tugraph_client=TuGraphClient(
        base_url=settings.tugraph_url,
        username=settings.tugraph_username,
        password=settings.tugraph_password,
        graph=settings.tugraph_graph,
        mock_mode=settings.mock_tugraph,
    ),
    dispatch_client=DispatchClient(timeout_seconds=settings.request_timeout_seconds),
    llm_planner=repair_llm,
)
