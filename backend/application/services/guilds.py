"""Guild administration use cases."""

from backend.application.ports.persistence import UnitOfWork
from backend.application.read_models import GuildSettings


async def set_guild_settings(
    uow: UnitOfWork,
    guild_id: str,
    enabled: bool,
    allowed_channel_ids: list[str],
    retention_days: int,
) -> GuildSettings:
    settings = GuildSettings(guild_id, enabled, allowed_channel_ids, retention_days)
    result = await uow.guilds.save_settings(settings)
    await uow.commit()
    return result


async def delete_guild_data(uow: UnitOfWork, guild_id: str) -> None:
    await uow.guilds.delete_data(guild_id)
    await uow.commit()
