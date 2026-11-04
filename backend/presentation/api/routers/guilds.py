from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends

from backend.application.ports.persistence import UnitOfWork
from backend.application.services import guilds
from backend.presentation.api.dependencies import ApiDependencies
from backend.presentation.api.schemas import (
    GuildSettingsRequest,
)


def create_router(dependencies: ApiDependencies) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/api/v1/guilds/{guild_id}/settings",
        tags=["guilds"],
        dependencies=dependencies.bot,
    )
    async def get_guild_settings(
        guild_id: str, uow: UnitOfWork = Depends(dependencies.get_uow)
    ) -> dict[str, Any]:
        return asdict(await guilds.get_guild_settings(uow, guild_id))

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
        return asdict(result)

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
