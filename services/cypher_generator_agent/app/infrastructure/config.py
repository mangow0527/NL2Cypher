from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


_DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


class Settings(BaseSettings):
    __test__ = False
    app_name: str = "cypher-generator-agent"
    host: str = "0.0.0.0"
    port: int = 8000
    testing_agent_url: str = "http://127.0.0.1:8003"
    request_timeout_seconds: float = 120.0
    graph_model_path: Path = _DEFAULT_ARTIFACT_DIR / "tugraph_network_graph_model.yaml"
    value_index_path: Path = _DEFAULT_ARTIFACT_DIR / "tugraph_value_index.json"

    model_config = SettingsConfigDict(
        env_prefix="CYPHER_GENERATOR_AGENT_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
