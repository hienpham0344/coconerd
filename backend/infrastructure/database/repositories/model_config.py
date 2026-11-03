"""Passive model configuration persistence."""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.read_models import ModelConfiguration, WorkerModelConfiguration
from backend.infrastructure.database.models import ModelConfigRecord


class ModelConfigRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, scope: str, guild_id: str | None) -> ModelConfiguration | None:
        record = await self.session.scalar(
            select(ModelConfigRecord).where(
                ModelConfigRecord.scope == scope, ModelConfigRecord.guild_id == guild_id
            )
        )
        if record is None:
            return None
        return ModelConfiguration(
            record.scope,
            record.guild_id,
            record.provider,
            record.model_id,
            record.temperature,
            record.max_tokens,
        )

    async def get_for_worker(
        self, scope: str, guild_id: str | None
    ) -> WorkerModelConfiguration | None:
        record = await self.session.scalar(
            select(ModelConfigRecord).where(
                ModelConfigRecord.scope == scope, ModelConfigRecord.guild_id == guild_id
            )
        )
        if record is None:
            return None
        return WorkerModelConfiguration(
            record.scope,
            record.guild_id,
            record.provider,
            record.model_id,
            record.temperature,
            record.max_tokens,
            record.enabled,
        )

    async def save(self, config: ModelConfiguration) -> None:
        record = await self.session.scalar(
            select(ModelConfigRecord).where(
                ModelConfigRecord.scope == config.scope,
                ModelConfigRecord.guild_id == config.guild_id,
            )
        )
        if record is None:
            record = ModelConfigRecord(
                id=str(uuid4()), scope=config.scope, guild_id=config.guild_id
            )
            self.session.add(record)
        record.provider = config.provider
        record.model_id = config.model_id
        record.temperature = config.temperature
        record.max_tokens = config.max_tokens
