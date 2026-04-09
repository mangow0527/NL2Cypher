from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "testing-service"
    host: str = "0.0.0.0"
    port: int = 8001
    db_path: str = "data/testing_service.db"
    repair_service_url: str = "http://127.0.0.1:8002"
    request_timeout_seconds: float = 30.0

    model_config = SettingsConfigDict(
        env_prefix="TESTING_SERVICE_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()
