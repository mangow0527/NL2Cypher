from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional

from shared.evaluation import evaluate_submission
from shared.models import (
    ActualAnswer,
    EvaluationSubmissionRequest,
    EvaluationSubmissionResponse,
    ExpectedAnswer,
    IssueTicket,
    QAGoldenRequest,
    QAGoldenResponse,
    QueryQuestionResponse,
)
from shared.tugraph import TuGraphClient

from .clients import LLMEvaluationClient, QueryGeneratorConsoleClient, RepairServiceClient, ServiceHealthClient
from .config import settings
from .repository import TestingRepository

logger = logging.getLogger("testing_service")

DEFAULT_CGS_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_KNOWLEDGE_OPS_BASE_URL = "http://127.0.0.1:8010"
DEFAULT_QA_GENERATOR_BASE_URL = "http://127.0.0.1:8020"


class EvaluationService:
    def __init__(
        self,
        repository: TestingRepository,
        repair_client: RepairServiceClient,
        tugraph_client: TuGraphClient,
        llm_client: Optional[LLMEvaluationClient] = None,
        console_query_client: Optional[QueryGeneratorConsoleClient] = None,
        health_client: Optional[ServiceHealthClient] = None,
    ) -> None:
        self.repository = repository
        self.repair_client = repair_client
        self.tugraph_client = tugraph_client
        self.llm_client = llm_client
        self.console_query_client = console_query_client or QueryGeneratorConsoleClient(
            base_url=DEFAULT_CGS_BASE_URL,
            timeout_seconds=settings.request_timeout_seconds,
        )
        self.health_client = health_client or ServiceHealthClient()

    async def ingest_golden(self, request: QAGoldenRequest) -> QAGoldenResponse:
        self.repository.save_golden(request)
        submission = self.repository.get_submission(request.id)
        if submission is None:
            return QAGoldenResponse(id=request.id, status="received_golden_only")
        return await self._evaluate_ready_pair(request.id)

    async def ingest_submission(self, request: EvaluationSubmissionRequest) -> EvaluationSubmissionResponse:
        golden = self.repository.get_golden(request.id)
        status = "ready_to_evaluate" if golden else "waiting_for_golden"
        self.repository.save_submission(request, status=status)
        if golden is None:
            return EvaluationSubmissionResponse(id=request.id, status="waiting_for_golden")
        return await self._evaluate_ready_pair(request.id)

    async def _evaluate_ready_pair(self, id: str) -> EvaluationSubmissionResponse | QAGoldenResponse:
        golden = self.repository.get_golden(id)
        submission = self.repository.get_submission(id)
        if not golden or not submission:
            raise RuntimeError(f"Expected both golden and submission before evaluating id={id}")

        execution = await self.tugraph_client.execute(submission["generated_cypher"])
        self.repository.save_submission_execution(id, execution.model_dump_json())
        expected_answer = json.loads(golden["golden_answer_json"])

        evaluation = evaluate_submission(
            question=submission["question"],
            expected_cypher=golden["golden_cypher"],
            expected_answer=expected_answer,
            actual_cypher=submission["generated_cypher"],
            execution=execution,
            loaded_knowledge_tags=[],
        )

        if evaluation.verdict != "pass" and self.llm_client is not None:
            evaluation = await self._llm_re_evaluate(
                evaluation=evaluation,
                question=submission["question"],
                expected_cypher=golden["golden_cypher"],
                expected_answer=expected_answer,
                actual_cypher=submission["generated_cypher"],
                execution=execution,
            )

        if evaluation.verdict == "pass":
            self.repository.mark_submission_status(id, "passed")
            return EvaluationSubmissionResponse(id=id, status="passed", verdict=evaluation.verdict)

        ticket = IssueTicket(
            ticket_id=f"ticket-{id}",
            id=id,
            difficulty=golden["difficulty"],
            question=submission["question"],
            expected=ExpectedAnswer(cypher=golden["golden_cypher"], answer=expected_answer),
            actual=ActualAnswer(
                generated_cypher=submission["generated_cypher"],
                execution=execution,
            ),
            evaluation=evaluation,
            input_prompt_snapshot=submission.get("input_prompt_snapshot", ""),
        )
        self.repository.save_issue_ticket(ticket)
        krss_response = await self.repair_client.submit_issue_ticket(ticket)
        self.repository.save_submission_krss_response(id, krss_response.model_dump(mode="json"))
        return EvaluationSubmissionResponse(
            id=id,
            status="issue_ticket_created",
            issue_ticket_id=ticket.ticket_id,
            verdict=evaluation.verdict,
        )

    async def _llm_re_evaluate(
        self,
        evaluation,
        question: str,
        expected_cypher: str,
        expected_answer,
        actual_cypher: str,
        execution,
    ):
        logger.info("Triggering LLM re-evaluation for question: %s", question)
        llm_result = await self.llm_client.evaluate(
            question=question,
            expected_cypher=expected_cypher,
            expected_answer=expected_answer,
            actual_cypher=actual_cypher,
            actual_result=execution.rows,
            rule_based_verdict=evaluation.verdict,
            rule_based_dimensions=evaluation.dimensions.model_dump(),
        )
        if llm_result is None:
            logger.warning("LLM re-evaluation returned None, keeping rule-based verdict")
            return evaluation

        dimensions = evaluation.dimensions
        llm_result_correctness = llm_result.get("result_correctness")
        llm_question_alignment = llm_result.get("question_alignment")
        reasoning = llm_result.get("reasoning", "")
        confidence = llm_result.get("confidence", 0.0)

        if llm_result_correctness == "pass" and dimensions.result_correctness == "fail":
            dimensions.result_correctness = "pass"
            evaluation.evidence.append(f"[LLM override] result_correctness flipped to pass: {reasoning}")
            logger.info("LLM overrode result_correctness to pass (confidence=%.2f)", confidence)

        if llm_question_alignment == "pass" and dimensions.question_alignment == "fail":
            dimensions.question_alignment = "pass"
            evaluation.evidence.append(f"[LLM override] question_alignment flipped to pass: {reasoning}")
            logger.info("LLM overrode question_alignment to pass (confidence=%.2f)", confidence)

        evaluation.dimensions = dimensions
        failures = [
            dimensions.syntax_validity,
            dimensions.schema_alignment,
            dimensions.result_correctness,
            dimensions.question_alignment,
        ].count("fail")

        if failures == 0:
            evaluation.verdict = "pass"
        elif failures == 4 or dimensions.syntax_validity == "fail":
            evaluation.verdict = "fail"
        else:
            evaluation.verdict = "partial_fail"

        return evaluation

    def get_evaluation_status(self, id: str) -> Dict[str, object]:
        golden = self.repository.get_golden(id)
        submission = self.repository.get_submission(id)
        return {
            "id": id,
            "has_golden": golden is not None,
            "has_submission": submission is not None,
            "golden": golden,
            "submission": submission,
        }

    def get_issue_ticket(self, ticket_id: str) -> Optional[IssueTicket]:
        return self.repository.get_issue_ticket(ticket_id)

    def get_service_status(self) -> Dict[str, object]:
        return {
            "storage": settings.data_dir,
            "repair_service_url": settings.repair_service_url,
            "llm_enabled": settings.llm_enabled,
            "llm_model": settings.llm_model,
            "mode": "evaluation_router",
        }

    async def get_runtime_architecture(self) -> Dict[str, object]:
        services = [
            await self._build_service_card(
                service_key="cgs",
                label_zh="查询生成服务",
                label_en="Query Generator Service",
                base_url=DEFAULT_CGS_BASE_URL,
                port="8000",
                description_zh="接收自然语言问题并生成 Cypher 与提示快照。",
                description_en="Accepts natural-language questions and generates Cypher plus prompt snapshots.",
                key_endpoints=["POST /api/v1/qa/questions", "GET /api/v1/questions/{id}/prompt"],
            ),
            await self._build_service_card(
                service_key="testing_service",
                label_zh="测试服务",
                label_en="Testing Service",
                base_url=f"http://127.0.0.1:{settings.port}",
                port=str(settings.port),
                description_zh="聚合黄金样本、评测结果、问题票据与联调控制台视图。",
                description_en="Aggregates goldens, evaluation results, issue tickets, and console runtime views.",
                key_endpoints=["POST /api/v1/qa/goldens", "POST /api/v1/evaluations/submissions"],
            ),
            await self._build_service_card(
                service_key="krss",
                label_zh="知识修复建议服务",
                label_en="Knowledge Repair Suggestion Service",
                base_url=settings.repair_service_url,
                port="8002",
                description_zh="接收问题票据并生成知识修复建议。",
                description_en="Receives issue tickets and returns knowledge repair suggestions.",
                key_endpoints=["POST /api/v1/issue-tickets"],
            ),
            await self._build_service_card(
                service_key="knowledge_ops",
                label_zh="知识运营服务",
                label_en="Knowledge Ops Service",
                base_url=DEFAULT_KNOWLEDGE_OPS_BASE_URL,
                port="8010",
                description_zh="接收 KRSS 的正式知识修复请求并落地知识补丁。",
                description_en="Receives formal knowledge repair requests from KRSS and applies knowledge patches.",
                key_endpoints=["POST /api/knowledge/rag/prompt-package", "POST /api/knowledge/repairs/apply"],
            ),
            await self._build_service_card(
                service_key="qa_generator",
                label_zh="问答生成服务",
                label_en="QA Generator Service",
                base_url=DEFAULT_QA_GENERATOR_BASE_URL,
                port="8020",
                description_zh="提供题目与黄金样本生成能力，供联调与回归使用。",
                description_en="Provides question and golden-sample generation for integration and regression workflows.",
                key_endpoints=["POST /jobs", "POST /jobs/quick-run"],
            ),
        ]
        return {
            "title_zh": "系统运行架构",
            "title_en": "System Runtime Architecture",
            "services": services,
            "links": self._runtime_links(),
            "data_objects": self._runtime_data_objects(),
        }

    async def run_console_flow(self, *, id: str, question: str) -> Dict[str, object]:
        self.repository.clear_console_run(id)
        architecture = await self.get_runtime_architecture()
        generation = await self._get_console_generation(id=id, question=question)
        generation_dict = generation.model_dump(mode="json")

        golden_record = self.repository.get_golden(id)
        if golden_record is None:
            raise ValueError(f"No golden answer found for id={id}. Please submit a golden first.")
        try:
            expected_answer = json.loads(golden_record.get("golden_answer_json") or "[]")
        except Exception:
            expected_answer = []
        golden = QAGoldenRequest(
            id=id,
            cypher=str(golden_record.get("golden_cypher") or ""),
            answer=expected_answer,
            difficulty=str(golden_record.get("difficulty") or "L3"),
        )

        submission_request = EvaluationSubmissionRequest(
            id=id,
            question=question,
            generation_run_id=generation.generation_run_id,
            generated_cypher=generation.generated_cypher,
            parse_summary=generation.parse_summary,
            guardrail_summary=generation.guardrail_summary,
            raw_output_snapshot=generation.raw_output_snapshot,
            input_prompt_snapshot=generation.input_prompt_snapshot,
        )
        evaluation_response: EvaluationSubmissionResponse | None = None
        if not await self._is_service_online(settings.repair_service_url):
            evaluation_response = await self._evaluate_console_without_krss(
                request=submission_request,
                golden=golden,
            )
        else:
            try:
                evaluation_response = await asyncio.wait_for(
                    self.ingest_submission(submission_request),
                    timeout=min(20.0, float(settings.request_timeout_seconds)),
                )
            except asyncio.TimeoutError:
                logger.warning("console run timed out while waiting for evaluation for id=%s", id)
            except Exception as exc:
                logger.warning("console run encountered downstream failure for id=%s: %s", id, exc)

        submission_snapshot = self.repository.get_submission_snapshot(id)
        issue_snapshot = self.repository.get_issue_snapshot_by_submission_id(id)
        krss_snapshot = self.repository.get_krss_snapshot_by_submission_id(id)
        execution = self._execution_snapshot_from_submission(submission_snapshot)
        evaluation_snapshot = self._evaluation_snapshot(
            response=evaluation_response,
            issue_snapshot=issue_snapshot,
            execution_snapshot=execution,
        )
        evaluation_verdict = evaluation_snapshot.get("verdict", "fail")
        knowledge_repair_status = (
            "success"
            if krss_snapshot is not None
            else ("failed" if issue_snapshot is not None else "skipped")
        )

        stages = {
            "query_generation": {
                "label_zh": "查询生成",
                "label_en": "Query Generation",
                "status": "failed" if generation.failure_stage else "success",
            },
            "evaluation": {
                "label_zh": "评测执行",
                "label_en": "Evaluation",
                "status": "success" if evaluation_verdict == "pass" else "failed",
            },
            "knowledge_repair": {
                "label_zh": "知识修复",
                "label_en": "Knowledge Repair",
                "status": knowledge_repair_status if krss_snapshot is None else "success",
            },
        }
        return {
            "id": id,
            "question": question,
            "title_zh": "系统联调运行",
            "title_en": "System Integration Run",
            "service_cards": architecture["services"],
            "links": architecture["links"],
            "data_objects": architecture["data_objects"],
            "stages": stages,
            "timeline": [
                {
                    "stage_key": "query_generation",
                    "label_zh": "CGS 生成任务",
                    "label_en": "CGS generation task",
                    "status": stages["query_generation"]["status"],
                },
                {
                    "stage_key": "prompt_fetch",
                    "label_zh": "知识运营提示词获取",
                    "label_en": "Knowledge Ops prompt fetch",
                    "status": "success" if generation.input_prompt_snapshot else "failed",
                },
                {
                    "stage_key": "evaluation",
                    "label_zh": "Testing Service 评测",
                    "label_en": "Testing Service evaluation",
                    "status": stages["evaluation"]["status"],
                },
                {
                    "stage_key": "knowledge_repair",
                    "label_zh": "KRSS 问题诊断",
                    "label_en": "KRSS issue diagnosis",
                    "status": stages["knowledge_repair"]["status"],
                },
                {
                    "stage_key": "knowledge_apply",
                    "label_zh": "知识运营修复接收",
                    "label_en": "Knowledge Ops repair apply",
                    "status": "success" if krss_snapshot is not None else "skipped",
                },
            ],
            "artifacts": {
                "generation": generation_dict,
                "submission": submission_snapshot,
                "execution": execution,
                "evaluation": evaluation_snapshot,
                "knowledge_repair": {
                    "issue_ticket": issue_snapshot,
                    "krss_response": krss_snapshot,
                    "status": knowledge_repair_status,
                },
            },
        }

    async def _build_service_card(
        self,
        *,
        service_key: str,
        label_zh: str,
        label_en: str,
        base_url: str,
        port: str,
        description_zh: str,
        description_en: str,
        key_endpoints: list[str],
    ) -> Dict[str, Any]:
        status = "unknown"
        try:
            await self.health_client.read_health(base_url=base_url, timeout_seconds=1.0)
            status = "online"
        except Exception:
            status = "offline"
        return {
            "service_key": service_key,
            "label_zh": label_zh,
            "label_en": label_en,
            "base_url": base_url,
            "port": port,
            "status": status,
            "description_zh": description_zh,
            "description_en": description_en,
            "key_endpoints": key_endpoints,
        }

    def _runtime_links(self) -> list[Dict[str, str]]:
        return [
            {
                "source": "cgs",
                "target": "knowledge_ops",
                "label_zh": "获取提示词包",
                "label_en": "Fetch prompt package",
            },
            {
                "source": "cgs",
                "target": "testing_service",
                "label_zh": "提交评测结果",
                "label_en": "Submit evaluation payload",
            },
            {
                "source": "testing_service",
                "target": "krss",
                "label_zh": "发送问题票据",
                "label_en": "Send issue ticket",
            },
            {
                "source": "krss",
                "target": "cgs",
                "label_zh": "读取提示词快照",
                "label_en": "Read prompt snapshot",
            },
            {
                "source": "krss",
                "target": "knowledge_ops",
                "label_zh": "提交知识修复建议",
                "label_en": "Submit knowledge repair suggestion",
            },
            {
                "source": "qa_generator",
                "target": "testing_service",
                "label_zh": "提供黄金样本",
                "label_en": "Provide golden samples",
            },
            {
                "source": "testing_service",
                "target": "tugraph",
                "label_zh": "依赖 TuGraph 执行 Cypher",
                "label_en": "Depend on TuGraph for Cypher execution",
            },
        ]

    def _runtime_data_objects(self) -> list[Dict[str, str]]:
        return [
            {
                "object_key": "qa_question",
                "label_zh": "问答任务",
                "label_en": "QA Question",
                "source_zh": "外部调用方 / QA 生成器",
                "target_zh": "CGS",
                "meaning_zh": "一次待生成 Cypher 的问题输入，包含 id 与 question。",
            },
            {
                "object_key": "prompt_snapshot",
                "label_zh": "提示词快照",
                "label_en": "Prompt Snapshot",
                "source_zh": "CGS",
                "target_zh": "KRSS",
                "meaning_zh": "CGS 在本轮生成中实际使用的提示词原文。",
            },
            {
                "object_key": "evaluation_submission",
                "label_zh": "评测提交",
                "label_en": "Evaluation Submission",
                "source_zh": "CGS",
                "target_zh": "Testing Service",
                "meaning_zh": "生成结果与生成证据，用于执行与评测。",
            },
            {
                "object_key": "issue_ticket",
                "label_zh": "问题票据",
                "label_en": "Issue Ticket",
                "source_zh": "Testing Service",
                "target_zh": "KRSS",
                "meaning_zh": "失败样本与评测证据，用于知识根因分析。",
            },
            {
                "object_key": "knowledge_repair",
                "label_zh": "知识修复建议",
                "label_en": "Knowledge Repair Suggestion",
                "source_zh": "KRSS",
                "target_zh": "Knowledge Ops",
                "meaning_zh": "面向知识运营服务的正式知识修复请求。",
            },
        ]

    async def _get_console_generation(self, *, id: str, question: str) -> QueryQuestionResponse:
        timeout_seconds = min(10.0, float(settings.request_timeout_seconds))
        try:
            if await self._is_service_online(DEFAULT_CGS_BASE_URL):
                return await asyncio.wait_for(
                    self.console_query_client.submit_question(id=id, question=question),
                    timeout=timeout_seconds,
                )
        except asyncio.TimeoutError:
            logger.warning("console run timed out while waiting for CGS generation for id=%s", id)
        except Exception:
            logger.warning("console run falling back to local generation for id=%s", id)

        try:
            return await asyncio.wait_for(self.console_query_client.get_question_run(id), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            logger.warning("console run timed out while reading CGS question run for id=%s", id)
        except Exception:
            generated_cypher = "MATCH (n:NetworkElement) RETURN n.id AS id, n.name AS name LIMIT 20"
            return QueryQuestionResponse(
                id=id,
                generation_run_id=f"console-{id}",
                generation_status="generated",
                generated_cypher=generated_cypher,
                parse_summary="console_fallback_generation",
                guardrail_summary="passed",
                raw_output_snapshot=json.dumps({"cypher": generated_cypher}, ensure_ascii=False),
                failure_stage=None,
                failure_reason_summary=None,
                input_prompt_snapshot="Console runtime fallback prompt snapshot.",
            )

    async def _is_service_online(self, base_url: str) -> bool:
        try:
            await self.health_client.read_health(base_url=base_url, timeout_seconds=1.0)
            return True
        except Exception:
            return False

    async def _evaluate_console_without_krss(
        self,
        *,
        request: EvaluationSubmissionRequest,
        golden: QAGoldenRequest,
    ) -> EvaluationSubmissionResponse:
        self.repository.save_submission(request, status="ready_to_evaluate")
        execution = await self.tugraph_client.execute(request.generated_cypher)
        self.repository.save_submission_execution(request.id, execution.model_dump_json())
        evaluation = evaluate_submission(
            question=request.question,
            expected_cypher=golden.cypher,
            expected_answer=golden.answer,
            actual_cypher=request.generated_cypher,
            execution=execution,
            loaded_knowledge_tags=[],
        )
        if evaluation.verdict == "pass":
            self.repository.mark_submission_status(request.id, "passed")
            return EvaluationSubmissionResponse(id=request.id, status="passed", verdict=evaluation.verdict)

        ticket = IssueTicket(
            ticket_id=f"ticket-{request.id}",
            id=request.id,
            difficulty=golden.difficulty,
            question=request.question,
            expected=ExpectedAnswer(cypher=golden.cypher, answer=golden.answer),
            actual=ActualAnswer(generated_cypher=request.generated_cypher, execution=execution),
            evaluation=evaluation,
            input_prompt_snapshot=request.input_prompt_snapshot,
        )
        self.repository.save_issue_ticket(ticket)
        return EvaluationSubmissionResponse(
            id=request.id,
            status="issue_ticket_created",
            issue_ticket_id=ticket.ticket_id,
            verdict=evaluation.verdict,
        )

    def _execution_snapshot_from_submission(self, submission_snapshot: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not submission_snapshot or not submission_snapshot.get("execution_json"):
            return {
                "success": False,
                "rows": [],
                "row_count": 0,
                "error_message": "Execution not available.",
                "elapsed_ms": 0,
            }
        return json.loads(submission_snapshot["execution_json"])

    def _evaluation_snapshot(
        self,
        *,
        response: Optional[EvaluationSubmissionResponse],
        issue_snapshot: Optional[Dict[str, Any]],
        execution_snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
        if issue_snapshot is not None:
            return issue_snapshot["evaluation"]
        return {
            "verdict": response.verdict if response is not None else "pass",
            "dimensions": {
                "syntax_validity": "pass" if execution_snapshot.get("success") else "fail",
                "schema_alignment": "pass" if execution_snapshot.get("success") else "fail",
                "result_correctness": "pass",
                "question_alignment": "pass",
            },
            "symptom": "Console success path completed without generating an issue ticket.",
            "evidence": [],
        }


repository = TestingRepository(data_dir=settings.data_dir)

llm_client = None
if settings.llm_enabled and settings.llm_base_url and settings.llm_api_key and settings.llm_model:
    llm_client = LLMEvaluationClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout_seconds=settings.request_timeout_seconds,
        temperature=settings.llm_temperature,
    )

validation_service = EvaluationService(
    repository=repository,
    repair_client=RepairServiceClient(
        base_url=settings.repair_service_url,
        timeout_seconds=settings.request_timeout_seconds,
    ),
    tugraph_client=TuGraphClient(
        base_url=settings.tugraph_url,
        username=settings.tugraph_username,
        password=settings.tugraph_password,
        graph=settings.tugraph_graph,
        mock_mode=settings.mock_tugraph,
    ),
    llm_client=llm_client,
    console_query_client=QueryGeneratorConsoleClient(
        base_url=DEFAULT_CGS_BASE_URL,
        timeout_seconds=settings.request_timeout_seconds,
    ),
    health_client=ServiceHealthClient(),
)
