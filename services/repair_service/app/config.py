from __future__ import annotations

import os
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "repair-service"
    host: str = "0.0.0.0"
    port: int = 8002
    db_path: str = "data/repair_service.db"
    query_generator_service_url: str = "http://127.0.0.1:8000"
    knowledge_ops_feedback_url: Optional[str] = None
    qa_generation_feedback_url: Optional[str] = None
    request_timeout_seconds: float = 60.0
    tugraph_url: str = os.getenv("QUERY_GENERATOR_TUGRAPH_URL", "http://127.0.0.1:7070")
    tugraph_username: str = os.getenv("QUERY_GENERATOR_TUGRAPH_USERNAME", "admin")
    tugraph_password: str = os.getenv("QUERY_GENERATOR_TUGRAPH_PASSWORD", "admin")
    tugraph_graph: str = os.getenv("QUERY_GENERATOR_TUGRAPH_GRAPH", "default")
    mock_tugraph: bool = os.getenv("QUERY_GENERATOR_MOCK_TUGRAPH", "true").lower() == "true"
    qwen_model_name: str = os.getenv("QUERY_GENERATOR_QWEN_MODEL_NAME", "qwen-32b")
    generator_llm_enabled: bool = os.getenv("QUERY_GENERATOR_LLM_ENABLED", "false").lower() == "true"
    generator_llm_base_url: Optional[str] = os.getenv("QUERY_GENERATOR_LLM_BASE_URL")
    generator_llm_api_key: Optional[str] = os.getenv("QUERY_GENERATOR_LLM_API_KEY")
    generator_llm_model: Optional[str] = os.getenv("QUERY_GENERATOR_LLM_MODEL")
    generator_llm_temperature: float = float(os.getenv("QUERY_GENERATOR_LLM_TEMPERATURE", "0.1"))
    llm_enabled: bool = os.getenv("REPAIR_SERVICE_LLM_ENABLED", os.getenv("TESTING_SERVICE_GPT_ENABLED", "false")).lower() == "true"
    llm_provider: str = os.getenv("REPAIR_SERVICE_LLM_PROVIDER", os.getenv("TESTING_SERVICE_GPT_PROVIDER", "glm_openai_compatible"))
    llm_base_url: Optional[str] = os.getenv("REPAIR_SERVICE_LLM_BASE_URL", os.getenv("TESTING_SERVICE_GPT_BASE_URL"))
    llm_api_key: Optional[str] = os.getenv("REPAIR_SERVICE_LLM_API_KEY", os.getenv("TESTING_SERVICE_GPT_API_KEY"))
    llm_model_name: Optional[str] = os.getenv("REPAIR_SERVICE_LLM_MODEL_NAME", os.getenv("TESTING_SERVICE_GPT_MODEL_NAME"))
    llm_temperature: float = float(os.getenv("REPAIR_SERVICE_LLM_TEMPERATURE", os.getenv("TESTING_SERVICE_GPT_TEMPERATURE", "0.1")))

    model_config = SettingsConfigDict(
        env_prefix="REPAIR_SERVICE_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()
