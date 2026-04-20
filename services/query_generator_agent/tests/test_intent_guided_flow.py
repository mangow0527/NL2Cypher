import tempfile
import unittest

from services.query_generator_agent.app.models import QAQuestionRequest
from services.query_generator_agent.app.repository import QueryGeneratorRepository
from services.query_generator_agent.app.service import QueryWorkflowService


class _ExplodingPromptClient:
    async def fetch_prompt(self, id: str, question: str) -> str:
        raise AssertionError("intent-guided experiment should reuse the local KO-derived prompt assembly path")


class _IntentGuidedGeneratorClient:
    def __init__(self) -> None:
        self.calls = []

    async def generate_from_prompt(self, task_id: str, question_text: str, generation_prompt: str):
        self.calls.append((task_id, generation_prompt))
        if task_id.endswith(":intent_understanding"):
            return {
                "raw_output": """
{
  "query_type": "relation_association",
  "primary_entity": "Link",
  "related_entities": ["Port"],
  "relation_paths": ["LINK_DST"],
  "filters": [],
  "aggregation": "none",
  "ordering_limit": {"limit": 5},
  "return_shape": "key_plus_entity"
}
""".strip()
            }
        return {"raw_output": "MATCH (l:Link)-[:LINK_DST]->(p:Port) RETURN l.id AS key, p LIMIT 5"}


class _TestingClient:
    def __init__(self) -> None:
        self.payloads = []

    async def submit(self, payload):
        self.payloads.append(payload)


class IntentGuidedFlowTest(unittest.IsolatedAsyncioTestCase):
    async def test_intent_guided_eval_selects_type_specific_knowledge_and_few_shot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            generator = _IntentGuidedGeneratorClient()
            testing = _TestingClient()
            service = QueryWorkflowService(
                prompt_client=_ExplodingPromptClient(),
                generator_client=generator,
                testing_client=testing,
                repository=QueryGeneratorRepository(data_dir=tmpdir),
            )

            response = await service.ingest_question(
                QAQuestionRequest(
                    id="semantic_intent_guided_eval_link_dst_port_001",
                    question="查询5条链路及其目的端口信息。",
                )
            )

        self.assertEqual(response.generation_status, "submitted_to_testing")
        self.assertEqual(len(generator.calls), 2)
        self.assertTrue(generator.calls[0][0].endswith(":intent_understanding"))
        self.assertIn("required_semantics:", generator.calls[0][1])
        self.assertIn("query_type: relation_association", generator.calls[1][1])
        self.assertIn("【按题型选择的知识】", generator.calls[1][1])
        self.assertIn("关系关联查询重点检查", generator.calls[1][1])
        self.assertIn("[id: link_dst_port_info_few_shot]", generator.calls[1][1])
        self.assertIn("Anti-Pattern: MATCH (l:Link)-[:LINK_DST]->(p:Port) RETURN l, p LIMIT 5", generator.calls[1][1])
        self.assertEqual(len(testing.payloads), 1)
        self.assertIn("【Stage 1 Intent Understanding Prompt】", testing.payloads[0].input_prompt_snapshot)
        self.assertIn("【Stage 2 Intent-Guided Generation Prompt】", testing.payloads[0].input_prompt_snapshot)


if __name__ == "__main__":
    unittest.main()
