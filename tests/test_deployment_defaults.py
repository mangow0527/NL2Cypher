import unittest
from unittest.mock import patch

from services.cypher_generator_agent.app.config import Settings as CypherGeneratorAgentSettings
from services.repair_agent.app.config import Settings as RepairServiceSettings
from console.runtime_console.app.config import Settings as RuntimeResultsSettings
from services.testing_agent.app.config import Settings as TestingServiceSettings


class DeploymentDefaultsTest(unittest.TestCase):
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
        self.assertEqual(settings.knowledge_agent_url, "http://127.0.0.1:8010")
        self.assertEqual(settings.service_public_base_url, "http://127.0.0.1:8000")

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
        self.assertEqual(settings.tugraph_url, "http://118.196.92.128:7070")

    def test_runtime_results_center_defaults_bind_console_port(self):
        settings = RuntimeResultsSettings()

        self.assertEqual(settings.port, 8001)
        self.assertEqual(settings.cypher_generator_agent_data_dir, "data/cypher_generator_agent")
        self.assertEqual(settings.testing_data_dir, "data/testing_service")
        self.assertEqual(settings.repair_data_dir, "data/repair_service")

    def test_repair_service_defaults_target_fixed_remote_tugraph(self):
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

        self.assertEqual(settings.cypher_generator_agent_url, "http://127.0.0.1:8000")
        self.assertEqual(settings.tugraph_url, "http://118.196.92.128:7070")
