from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "query-generator-service"
    host: str = "0.0.0.0"
    port: int = 8000
    data_dir: str = "data/query_generator_service"
    testing_service_url: str = "http://127.0.0.1:8001"
    knowledge_ops_service_url: str = "http://127.0.0.1:8003"
    service_public_base_url: str = "http://127.0.0.1:8000"
    qwen_model_name: str = "qwen-32b"
    request_timeout_seconds: float = 30.0
    llm_enabled: bool = False
    llm_provider: str = "openai_compatible"
    llm_base_url: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_model: Optional[str] = None
    llm_temperature: float = 0.1

    model_config = SettingsConfigDict(
        env_prefix="QUERY_GENERATOR_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()
