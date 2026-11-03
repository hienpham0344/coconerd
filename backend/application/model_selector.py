from typing import Protocol

from backend.config import Settings


class ModelConfiguration(Protocol):
    provider: str
    model_id: str
    temperature: float
    max_tokens: int
    enabled: bool


class ModelSelector:
    """Resolve an authorized guild override before the global model configuration."""

    @staticmethod
    def select(
        defaults: Settings,
        guild_config: ModelConfiguration | None,
        global_config: ModelConfiguration | None,
    ) -> Settings:
        selected = guild_config if guild_config and guild_config.enabled else global_config
        if selected is None or not selected.enabled:
            return defaults
        if selected.provider != "meta":
            raise ValueError(f"Unsupported model provider: {selected.provider}")
        return defaults.model_copy(
            update={
                "meta_model_name": selected.model_id,
                "llm_temperature": selected.temperature,
                "llm_max_tokens": selected.max_tokens,
            }
        )
