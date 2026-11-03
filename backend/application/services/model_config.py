"""Global and guild model configuration, with explicit fallback policy."""

from backend.application.model_selector import ModelSelector
from backend.application.ports.persistence import UnitOfWork
from backend.application.read_models import ModelConfiguration
from backend.config import Settings


async def get_model_config(
    uow: UnitOfWork, guild_id: str | None, default: ModelConfiguration
) -> ModelConfiguration:
    if guild_id:
        override = await uow.model_config.get("guild", guild_id)
        if override is not None:
            return override
    return await uow.model_config.get("global", None) or default


async def set_model_config(
    uow: UnitOfWork,
    guild_id: str | None,
    provider: str,
    model_id: str,
    temperature: float,
    max_tokens: int,
) -> ModelConfiguration:
    config = ModelConfiguration(
        "guild" if guild_id else "global", guild_id, provider, model_id, temperature, max_tokens
    )
    await uow.model_config.save(config)
    await uow.commit()
    return config


async def select_worker_settings(uow: UnitOfWork, defaults: Settings, guild_id: str) -> Settings:
    guild_config = await uow.model_config.get_for_worker("guild", guild_id)
    global_config = await uow.model_config.get_for_worker("global", None)
    return ModelSelector.select(defaults, guild_config, global_config)
