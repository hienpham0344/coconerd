"""Passive queries and writes for retention workflows."""

from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.read_models import (
    GuildSettings,
    RetainedMessage,
    RetentionAction,
    SummarySources,
)
from backend.infrastructure.database.models import (
    AIDecisionRecord,
    ApiRateLimitRecord,
    DiscordActionRecord,
    GuildSettingsRecord,
    MessageRecord,
    MessageTopicAssociationRecord,
    ProcessingJobRecord,
    ReviewEventRecord,
    TopicSummaryRecord,
)


class RetentionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def prune_rate_limits(self, cutoff: datetime) -> None:
        await self.session.execute(
            delete(ApiRateLimitRecord).where(ApiRateLimitRecord.window_start < cutoff)
        )

    async def guild_settings(self) -> list[GuildSettings]:
        rows = await self.session.scalars(select(GuildSettingsRecord))
        return [
            GuildSettings(
                row.guild_id, row.enabled, list(row.allowed_channel_ids), row.retention_days
            )
            for row in rows
        ]

    async def messages_before(self, guild_id: str, cutoff: datetime) -> list[RetainedMessage]:
        rows = await self.session.scalars(
            select(MessageRecord).where(
                MessageRecord.guild_id == guild_id, MessageRecord.created_at < cutoff
            )
        )
        return [RetainedMessage(row.id, row.discord_message_id) for row in rows]

    async def actions(self, guild_id: str) -> list[RetentionAction]:
        rows = await self.session.scalars(
            select(DiscordActionRecord).where(
                DiscordActionRecord.guild_id == guild_id,
                DiscordActionRecord.action_type.in_(["CREATE_THREAD", "APPEND_MESSAGE"]),
            )
        )
        return [RetentionAction(row.id, row.status, dict(row.payload)) for row in rows]

    async def summary_sources(self, guild_id: str) -> list[SummarySources]:
        rows = await self.session.scalars(
            select(TopicSummaryRecord).where(TopicSummaryRecord.guild_id == guild_id)
        )
        return [SummarySources(row.id, list(row.source_message_ids)) for row in rows]

    async def replace_summary_sources(self, summary_id: str, source_message_ids: list[str]) -> None:
        await self.session.execute(
            update(TopicSummaryRecord)
            .where(TopicSummaryRecord.id == summary_id)
            .values(source_message_ids=source_message_ids)
        )

    async def delete_messages(self, record_ids: list[str]) -> None:
        for model in (
            ReviewEventRecord,
            ProcessingJobRecord,
            AIDecisionRecord,
            MessageTopicAssociationRecord,
        ):
            await self.session.execute(delete(model).where(model.message_record_id.in_(record_ids)))
        await self.session.execute(delete(MessageRecord).where(MessageRecord.id.in_(record_ids)))
