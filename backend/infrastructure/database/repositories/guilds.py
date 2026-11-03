from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.read_models import GuildSettings
from backend.infrastructure.database.models import (
    AIDecisionRecord,
    DiscordActionRecord,
    EpisodeRecord,
    GuildSettingsRecord,
    MessageRecord,
    MessageTopicAssociationRecord,
    ModelConfigRecord,
    ProcessingJobRecord,
    TopicRecord,
    TopicSummaryRecord,
)


class GuildRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def channel_is_enabled(self, guild_id: str, channel_id: str) -> bool:
        setting = await self.session.get(GuildSettingsRecord, guild_id)
        return bool(setting and setting.enabled and channel_id in setting.allowed_channel_ids)

    async def save_settings(self, settings: GuildSettings) -> GuildSettings:
        record = await self.session.get(GuildSettingsRecord, settings.guild_id)
        if record is None:
            record = GuildSettingsRecord(guild_id=settings.guild_id)
            self.session.add(record)
        record.enabled = settings.enabled
        record.allowed_channel_ids = settings.allowed_channel_ids
        record.retention_days = settings.retention_days
        return settings

    async def delete_data(self, guild_id: str) -> None:
        topic_ids = select(TopicRecord.id).where(TopicRecord.guild_id == guild_id)
        message_ids = select(MessageRecord.id).where(MessageRecord.guild_id == guild_id)
        await self.session.execute(
            delete(ProcessingJobRecord).where(ProcessingJobRecord.guild_id == guild_id)
        )
        await self.session.execute(
            delete(DiscordActionRecord).where(DiscordActionRecord.guild_id == guild_id)
        )
        await self.session.execute(
            delete(TopicSummaryRecord).where(TopicSummaryRecord.guild_id == guild_id)
        )
        await self.session.execute(delete(EpisodeRecord).where(EpisodeRecord.guild_id == guild_id))
        await self.session.execute(
            delete(MessageTopicAssociationRecord).where(
                MessageTopicAssociationRecord.guild_id == guild_id
            )
        )
        await self.session.execute(
            delete(AIDecisionRecord).where(AIDecisionRecord.guild_id == guild_id)
        )
        await self.session.execute(delete(TopicRecord).where(TopicRecord.id.in_(topic_ids)))
        await self.session.execute(delete(MessageRecord).where(MessageRecord.id.in_(message_ids)))
        await self.session.execute(
            delete(GuildSettingsRecord).where(GuildSettingsRecord.guild_id == guild_id)
        )
        await self.session.execute(
            delete(ModelConfigRecord).where(ModelConfigRecord.guild_id == guild_id)
        )
