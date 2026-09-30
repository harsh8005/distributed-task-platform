from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Distributed Task Platform"
    environment: Literal["development", "test", "staging", "production"] = "development"

    database_url: str = Field(default="sqlite:///./distributed_task_platform.db")
    redis_url: str = Field(default="redis://localhost:6379/0")
    rabbitmq_url: str = Field(default="amqp://guest:guest@localhost:5672/%2F")

    jwt_secret_key: str = Field(default="change-me-in-production")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    worker_poll_interval_seconds: int = 2
    scheduler_poll_interval_seconds: int = 10
    retry_delay_seconds: int = 30
    max_job_attempts: int = 3
    queue_name: str = "task_jobs"

    auto_create_tables: bool = True
    enable_rabbitmq: bool = False
    enable_redis: bool = False

    metrics_namespace: str = "dtp"
    cors_allow_origins: str = "*"

    max_concurrent_jobs_per_tenant: int = 5
    outbox_poll_interval_seconds: float = 1.0
    outbox_max_retries: int = 5

    enable_otel: bool = False
    otlp_endpoint: str = "http://localhost:4318/v1/traces"

    autoscaler_min_workers: int = 1
    autoscaler_max_workers: int = 10
    autoscaler_jobs_per_worker: int = 5

    @property
    def allow_all_origins(self) -> bool:
        return self.cors_allow_origins.strip() == "*"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

