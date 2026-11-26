from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, Depends

from backend.application.errors import NotFound
from backend.application.ports.persistence import UnitOfWork
from backend.application.services import guilds
from backend.presentation.api.dependencies import ApiDependencies
from backend.presentation.api.schemas import (
    GuildSettingsRequest,
)


def _serialize_settings(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    if is_dataclass(item):
        return asdict(item)
    return {
        "guild_id": item.guild_id,
        "enabled": item.enabled,
        "allowed_channel_ids": list(item.allowed_channel_ids),
        "retention_days": item.retention_days,
        "output_channel_id": getattr(item, "output_channel_id", None),
    }


def create_router(dependencies: ApiDependencies) -> APIRouter:
    router = APIRouter()
    bot_or_admin = (
        dependencies.bot_or_admin if dependencies.bot_or_admin is not None else dependencies.bot
    )

    @router.get(
        "/api/v1/admin/guilds",
        tags=["admin"],
        dependencies=dependencies.admin,
        include_in_schema=False,
    )
    async def list_guilds(
        uow: UnitOfWork = Depends(dependencies.get_uow),
    ) -> dict[str, Any]:
        items = await guilds.list_guild_settings(uow)
        return {"items": [_serialize_settings(item) for item in items]}

    @router.get(
        "/api/v1/admin/guilds/{guild_id}/settings",
        tags=["admin"],
        dependencies=bot_or_admin,
        include_in_schema=False,
    )
    @router.get(
        "/api/v1/guilds/{guild_id}/settings",
        tags=["guilds"],
        dependencies=bot_or_admin,
    )
    async def get_guild_settings(
        guild_id: str, uow: UnitOfWork = Depends(dependencies.get_uow)
    ) -> dict[str, Any]:
        result = await guilds.get_guild_settings(uow, guild_id)
        if result is None:
            raise NotFound("Guild settings not found")
        return _serialize_settings(result)

    @router.put(
        "/api/v1/admin/guilds/{guild_id}/settings",
        tags=["admin"],
        dependencies=dependencies.admin,
    )
    async def set_guild_settings(
        guild_id: str,
        body: GuildSettingsRequest,
        uow: UnitOfWork = Depends(dependencies.get_uow),
    ) -> dict[str, Any]:
        result = await guilds.set_guild_settings(
            uow,
            guild_id,
            body.enabled,
            body.allowed_channel_ids,
            body.retention_days,
            body.output_channel_id,
        )
        return _serialize_settings(result)

    @router.delete(
        "/api/v1/admin/guilds/{guild_id}/data",
        tags=["admin"],
        dependencies=dependencies.admin,
    )
    async def delete_guild_data(
        guild_id: str, uow: UnitOfWork = Depends(dependencies.get_uow)
    ) -> dict[str, str]:
        await guilds.delete_guild_data(uow, guild_id)
        return {"guild_id": guild_id, "status": "deleted"}

    return router
