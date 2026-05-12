import unittest
from pathlib import Path
from unittest.mock import patch

from services.cypher_generator_agent.app.config import Settings as CypherGeneratorAgentSettings
from services.cypher_generator_agent.app.models import GenerationRunResult, ServiceFailureReason
from services.repair_agent.app.config import Settings as RepairServiceSettings
from console.runtime_console.app.config import Settings as RuntimeResultsSettings
from services.testing_agent.app.config import Settings as TestingServiceSettings


class DeploymentDefaultsTest(unittest.TestCase):
    def test_remote_env_example_uses_current_cypher_generator_prefixes(self):
        env_example = Path("deploy/remote.env.example").read_text(encoding="utf-8")

        self.assertIn("CYPHER_GENERATOR_AGENT_TESTING_AGENT_URL=", env_example)
        self.assertIn("CYPHER_GENERATOR_AGENT_KNOWLEDGE_DOCS_DIR=", env_example)
        self.assertIn("CYPHER_GENERATOR_AGENT_LLM_BASE_URL=", env_example)
        self.assertNotIn("QUERY_GENERATOR_LLM_", env_example)
        self.assertNotIn("QUERY_GENERATOR_TESTING_SERVICE_URL", env_example)
        self.assertNotIn("REPAIR_SERVICE_CGS_BASE_URL", env_example)
        self.assertNotIn("REPAIR_SERVICE_TUGRAPH_URL", env_example)
        self.assertNotIn("REPAIR_SERVICE_MOCK_TUGRAPH", env_example)

    def test_cypher_generator_agent_defaults_keep_local_service_routing(self):
        with patch.dict(
            "os.environ",
            {
                "CYPHER_GENERATOR_AGENT_LLM_ENABLED": "true",
                "CYPHER_GENERATOR_AGENT_LLM_BASE_URL": "https://example.com/v1",
                "CYPHER_GENERATOR_AGENT_LLM_API_KEY": "secret",
                "CYPHER_GENERATOR_AGENT_LLM_MODEL": "glm-4.5",
            },
            clear=False,
        ):
            settings = CypherGeneratorAgentSettings(_env_file=None)

        self.assertEqual(settings.testing_agent_url, "http://127.0.0.1:8003")
        self.assertEqual(settings.knowledge_docs_dir, "knowledge")
        self.assertEqual(settings.knowledge_context_source, "file")
        self.assertEqual(settings.rag_service_url, "http://127.0.0.1:8004")
        self.assertEqual(settings.rag_retrieval_limit, 12)
        self.assertEqual(settings.service_public_base_url, "http://127.0.0.1:8000")
        self.assertNotIn("knowledge_agent_url", CypherGeneratorAgentSettings.model_fields)
        self.assertIn("knowledge_docs_dir", CypherGeneratorAgentSettings.model_fields)

    def test_cypher_generator_agent_knowledge_docs_dir_env_override(self):
        with patch.dict(
            "os.environ",
            {
                "CYPHER_GENERATOR_AGENT_LLM_ENABLED": "true",
                "CYPHER_GENERATOR_AGENT_LLM_BASE_URL": "https://example.com/v1",
                "CYPHER_GENERATOR_AGENT_LLM_API_KEY": "secret",
                "CYPHER_GENERATOR_AGENT_LLM_MODEL": "glm-4.5",
                "CYPHER_GENERATOR_AGENT_KNOWLEDGE_DOCS_DIR": "/tmp/custom-knowledge",
            },
            clear=False,
        ):
            settings = CypherGeneratorAgentSettings(_env_file=None)

        self.assertEqual(settings.knowledge_docs_dir, "/tmp/custom-knowledge")

    def test_cypher_generator_agent_service_failure_reason_uses_local_context_name(self):
        self.assertIn("knowledge_context_unavailable", ServiceFailureReason.__args__)
        self.assertIn("semantic_contract_unaligned", ServiceFailureReason.__args__)
        self.assertNotIn("knowledge_agent_context_unavailable", ServiceFailureReason.__args__)

        GenerationRunResult(
            generation_run_id="run-1",
            generation_status="service_failed",
            reason="knowledge_context_unavailable",
        )
        GenerationRunResult(
            generation_run_id="run-semantic-contract",
            generation_status="service_failed",
            reason="semantic_contract_unaligned",
        )

        with self.assertRaises(ValueError):
            GenerationRunResult(
                generation_run_id="run-2",
                generation_status="service_failed",
                reason="knowledge_agent_context_unavailable",
            )

    def test_testing_service_defaults_target_fixed_remote_tugraph(self):
        with patch.dict(
            "os.environ",
            {
                "TESTING_SERVICE_LLM_ENABLED": "true",
                "TESTING_SERVICE_LLM_BASE_URL": "https://example.com/v1",
                "TESTING_SERVICE_LLM_API_KEY": "secret",
                "TESTING_SERVICE_LLM_MODEL": "glm-4.5",
            },
            clear=False,
        ):
            settings = TestingServiceSettings(_env_file=None)

        self.assertEqual(settings.port, 8003)
        self.assertEqual(settings.repair_service_url, "http://127.0.0.1:8002")
        self.assertEqual(settings.tugraph_url, "http://101.37.211.45:7070")

    def test_runtime_results_center_defaults_bind_console_port(self):
        settings = RuntimeResultsSettings()

        self.assertEqual(settings.port, 8001)
        self.assertEqual(settings.cypher_generator_agent_data_dir, "data/cypher_generator_agent")
        self.assertEqual(settings.testing_data_dir, "data/testing_service")
        self.assertEqual(settings.repair_data_dir, "data/repair_service")

    def test_repair_service_defaults_only_expose_repair_owned_settings(self):
        with patch.dict(
            "os.environ",
            {
                "REPAIR_SERVICE_LLM_ENABLED": "true",
                "REPAIR_SERVICE_LLM_BASE_URL": "https://example.com/v1",
                "REPAIR_SERVICE_LLM_API_KEY": "secret",
                "REPAIR_SERVICE_LLM_MODEL_NAME": "glm-4.5",
            },
            clear=False,
        ):
            settings = RepairServiceSettings(_env_file=None)

        self.assertEqual(settings.port, 8002)
        self.assertEqual(settings.knowledge_agent_repairs_apply_url, "http://127.0.0.1:8010/api/knowledge/repairs/apply")
        self.assertEqual(
            set(RepairServiceSettings.model_fields),
            {
                "app_name",
                "host",
                "port",
                "data_dir",
                "knowledge_agent_repairs_apply_url",
                "knowledge_agent_repairs_apply_capture_dir",
                "knowledge_agent_repairs_apply_max_attempts",
                "request_timeout_seconds",
                "llm_enabled",
                "llm_provider",
                "llm_base_url",
                "llm_api_key",
                "llm_model_name",
                "llm_temperature",
                "llm_max_retries",
                "llm_retry_base_delay_seconds",
                "llm_max_concurrency",
            },
        )
