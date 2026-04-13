from __future__ import annotations

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "repair-service"
    host: str = "0.0.0.0"
    port: int = 8002
    data_dir: str = "data/repair_service"
    cgs_base_url: str = "http://127.0.0.1:8000"
    knowledge_ops_repairs_apply_url: str = "http://127.0.0.1:8003/api/knowledge/repairs/apply"
    knowledge_ops_repairs_apply_capture_dir: Optional[str] = None
    query_generator_service_url: str = "http://127.0.0.1:8000"
    knowledge_ops_feedback_url: Optional[str] = None
    qa_generation_feedback_url: Optional[str] = None
    request_timeout_seconds: float = 60.0

    tugraph_url: str = "http://127.0.0.1:7070"
    tugraph_username: str = "admin"
    tugraph_password: str = "admin"
    tugraph_graph: str = "default"
    mock_tugraph: bool = True

    qwen_model_name: str = "qwen-32b"

    generator_llm_enabled: bool = False
    generator_llm_base_url: Optional[str] = None
    generator_llm_api_key: Optional[str] = None
    generator_llm_model: Optional[str] = None
    generator_llm_temperature: float = 0.1

    llm_enabled: bool = False
    llm_provider: str = "openai_compatible"
    llm_base_url: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_model_name: Optional[str] = None
    llm_temperature: float = 0.1

    model_config = SettingsConfigDict(
        env_prefix="REPAIR_SERVICE_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()
