from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import and_, case, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from backend.application.read_models import ActionReadModel, ActionState, ClaimedAction
from backend.domain.enums import ActionStatus, ActionType
from backend.infrastructure.database.models import DiscordActionRecord, TopicRecord
from backend.infrastructure.database.notifications import ACTIONS_CHANNEL, notify_transaction


class ActionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _topic_discord_context(
        self, topic_ids: set[str]
    ) -> tuple[dict[str, str | None], dict[str, str | None]]:
        if not topic_ids:
            return {}, {}
        topics = await self.session.scalars(
            select(TopicRecord).where(TopicRecord.id.in_(topic_ids))
        )
        thread_ids: dict[str, str | None] = {topic.id: topic.discord_thread_id for topic in topics}
        summary_actions = await self.session.scalars(
            select(DiscordActionRecord)
            .where(
                DiscordActionRecord.topic_id.in_(topic_ids),
                DiscordActionRecord.action_type == ActionType.UPSERT_SUMMARY.value,
                DiscordActionRecord.status == ActionStatus.SUCCEEDED.value,
                DiscordActionRecord.discord_message_id.is_not(None),
            )
            .order_by(
                DiscordActionRecord.completed_at.desc(),
                DiscordActionRecord.created_at.desc(),
                DiscordActionRecord.id.desc(),
            )
        )
        summary_message_ids: dict[str, str | None] = {}
        for action in summary_actions:
            if action.topic_id not in summary_message_ids:
                summary_message_ids[action.topic_id] = action.discord_message_id
        return thread_ids, summary_message_ids

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
        if record is None:
            return None
        thread_ids, summary_ids = await self._topic_discord_context({record.topic_id})
        return _action_read_model(
            record,
            discord_thread_id=record.discord_thread_id or thread_ids.get(record.topic_id),
            discord_summary_message_id=summary_ids.get(record.topic_id),
        )

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
        thread_ids, summary_ids = await self._topic_discord_context({record.topic_id})
        return _action_read_model(
            record,
            discord_thread_id=record.discord_thread_id or thread_ids.get(record.topic_id),
            discord_summary_message_id=summary_ids.get(record.topic_id),
        )

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
        if action_type == ActionType.UPSERT_SUMMARY:
            await self.session.execute(
                update(DiscordActionRecord)
                .execution_options(synchronize_session=False)
                .where(
                    DiscordActionRecord.guild_id == guild_id,
                    DiscordActionRecord.topic_id == topic_id,
                    DiscordActionRecord.action_type == ActionType.UPSERT_SUMMARY.value,
                    DiscordActionRecord.status == ActionStatus.PENDING.value,
                    DiscordActionRecord.superseded.is_(False),
                )
                .values(
                    status=ActionStatus.CANCELLED.value,
                    superseded=True,
                    error_type="SupersededByNewerSummary",
                )
            )
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
        if not records:
            return []
        thread_ids, summary_ids = await self._topic_discord_context(
            {record.topic_id for record in records}
        )
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
                discord_thread_id=record.discord_thread_id or thread_ids.get(record.topic_id),
                discord_summary_message_id=summary_ids.get(record.topic_id),
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
            .with_for_update(skip_locked=True)
        )
        ids = list((await self.session.scalars(eligible)).all())
        if not ids:
            return []
        tokens = {action_id: uuid4().hex for action_id in ids}
        lease_token_expr: object = (
            tokens[ids[0]] if len(ids) == 1 else case(tokens, value=DiscordActionRecord.id)
        )
        await self.session.execute(
            update(DiscordActionRecord)
            .execution_options(synchronize_session=False)
            .where(DiscordActionRecord.id.in_(ids), expired)
            .values(
                status=ActionStatus.CLAIMED,
                lease_owner=owner,
                lease_token=lease_token_expr,
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
                DiscordActionRecord.lease_token.in_(list(tokens.values())),
            )
            .order_by(DiscordActionRecord.created_at, DiscordActionRecord.id)
            .execution_options(populate_existing=True)
        )
        return [record for record in result if record.lease_token == tokens.get(record.id)]

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
            error_type=record.error_type,
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


def _action_read_model(
    record: DiscordActionRecord,
    *,
    discord_thread_id: str | None = None,
    discord_summary_message_id: str | None = None,
) -> ActionReadModel:
    return ActionReadModel(
        id=record.id,
        guild_id=record.guild_id,
        channel_id=record.channel_id,
        topic_id=record.topic_id,
        action_type=record.action_type,
        status=record.status,
        payload=record.payload,
        dependency_id=record.dependency_id,
        discord_thread_id=discord_thread_id,
        discord_summary_message_id=discord_summary_message_id,
    )
