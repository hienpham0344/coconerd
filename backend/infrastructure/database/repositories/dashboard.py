"""Administrative dashboard read models and encrypted, expiring credentials."""

from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update

from backend.infrastructure.database.models import (
    DashboardCredentialRecord,
    GuildSettingsRecord,
    MessageRecord,
    MessageTopicAssociationRecord,
    TopicRecord,
)
from backend.infrastructure.database.statements import conflict_insert


class DashboardRepository:
    def __init__(self, session):
        self.session = session

    @staticmethod
    def guild_data(record):
        return {
            key: getattr(record, key)
            for key in (
                "guild_id",
                "enabled",
                "allowed_channel_ids",
                "output_channel_id",
                "retention_days",
            )
        }

    async def guilds(self, limit, offset):
        records = await self.session.scalars(
            select(GuildSettingsRecord)
            .order_by(GuildSettingsRecord.guild_id)
            .limit(limit)
            .offset(offset)
        )
        return [self.guild_data(record) for record in records]

    async def settings(self, guild_id):
        record = await self.session.get(GuildSettingsRecord, guild_id)
        return self.guild_data(record) if record else None

    async def overview(self, guild_id, guild):
        async def count(model, *conditions):
            return await self.session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.guild_id == guild_id, *conditions)
            )

        return {
            "topics": await count(TopicRecord),
            "active_topics": await count(
                TopicRecord, TopicRecord.status.in_(["ACTIVE", "RESUMED"])
            ),
            "messages": await count(MessageRecord),
            "channels": len(guild["allowed_channel_ids"]),
        }

    async def topics(self, guild_id, query, status, limit, offset):
        filters = [TopicRecord.guild_id == guild_id]
        if status:
            filters.append(TopicRecord.status == status)
        if query.strip():
            escaped = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            filters.append(TopicRecord.title.ilike(f"%{escaped}%", escape="\\"))
        total = await self.session.scalar(
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
        rows = await self.session.execute(
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

    async def save_credential(self, kind, key, payload, expires_at, expected_payload=None):
        if expected_payload is not None:
            changed = await self.session.scalar(
                update(DashboardCredentialRecord)
                .where(
                    DashboardCredentialRecord.kind == kind,
                    DashboardCredentialRecord.key_hash == key,
                    DashboardCredentialRecord.payload == expected_payload,
                    DashboardCredentialRecord.expires_at > datetime.now(UTC),
                )
                .values(payload=payload, expires_at=expires_at)
                .returning(DashboardCredentialRecord.key_hash)
            )
            await self.session.commit()
            return changed is not None
        await self.session.execute(
            delete(DashboardCredentialRecord).where(
                DashboardCredentialRecord.expires_at <= datetime.now(UTC)
            )
        )
        await self.session.execute(
            conflict_insert(self.session, DashboardCredentialRecord)
            .values(kind=kind, key_hash=key, payload=payload, expires_at=expires_at)
            .on_conflict_do_update(
                index_elements=["kind", "key_hash"],
                set_={
                    "payload": payload,
                    "expires_at": expires_at,
                },
            )
        )
        await self.session.commit()
        return True

    @staticmethod
    def credential_data(payload, expires_at):
        # SQLite returns naive UTC values; serialize an explicit offset for Node clients.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return {"payload": payload, "expires_at": expires_at}

    async def credential(self, kind, key, consume=False):
        conditions = (
            DashboardCredentialRecord.kind == kind,
            DashboardCredentialRecord.key_hash == key,
            DashboardCredentialRecord.expires_at > datetime.now(UTC),
        )
        if consume:
            result = await self.session.execute(
                delete(DashboardCredentialRecord)
                .where(*conditions)
                .returning(DashboardCredentialRecord.payload, DashboardCredentialRecord.expires_at)
            )
            row = result.mappings().first()
            await self.session.commit()
            return self.credential_data(row["payload"], row["expires_at"]) if row else None
        record = await self.session.scalar(select(DashboardCredentialRecord).where(*conditions))
        return self.credential_data(record.payload, record.expires_at) if record else None

    async def delete_credential(self, kind, key):
        await self.session.execute(
            delete(DashboardCredentialRecord).where(
                DashboardCredentialRecord.kind == kind, DashboardCredentialRecord.key_hash == key
            )
        )
        await self.session.commit()
