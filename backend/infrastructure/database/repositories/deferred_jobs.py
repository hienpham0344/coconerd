"""One evidence-triggered reassessment per unassigned message."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import case, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.clarification import (
    DEFER_WINDOW_SECONDS,
    is_clarification,
    is_conversation_followup,
    utc,
)
from backend.infrastructure.database.models import (
    MessageRecord,
    MessageTopicAssociationRecord,
    ProcessingJobRecord,
    TopicRecord,
)
from backend.infrastructure.database.repositories.messages import _message_read_model


class DeferredJobs:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _matches(self, target: MessageRecord, followup: MessageRecord) -> bool:
        if not is_clarification(_message_read_model(target), _message_read_model(followup)):
            if not is_conversation_followup(
                _message_read_model(target), _message_read_model(followup)
            ):
                return False
            # Only a successfully assigned turn can trigger a natural follow-up.
            # Mere ingestion, repeated words and arbitrary nearby chatter cannot.
            return (
                await self.session.scalar(
                    select(MessageTopicAssociationRecord.id)
                    .join(TopicRecord, TopicRecord.id == MessageTopicAssociationRecord.topic_id)
                    .where(
                        MessageTopicAssociationRecord.guild_id == target.guild_id,
                        MessageTopicAssociationRecord.message_record_id == followup.id,
                        TopicRecord.guild_id == target.guild_id,
                        TopicRecord.status != "CLOSED",
                    )
                    .limit(1)
                )
                is not None
            )
        if followup.reply_to_message_id:
            return True
        # Without an explicit reply, do not skip a newer message or resolve timestamp ties.
        intervening = await self.session.scalar(
            select(MessageRecord.id)
            .where(
                MessageRecord.guild_id == target.guild_id,
                MessageRecord.channel_id == target.channel_id,
                MessageRecord.author_id == target.author_id,
                MessageRecord.id != target.id,
                MessageRecord.created_at >= target.created_at,
                MessageRecord.created_at < followup.created_at,
            )
            .limit(1)
        )
        return intervening is None

    async def _wake(self, job_id: str, followup_id: str) -> bool:
        changed = await self.session.execute(
            update(ProcessingJobRecord)
            .execution_options(synchronize_session=False)
            .where(
                ProcessingJobRecord.id == job_id,
                ProcessingJobRecord.status == "WAITING",
                ProcessingJobRecord.reassessment_count == 0,
                ProcessingJobRecord.model_call_count < 2,
                ProcessingJobRecord.deferred_until > datetime.now(UTC),
            )
            .values(
                status="PENDING",
                reassessment_count=1,
                attempt_count=0,
                followup_message_id=followup_id,
                available_at=datetime.now(UTC),
                lease_owner=None,
                lease_expires_at=None,
            )
        )
        return changed.rowcount == 1

    async def wait(self, job_id: str, until: datetime, *, owner: str) -> bool:
        changed = await self.session.execute(
            update(ProcessingJobRecord)
            .execution_options(synchronize_session=False)
            .where(
                ProcessingJobRecord.id == job_id,
                ProcessingJobRecord.status == "CLAIMED",
                ProcessingJobRecord.lease_owner == owner,
                ProcessingJobRecord.lease_expires_at > datetime.now(UTC),
                ProcessingJobRecord.reassessment_count == 0,
                ProcessingJobRecord.model_call_count < 2,
            )
            .values(status="WAITING", deferred_until=until, lease_owner=None, lease_expires_at=None)
        )
        if changed.rowcount != 1:
            return False
        target = await self.session.scalar(
            select(MessageRecord).join(ProcessingJobRecord).where(ProcessingJobRecord.id == job_id)
        )
        if target is not None:
            # Prefer explicit replies in a busy channel; inspect at most 30 candidates.
            following = await self.session.scalars(
                select(MessageRecord)
                .where(
                    MessageRecord.guild_id == target.guild_id,
                    MessageRecord.channel_id == target.channel_id,
                    MessageRecord.created_at > target.created_at,
                    MessageRecord.created_at
                    <= utc(target.created_at) + timedelta(seconds=DEFER_WINDOW_SECONDS),
                )
                .order_by(
                    case(
                        (MessageRecord.reply_to_message_id == target.discord_message_id, 0), else_=1
                    ),
                    MessageRecord.created_at,
                )
                .limit(30)
            )
            for followup in following:
                if await self._matches(target, followup):
                    await self._wake(job_id, followup.id)
                    break
        return True

    async def wake(self, followup_id: str) -> None:
        followup = await self.session.get(MessageRecord, followup_id)
        if followup is None or not followup.content.strip():
            return
        query = (
            select(ProcessingJobRecord.id, MessageRecord)
            .join(MessageRecord)
            .where(
                ProcessingJobRecord.status == "WAITING",
                ProcessingJobRecord.guild_id == followup.guild_id,
                MessageRecord.guild_id == followup.guild_id,
                MessageRecord.channel_id == followup.channel_id,
                ProcessingJobRecord.deferred_until > datetime.now(UTC),
                MessageRecord.created_at < followup.created_at,
                MessageRecord.created_at
                >= utc(followup.created_at) - timedelta(seconds=DEFER_WINDOW_SECONDS),
            )
        )
        if followup.reply_to_message_id:
            query = query.where(MessageRecord.discord_message_id == followup.reply_to_message_id)
        rows = await self.session.execute(query.order_by(MessageRecord.created_at.desc()).limit(30))
        woken = 0
        for job_id, target in rows:
            if await self._matches(target, followup):
                woken += await self._wake(job_id, followup_id)
                if woken == 6:
                    break
