"""Guild administration use cases."""

from backend.application.errors import NotFound
from backend.application.ports.persistence import UnitOfWork
from backend.application.read_models import GuildSettings


async def get_guild_settings(uow: UnitOfWork, guild_id: str) -> GuildSettings:
    settings = await uow.guilds.get_settings(guild_id)
    if settings is None:
        raise NotFound("Guild settings not found")
    return settings


async def set_guild_settings(
    uow: UnitOfWork,
    guild_id: str,
    enabled: bool,
    allowed_channel_ids: list[str],
    retention_days: int,
    output_channel_id: str | None = None,
) -> GuildSettings:
    settings = GuildSettings(
        guild_id, enabled, allowed_channel_ids, retention_days, output_channel_id
    )
    result = await uow.guilds.save_settings(settings)
    await uow.commit()
    return result


async def delete_guild_data(uow: UnitOfWork, guild_id: str) -> None:
    await uow.guilds.delete_data(guild_id)
    await uow.commit()
