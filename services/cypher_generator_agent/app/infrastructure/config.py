from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    __test__ = False
    app_name: str = "cypher-generator-agent"
    host: str = "0.0.0.0"
    port: int = 8000
    testing_agent_url: str = "http://127.0.0.1:8003"
    request_timeout_seconds: float = 120.0

    model_config = SettingsConfigDict(
        env_prefix="CYPHER_GENERATOR_AGENT_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
