"""Compose the existing backend with read-only dashboard routes."""

import os
from pathlib import Path
from typing import Literal

from fastapi import Depends, HTTPException, Query
from sqlalchemy import func, select

from backend.config import Settings
from backend.infrastructure.database.models import (
    GuildSettingsRecord,
    MessageRecord,
    MessageTopicAssociationRecord,
    TopicRecord,
)
from backend.presentation.api.app import create_app
from backend.presentation.api.security import admin_key_dependency


def create_bridge(settings=None, session_factory=None):
    settings = settings or Settings()
    app = create_app(settings, session_factory)
    factory = app.state.session_factory
    auth = [Depends(admin_key_dependency(settings.admin_api_key))]

    def guild_data(record):
        return {
            "guild_id": record.guild_id,
            "enabled": record.enabled,
            "allowed_channel_ids": record.allowed_channel_ids,
            "retention_days": record.retention_days,
        }

    async def require_guild(session, guild_id):
        record = await session.get(GuildSettingsRecord, guild_id)
        if record is None:
            raise HTTPException(404, "Server has not been configured.")
        return record

    @app.get("/api/v1/admin/web/guilds", dependencies=auth)
    async def list_guilds():
        async with factory() as session:
            records = await session.scalars(
                select(GuildSettingsRecord).order_by(GuildSettingsRecord.guild_id)
            )
            return {"items": [guild_data(record) for record in records]}

    @app.get("/api/v1/admin/web/guilds/{guild_id}/settings", dependencies=auth)
    async def get_settings(guild_id: str):
        async with factory() as session:
            return guild_data(await require_guild(session, guild_id))

    @app.get("/api/v1/admin/web/guilds/{guild_id}/overview", dependencies=auth)
    async def overview(guild_id: str):
        async with factory() as session:
            guild = await require_guild(session, guild_id)
            topics = await session.scalar(
                select(func.count())
                .select_from(TopicRecord)
                .where(TopicRecord.guild_id == guild_id)
            )
            active = await session.scalar(
                select(func.count())
                .select_from(TopicRecord)
                .where(
                    TopicRecord.guild_id == guild_id, TopicRecord.status.in_(["ACTIVE", "RESUMED"])
                )
            )
            messages = await session.scalar(
                select(func.count())
                .select_from(MessageRecord)
                .where(MessageRecord.guild_id == guild_id)
            )
            return {
                "topics": topics,
                "active_topics": active,
                "messages": messages,
                "channels": len(guild.allowed_channel_ids),
            }

    @app.get("/api/v1/admin/web/guilds/{guild_id}/topics", dependencies=auth)
    async def list_topics(
        guild_id: str,
        q: str = Query(default="", max_length=200),
        status: Literal["ACTIVE", "RESUMED", "DORMANT", "CLOSED"] | None = None,
        limit: int = Query(default=12, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        async with factory() as session:
            await require_guild(session, guild_id)
            filters = [TopicRecord.guild_id == guild_id]
            if status:
                filters.append(TopicRecord.status == status)
            if q.strip():
                escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                filters.append(TopicRecord.title.ilike(f"%{escaped}%", escape="\\"))
            total = await session.scalar(
                select(func.count()).select_from(TopicRecord).where(*filters)
            )
            count = (
                select(func.count())
                .select_from(MessageTopicAssociationRecord)
                .where(
                    MessageTopicAssociationRecord.topic_id == TopicRecord.id,
                    MessageTopicAssociationRecord.guild_id == guild_id,
                )
                .correlate(TopicRecord)
                .scalar_subquery()
            )
            rows = await session.execute(
                select(TopicRecord, count)
                .where(*filters)
                .order_by(TopicRecord.last_activity_at.desc(), TopicRecord.id)
                .limit(limit)
                .offset(offset)
            )
            items = [
                {
                    "topic_id": topic.id,
                    "guild_id": topic.guild_id,
                    "title": topic.title,
                    "description": topic.description,
                    "status": topic.status,
                    "last_activity": topic.last_activity_at,
                    "discord_thread_id": topic.discord_thread_id,
                    "message_count": number,
                }
                for topic, number in rows
            ]
            return {"items": items, "total": total, "limit": limit, "offset": offset}

    return app


def application():
    settings = Settings()
    if not os.getenv("COCONERD_DATABASE_URL"):
        raise RuntimeError(
            "Set COCONERD_DATABASE_URL to your existing migrated database; "
            "the bridge never creates or migrates user data."
        )
    database = settings.database_url.removeprefix("sqlite+aiosqlite:///").split("?", 1)[0]
    if not Path(database).is_file():
        raise RuntimeError(
            "The selected database does not exist. "
            "Use the database already configured for the backend worker."
        )
    return create_bridge(settings)
