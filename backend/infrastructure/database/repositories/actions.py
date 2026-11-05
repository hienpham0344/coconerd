from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from backend.application.read_models import ActionReadModel, ActionState, ClaimedAction
from backend.domain.enums import ActionStatus, ActionType
from backend.infrastructure.database.models import DiscordActionRecord, TopicRecord
from backend.infrastructure.database.notifications import ACTIONS_CHANNEL, notify_transaction


class ActionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def pending_create(self, guild_id: str, topic_id: str) -> ActionReadModel | None:
        record = await self.session.scalar(
            select(DiscordActionRecord)
            .where(
                DiscordActionRecord.guild_id == guild_id,
                DiscordActionRecord.topic_id == topic_id,
                DiscordActionRecord.action_type == ActionType.CREATE_THREAD.value,
                DiscordActionRecord.status.in_(["PENDING", "CLAIMED", "DEAD"]),
                DiscordActionRecord.superseded.is_(False),
            )
            .order_by(DiscordActionRecord.created_at)
            .limit(1)
        )
        return _action_read_model(record) if record is not None else None

    async def add_read_model(
        self,
        guild_id: str,
        channel_id: str,
        topic_id: str,
        action_type: ActionType,
        payload: dict[str, object],
        dependency_id: str | None = None,
        max_attempts: int = 5,
    ) -> ActionReadModel:
        record = await self.add(
            guild_id, channel_id, topic_id, action_type, payload, dependency_id, max_attempts
        )
        return _action_read_model(record)

    async def add(
        self,
        guild_id: str,
        channel_id: str,
        topic_id: str,
        action_type: ActionType,
        payload: dict[str, object],
        dependency_id: str | None = None,
        max_attempts: int = 5,
    ) -> DiscordActionRecord:
        record = DiscordActionRecord(
            id=str(uuid4()),
            guild_id=guild_id,
            channel_id=channel_id,
            topic_id=topic_id,
            action_type=action_type.value,
            payload=payload,
            dependency_id=dependency_id,
            max_attempts=max_attempts,
        )
        self.session.add(record)
        await notify_transaction(self.session, ACTIONS_CHANNEL)
        return record

    async def claim_available(
        self, owner: str, limit: int, now: datetime, lease_expires_at: datetime
    ) -> list[ClaimedAction]:
        records = await self._claim(owner, limit, now, lease_expires_at)
        return [
            ClaimedAction(
                id=record.id,
                guild_id=record.guild_id,
                channel_id=record.channel_id,
                topic_id=record.topic_id,
                action_type=record.action_type,
                status=record.status,
                payload=record.payload,
                dependency_id=record.dependency_id,
                lease_token=record.lease_token,
            )
            for record in records
        ]

    async def _claim(
        self, owner: str, limit: int, now: datetime, lease_expires_at: datetime
    ) -> list[DiscordActionRecord]:
        expired = or_(
            DiscordActionRecord.status == ActionStatus.PENDING,
            and_(
                DiscordActionRecord.status == ActionStatus.CLAIMED,
                DiscordActionRecord.lease_expires_at <= now,
            ),
        )
        await self.session.execute(
            update(DiscordActionRecord)
            .execution_options(synchronize_session=False)
            .where(expired, DiscordActionRecord.attempt_count >= DiscordActionRecord.max_attempts)
            .values(
                status="DEAD",
                lease_owner=None,
                lease_expires_at=None,
                error_type="LeaseAttemptsExhausted",
            )
        )
        await self.session.execute(
            update(DiscordActionRecord)
            .execution_options(synchronize_session=False)
            .where(
                expired,
                DiscordActionRecord.dependency_id.in_(
                    select(DiscordActionRecord.id).where(DiscordActionRecord.status == "DEAD")
                ),
            )
            .values(
                status="DEAD",
                lease_owner=None,
                lease_expires_at=None,
                error_type="DependencyFailed",
            )
        )
        predecessor = aliased(DiscordActionRecord, name="predecessor")
        # Serialize a topic's effects, including a predecessor waiting for backoff.
        # Separate topics remain claimable in the same batch. The ID breaks timestamp ties.
        blocked_by_topic = (
            select(predecessor.id)
            .where(
                predecessor.guild_id == DiscordActionRecord.guild_id,
                predecessor.topic_id == DiscordActionRecord.topic_id,
                predecessor.superseded.is_(False),
                predecessor.id != DiscordActionRecord.id,
                predecessor.status.in_(["PENDING", "CLAIMED"]),
                or_(
                    predecessor.created_at < DiscordActionRecord.created_at,
                    and_(
                        predecessor.created_at == DiscordActionRecord.created_at,
                        predecessor.id < DiscordActionRecord.id,
                    ),
                    and_(
                        predecessor.status == "CLAIMED",
                        predecessor.lease_expires_at > now,
                    ),
                ),
            )
            .exists()
        )
        eligible = (
            select(DiscordActionRecord.id)
            .where(
                expired,
                DiscordActionRecord.superseded.is_(False),
                DiscordActionRecord.topic_id.in_(
                    select(TopicRecord.id).where(TopicRecord.sync_paused.is_(False))
                ),
                DiscordActionRecord.available_at <= now,
                DiscordActionRecord.attempt_count < DiscordActionRecord.max_attempts,
                ~blocked_by_topic,
                or_(
                    DiscordActionRecord.dependency_id.is_(None),
                    DiscordActionRecord.dependency_id.in_(
                        select(DiscordActionRecord.id).where(
                            DiscordActionRecord.status == ActionStatus.SUCCEEDED
                        )
                    ),
                ),
            )
            .order_by(DiscordActionRecord.created_at, DiscordActionRecord.id)
            .limit(limit)
        )
        ids = list((await self.session.scalars(eligible)).all())
        if not ids:
            return []
        lease_token = uuid4().hex
        await self.session.execute(
            update(DiscordActionRecord)
            .execution_options(synchronize_session=False)
            .where(DiscordActionRecord.id.in_(ids), expired)
            .values(
                status=ActionStatus.CLAIMED,
                lease_owner=owner,
                lease_token=lease_token,
                lease_expires_at=lease_expires_at,
                attempt_count=DiscordActionRecord.attempt_count + 1,
            )
        )
        result = await self.session.scalars(
            select(DiscordActionRecord)
            .where(
                DiscordActionRecord.id.in_(ids),
                DiscordActionRecord.status == ActionStatus.CLAIMED,
                DiscordActionRecord.lease_owner == owner,
                DiscordActionRecord.lease_token == lease_token,
            )
            .execution_options(populate_existing=True)
        )
        return list(result)

    async def get(self, action_id: str) -> ActionState | None:
        record = await self.session.get(DiscordActionRecord, action_id)
        if record is None:
            return None
        return ActionState(
            id=record.id,
            guild_id=record.guild_id,
            channel_id=record.channel_id,
            topic_id=record.topic_id,
            action_type=record.action_type,
            status=record.status,
            payload=record.payload,
            dependency_id=record.dependency_id,
            lease_owner=record.lease_owner,
            attempt_count=record.attempt_count,
            max_attempts=record.max_attempts,
            discord_thread_id=record.discord_thread_id,
            discord_message_id=record.discord_message_id,
            lease_token=record.lease_token,
        )

    async def update(self, action_id: str, **changes: object) -> None:
        await self.session.execute(
            update(DiscordActionRecord).where(DiscordActionRecord.id == action_id).values(**changes)
        )

    async def update_leased(
        self, action_id: str, owner: str, *, lease_token: str | None = None, **changes: object
    ) -> bool:
        changed = await self.session.execute(
            update(DiscordActionRecord)
            .execution_options(synchronize_session=False)
            .where(
                DiscordActionRecord.id == action_id,
                DiscordActionRecord.status == "CLAIMED",
                DiscordActionRecord.lease_owner == owner,
                DiscordActionRecord.lease_expires_at > datetime.now(UTC),
                DiscordActionRecord.lease_token == lease_token,
            )
            .values(**changes)
        )
        return changed.rowcount == 1


def _action_read_model(record: DiscordActionRecord) -> ActionReadModel:
    return ActionReadModel(
        id=record.id,
        guild_id=record.guild_id,
        channel_id=record.channel_id,
        topic_id=record.topic_id,
        action_type=record.action_type,
        status=record.status,
        payload=record.payload,
        dependency_id=record.dependency_id,
    )
