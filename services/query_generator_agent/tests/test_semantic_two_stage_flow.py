import tempfile
import unittest

from services.query_generator_agent.app.models import QAQuestionRequest
from services.query_generator_agent.app import prompt_overrides
from services.query_generator_agent.app.repository import QueryGeneratorRepository
from services.query_generator_agent.app.service import QueryWorkflowService


class _ExplodingPromptClient:
    async def fetch_prompt(self, id: str, question: str) -> str:
        raise AssertionError("semantic two-stage experiment should reuse the strict local prompt baseline")


class _TwoStageGeneratorClient:
    def __init__(self) -> None:
        self.calls = []

    async def generate_from_prompt(self, task_id: str, question_text: str, generation_prompt: str):
        self.calls.append((task_id, generation_prompt))
        if task_id.endswith(":semantic_parsing"):
            return {
                "raw_output": """
{
  "entities": ["Link", "Port"],
  "relations": ["LINK_DST"],
  "attributes": [],
  "conditions": [],
  "limit": 5,
  "direction": "directed",
  "aggregation": "none",
  "ordering": "none",
  "return_shape": "key_plus_entity"
}
""".strip()
            }
        return {"raw_output": "MATCH (l:Link)-[:LINK_DST]->(p:Port) RETURN l.id AS link_id, p.name AS port_name LIMIT 5"}


class _TestingClient:
    def __init__(self) -> None:
        self.payloads = []

    async def submit(self, payload):
        self.payloads.append(payload)


class SemanticTwoStageFlowTest(unittest.IsolatedAsyncioTestCase):
    def test_intent_guided_experiment_bypasses_ko_without_manual_prompt_override(self) -> None:
        question_id = "semantic_intent_guided_eval_link_dst_port_001"

        self.assertTrue(prompt_overrides.uses_intent_guided_flow(question_id))
        self.assertTrue(hasattr(prompt_overrides, "should_bypass_knowledge_ops_prompt"))
        self.assertTrue(prompt_overrides.should_bypass_knowledge_ops_prompt(question_id))
        self.assertIsNone(prompt_overrides.build_manual_prompt_override(question_id, "查询5条链路及其目的端口信息。"))

    async def test_semantic_two_stage_eval_runs_semantic_parsing_before_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            generator = _TwoStageGeneratorClient()
            testing = _TestingClient()
            service = QueryWorkflowService(
                prompt_client=_ExplodingPromptClient(),
                generator_client=generator,
                testing_client=testing,
                repository=QueryGeneratorRepository(data_dir=tmpdir),
            )

            response = await service.ingest_question(
                QAQuestionRequest(
                    id="semantic_two_stage_eval_link_dst_port_001",
                    question="查询5条链路及其目的端口信息。",
                )
            )

        self.assertEqual(response.generation_status, "submitted_to_testing")
        self.assertEqual(len(generator.calls), 2)
        self.assertTrue(generator.calls[0][0].endswith(":semantic_parsing"))
        self.assertIn("task: semantic_parsing", generator.calls[0][1])
        self.assertIn("链路目的端口", generator.calls[0][1])
        self.assertIn("链路终点端口", generator.calls[0][1])
        self.assertIn("LINK_DST", generator.calls[0][1])
        self.assertIn("【结构化语义表示】", generator.calls[1][1])
        self.assertIn("\"return_shape\": \"key_plus_entity\"", generator.calls[1][1])
        self.assertIn("【Schema】", generator.calls[1][1])
        self.assertIn("【术语映射】", generator.calls[1][1])
        self.assertEqual(len(testing.payloads), 1)
        self.assertIn("【Stage 1 Semantic Parsing Prompt】", testing.payloads[0].input_prompt_snapshot)
        self.assertIn("【Stage 2 Generation Prompt】", testing.payloads[0].input_prompt_snapshot)


if __name__ == "__main__":
    unittest.main()
