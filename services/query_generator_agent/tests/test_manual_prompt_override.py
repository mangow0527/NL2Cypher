import tempfile
import unittest

from services.query_generator_agent.app.models import QAQuestionRequest
from services.query_generator_agent.app.repository import QueryGeneratorRepository
from services.query_generator_agent.app.service import QueryWorkflowService


class _ExplodingPromptClient:
    async def fetch_prompt(self, id: str, question: str) -> str:
        raise AssertionError("manual prompt override should bypass Knowledge Ops")


class _UnusedGeneratorClient:
    async def generate_from_prompt(self, task_id: str, question_text: str, generation_prompt: str):
        raise AssertionError("generator should not be called in this test")


class _UnusedTestingClient:
    async def submit(self, payload):
        raise AssertionError("testing client should not be called in this test")


class ManualPromptOverrideTest(unittest.IsolatedAsyncioTestCase):
    async def test_manual_prompt_eval_id_uses_local_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = QueryWorkflowService(
                prompt_client=_ExplodingPromptClient(),
                generator_client=_UnusedGeneratorClient(),
                testing_client=_UnusedTestingClient(),
                repository=QueryGeneratorRepository(data_dir=tmpdir),
            )

            response, prompt = await service._fetch_prompt(
                request=QAQuestionRequest(
                    id="manual_prompt_eval_link_dst_port_001",
                    question="查询5条链路及其目的端口信息。",
                ),
                generation_run_id="run-1",
                attempt_no=1,
            )

        self.assertIsNone(response)
        self.assertIn("默认返回满足问题语义的最小结果结构", prompt)
        self.assertIn("若问题未明确字段，则可以直接返回实体对象", prompt)
        self.assertIn("Question: 查询业务使用的隧道名称", prompt)
        self.assertIn("Question: 查询指定隧道经过的设备顺序", prompt)
        self.assertIn("错误示例：MATCH (s:Service)-[:LINK_TO]->(t:Tunnel) RETURN s.name, t.name", prompt)
        self.assertIn("“光纤源端口” 表示模式 `(f:Fiber)-[:FIBER_SRC]->(p:Port)`。", prompt)
        self.assertNotIn("RETURN a.id AS key, b LIMIT 5", prompt)
        self.assertIn("查询5条链路及其目的端口信息。", prompt)


if __name__ == "__main__":
    unittest.main()
