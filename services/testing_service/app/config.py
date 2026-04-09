from __future__ import annotations

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "testing-service"
    host: str = "0.0.0.0"
    port: int = 8001
    data_dir: str = "data/testing_service"
    repair_service_url: str = "http://127.0.0.1:8002"
    request_timeout_seconds: float = 30.0

    llm_enabled: bool = False
    llm_provider: str = "openai_compatible"
    llm_base_url: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_model: Optional[str] = None
    llm_temperature: float = 0.1

    model_config = SettingsConfigDict(
        env_prefix="TESTING_SERVICE_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()
