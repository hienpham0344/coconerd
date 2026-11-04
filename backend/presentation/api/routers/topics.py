from typing import Any

from fastapi import APIRouter, Depends, Query

from backend.application.errors import NotFound
from backend.application.ports.persistence import UnitOfWork
from backend.application.services import topics
from backend.presentation.api.dependencies import ApiDependencies


def create_router(dependencies: ApiDependencies) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/topics", tags=["topics"], dependencies=dependencies.bot)
    async def list_topics(
        guild_id: str = Query(min_length=1, max_length=100),
        channel_id: str | None = Query(default=None, min_length=1, max_length=100),
        include_closed: bool = False,
        limit: int = Query(default=50, ge=1, le=100),
        uow: UnitOfWork = Depends(dependencies.get_uow),
    ) -> dict[str, Any]:
        items = await topics.list_topics(uow, guild_id, channel_id, include_closed, limit)
        return {
            "items": [
                {
                    "topic_id": topic.id,
                    "guild_id": topic.guild_id,
                    "channel_id": topic.channel_id,
                    "title": topic.title,
                    "status": topic.status,
                    "last_activity_at": topic.last_activity_at,
                    "discord_thread_id": topic.discord_thread_id,
                    "message_count": topic.message_count,
                }
                for topic in items
            ]
        }

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
        dependencies=dependencies.bot,
    )
    async def get_topic_summary(
        topic_id: str,
        guild_id: str = Query(min_length=1, max_length=100),
        channel_id: str | None = Query(default=None, min_length=1, max_length=100),
        uow: UnitOfWork = Depends(dependencies.get_uow),
    ) -> dict[str, Any]:
        topic = await topics.get_topic(uow, guild_id, topic_id)
        if channel_id is not None and topic.channel_id != channel_id:
            raise NotFound("Topic not found in this channel")
        summary = await topics.get_topic_summary(uow, guild_id, topic_id)
        return {
            **summary.data,
            "title": topic.title,
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
