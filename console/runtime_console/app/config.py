from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "runtime-results-service"
    host: str = "0.0.0.0"
    port: int = 8001
    cypher_generator_agent_data_dir: str = "data/cypher_generator_agent"
    testing_data_dir: str = "data/testing_service"
    user_query_data_dir: str = "data/runtime_console/user_queries"
    poll_interval_seconds: int = 5
    cypher_generator_agent_base_url: str = "http://127.0.0.1:8000"
    testing_service_base_url: str = "http://127.0.0.1:8003"
    qa_generator_base_url: str = "http://127.0.0.1:8020"
    cga_trace_profile: str = "all"
    diagnostic_llm_base_url: str | None = None
    diagnostic_llm_api_key: str | None = None
    diagnostic_llm_model: str | None = None
    diagnostic_llm_temperature: float = 0.1
    diagnostic_llm_timeout_seconds: float = 120.0

    model_config = SettingsConfigDict(
        env_prefix="RUNTIME_RESULTS_SERVICE_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()
