from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from coconerd_ai.task_routing import TaskRouter, validate_meta_endpoint


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        hide_input_in_errors=True,
    )

    app_env: str = Field(
        default="development", validation_alias=AliasChoices("COCONERD_APP_ENV", "APP_ENV")
    )
    debug: bool = Field(default=False, validation_alias=AliasChoices("COCONERD_DEBUG", "DEBUG"))
    host: str = Field(default="0.0.0.0", validation_alias=AliasChoices("COCONERD_HOST", "HOST"))
    port: int = Field(default=8000, validation_alias=AliasChoices("COCONERD_PORT", "PORT"))
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/coconerd.db",
        validation_alias=AliasChoices("COCONERD_DATABASE_URL", "DATABASE_URL"),
    )
    checkpoint_db_path: str = "./data/checkpoints.db"
    require_postgres: bool = Field(default=False, validation_alias="COCONERD_REQUIRE_POSTGRES")
    bot_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("COCONERD_BOT_API_KEY", "BOT_API_KEY")
    )
    admin_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("COCONERD_ADMIN_API_KEY", "ADMIN_API_KEY")
    )
    meta_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "COCONERD_MODEL_API_KEY", "MODEL_API_KEY", "COCONERD_META_API_KEY", "META_API_KEY"
        ),
    )
    meta_api_base: str = Field(
        default="https://api.meta.ai/v1",
        validation_alias=AliasChoices("COCONERD_META_API_BASE", "META_API_BASE"),
    )
    meta_model_name: str = Field(
        default="muse-spark-1.3",
        validation_alias=AliasChoices("COCONERD_META_MODEL_NAME", "META_MODEL_NAME"),
    )
    mock_llm: bool = Field(
        default=False, validation_alias=AliasChoices("COCONERD_MOCK_LLM", "MOCK_LLM")
    )
    llm_temperature: float = 0.0
    llm_max_tokens: int = Field(
        default=2048,
        validation_alias=AliasChoices("COCONERD_LLM_MAX_TOKENS", "LLM_MAX_TOKENS"),
    )
    llm_reasoning_effort: Literal["minimal", "low", "medium", "high", "xhigh", "max"] = Field(
        default="low",
        validation_alias=AliasChoices("COCONERD_LLM_REASONING_EFFORT", "LLM_REASONING_EFFORT"),
    )
    agent_mode: Literal["task", "single"] = Field(
        default="task", validation_alias="COCONERD_AGENT_MODE"
    )
    agent_task_profiles: str = Field(default="{}", validation_alias="COCONERD_TASK_PROFILES")
    worker_poll_seconds: float = Field(
        default=1.0,
        validation_alias=AliasChoices("COCONERD_WORKER_POLL_SECONDS", "WORKER_POLL_SECONDS"),
    )
    worker_lease_seconds: int = Field(
        default=60,
        validation_alias=AliasChoices("COCONERD_WORKER_LEASE_SECONDS", "WORKER_LEASE_SECONDS"),
    )
    worker_max_attempts: int = Field(
        default=5,
        validation_alias=AliasChoices("COCONERD_WORKER_MAX_ATTEMPTS", "WORKER_MAX_ATTEMPTS"),
    )
    action_lease_seconds: int = Field(
        default=60,
        validation_alias=AliasChoices("COCONERD_ACTION_LEASE_SECONDS", "ACTION_LEASE_SECONDS"),
    )
    max_request_bytes: int = Field(
        default=65536,
        validation_alias=AliasChoices("COCONERD_MAX_REQUEST_BYTES", "MAX_REQUEST_BYTES"),
    )
    max_message_length: int = Field(
        default=8000,
        validation_alias=AliasChoices("COCONERD_MAX_MESSAGE_LENGTH", "MAX_MESSAGE_LENGTH"),
    )
    retention_days: int = Field(
        default=365,
        validation_alias=AliasChoices("COCONERD_RETENTION_DAYS", "RETENTION_DAYS"),
    )
    topic_dormant_after_days: int = Field(
        default=30,
        validation_alias=AliasChoices(
            "COCONERD_TOPIC_DORMANT_AFTER_DAYS", "TOPIC_DORMANT_AFTER_DAYS"
        ),
    )
    log_level: str = Field(
        default="INFO", validation_alias=AliasChoices("COCONERD_LOG_LEVEL", "LOG_LEVEL")
    )
    cors_origins: list[str] = Field(
        default_factory=list, validation_alias=AliasChoices("COCONERD_CORS_ORIGINS", "CORS_ORIGINS")
    )

    @field_validator("database_url")
    @classmethod
    def require_async_database(cls, value: str) -> str:
        if value.startswith("sqlite:///"):
            return value.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+asyncpg://" + value[len(prefix) :]
        if not value.startswith(("sqlite+aiosqlite:", "postgresql+asyncpg://")):
            raise ValueError("DATABASE_URL must use SQLite/aiosqlite or PostgreSQL/asyncpg")
        return value

    @model_validator(mode="after")
    def enforce_runtime_database(self) -> "Settings":
        if self.require_postgres and not self.database_url.startswith("postgresql+asyncpg://"):
            raise ValueError("PostgreSQL is required; configure COCONERD_DATABASE_URL")
        return self

    @model_validator(mode="after")
    def validate_task_configuration(self) -> "Settings":
        validate_meta_endpoint(self.meta_api_base)
        TaskRouter(
            model=self.meta_model_name,
            temperature=self.llm_temperature,
            max_tokens=self.llm_max_tokens,
            reasoning_effort=self.llm_reasoning_effort,
            mode=self.agent_mode,
            profiles_json=self.agent_task_profiles,
        )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
