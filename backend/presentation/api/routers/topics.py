from typing import Any

from fastapi import APIRouter, Depends, Query

from backend.application.ports.persistence import UnitOfWork
from backend.application.services import topics
from backend.presentation.api.dependencies import ApiDependencies


def create_router(dependencies: ApiDependencies) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/api/v1/topics/{topic_id}",
        tags=["topics"],
        dependencies=dependencies.bot,
    )
    async def get_topic(
        topic_id: str,
        guild_id: str = Query(min_length=1, max_length=100),
        uow: UnitOfWork = Depends(dependencies.get_uow),
    ) -> dict[str, Any]:
        topic = await topics.get_topic(uow, guild_id, topic_id)
        return {
            "topic_id": topic.id,
            "guild_id": topic.guild_id,
            "title": topic.title,
            "description": topic.description,
            "status": topic.status,
            "discord_thread_id": topic.discord_thread_id,
            "last_activity": topic.last_activity_at,
        }

    @router.get(
        "/api/v1/topics/{topic_id}/messages",
        tags=["topics"],
        dependencies=dependencies.bot,
    )
    async def get_topic_messages(
        topic_id: str,
        guild_id: str = Query(min_length=1, max_length=100),
        limit: int = Query(default=50, ge=1, le=100),
        before: str | None = Query(default=None),
        uow: UnitOfWork = Depends(dependencies.get_uow),
    ) -> dict[str, Any]:
        messages = await topics.get_topic_messages(uow, guild_id, topic_id, limit, before)
        return {
            "items": [
                {
                    "message_id": message.discord_message_id,
                    "channel_id": message.channel_id,
                    "author_id": message.author_id,
                    "author_name": message.author_name,
                    "content": message.content,
                    "created_at": message.created_at,
                    "reply_to_message_id": message.reply_to_message_id,
                }
                for message in messages
            ],
            "limit": limit,
        }

    @router.get(
        "/api/v1/topics/{topic_id}/summary",
        tags=["topics"],
        dependencies=[Depends(dependencies.bot_auth)],
    )
    async def get_topic_summary(
        topic_id: str,
        guild_id: str = Query(min_length=1, max_length=100),
        uow: UnitOfWork = Depends(dependencies.get_uow),
    ) -> dict[str, Any]:
        summary = await topics.get_topic_summary(uow, guild_id, topic_id)
        return {
            **summary.data,
            "version": summary.version,
            "source_message_ids": summary.source_message_ids,
        }

    @router.post(
        "/api/v1/admin/topics/{topic_id}/close",
        tags=["admin"],
        dependencies=dependencies.admin,
    )
    async def close_topic(
        topic_id: str,
        guild_id: str = Query(min_length=1, max_length=100),
        uow: UnitOfWork = Depends(dependencies.get_uow),
    ) -> dict[str, str]:
        await topics.close_topic(uow, guild_id, topic_id)
        return {"topic_id": topic_id, "status": "CLOSED"}

    @router.delete(
        "/api/v1/admin/topics/{topic_id}",
        tags=["admin"],
        dependencies=[Depends(dependencies.admin_auth)],
    )
    async def delete_topic(
        topic_id: str,
        guild_id: str = Query(min_length=1, max_length=100),
        uow: UnitOfWork = Depends(dependencies.get_uow),
    ) -> dict[str, str]:
        await topics.delete_topic(uow, guild_id, topic_id)
        return {"topic_id": topic_id, "status": "deleted"}

    return router
