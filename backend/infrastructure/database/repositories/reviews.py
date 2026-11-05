"""Atomic persistence for moderator corrections and their audit trail."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from backend.application.errors import Conflict
from backend.infrastructure.database.models import (
    DiscordActionRecord,
    MessageRecord,
    MessageTopicAssociationRecord,
    ProcessingJobRecord,
    ReviewEventRecord,
    TopicRecord,
)
from backend.infrastructure.database.repositories import review_queries
from backend.infrastructure.database.repositories.action_recovery import recover_action
from backend.infrastructure.database.statements import conflict_insert


class ReviewRepository:
    def __init__(self, session):
        self.session = session

    async def event(self, guild_id, request_id):
        event = await self.session.scalar(
            select(ReviewEventRecord).where(
                ReviewEventRecord.guild_id == guild_id,
                ReviewEventRecord.request_id == request_id,
            )
        )
        return {"fingerprint": event.fingerprint, "result": event.result} if event else None

    async def add_event(
        self,
        guild_id,
        request_id,
        fingerprint,
        operation,
        resource_id,
        actor,
        reason,
        result,
        message_record_id=None,
        topic_id=None,
    ):
        self.session.add(
            ReviewEventRecord(
                id=str(uuid4()),
                guild_id=guild_id,
                request_id=request_id,
                fingerprint=fingerprint,
                operation=operation,
                resource_id=resource_id,
                actor=actor,
                reason=reason,
                result=result,
                message_record_id=message_record_id,
                topic_id=topic_id,
            )
        )
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise Conflict(
                "Concurrent review request; reload and retry the same request_id"
            ) from exc

    async def message_state(self, guild_id, message_record_id):
        return await review_queries.message_state(self.session, guild_id, message_record_id)

    async def sync_state(self, guild_id, topic_id, limit, offset):
        return await review_queries.sync_state(self.session, guild_id, topic_id, limit, offset)

    async def finish_job(self, guild_id, message_record_id):
        # An UPDATE is the transaction's write fence; a later worker complete cannot pass it.
        changed = await self.session.execute(
            update(ProcessingJobRecord)
            .where(
                ProcessingJobRecord.guild_id == guild_id,
                ProcessingJobRecord.message_record_id == message_record_id,
                or_(
                    ProcessingJobRecord.status != "CLAIMED",
                    ProcessingJobRecord.lease_expires_at <= datetime.now(UTC),
                ),
            )
            .values(
                status="SUCCEEDED",
                lease_owner=None,
                lease_expires_at=None,
                deferred_until=None,
                error_type=None,
            )
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            raise Conflict("Message processing is active or its job is missing")

    async def reassign(self, guild_id, message_record_id, expected_revision, topic_id, reason):
        values = dict(
            topic_id=topic_id,
            kind="MANUAL",
            confidence=1.0,
            reason=reason,
            revision=expected_revision + 1,
        )
        if expected_revision == 0:
            statement = (
                conflict_insert(self.session, MessageTopicAssociationRecord)
                .values(
                    id=str(uuid4()),
                    guild_id=guild_id,
                    message_record_id=message_record_id,
                    **values,
                )
                .on_conflict_do_nothing(index_elements=["guild_id", "message_record_id"])
            )
        else:
            statement = (
                update(MessageTopicAssociationRecord)
                .where(
                    MessageTopicAssociationRecord.guild_id == guild_id,
                    MessageTopicAssociationRecord.message_record_id == message_record_id,
                    MessageTopicAssociationRecord.revision == expected_revision,
                )
                .values(**values)
                .execution_options(synchronize_session=False)
            )
        if (await self.session.execute(statement)).rowcount != 1:
            raise Conflict("Message association changed concurrently")

    async def fence_topic(self, guild_id, topic_id, version, paused, thread_id=None):
        values = dict(version=version + 1, sync_paused=paused)
        if thread_id is not None:
            values["discord_thread_id"] = thread_id
        try:
            changed = await self.session.execute(
                update(TopicRecord)
                .where(
                    TopicRecord.guild_id == guild_id,
                    TopicRecord.id == topic_id,
                    TopicRecord.version == version,
                )
                .values(**values)
                .execution_options(synchronize_session=False)
            )
        except IntegrityError as exc:
            raise Conflict("Discord thread is already mapped to another topic") from exc
        if changed.rowcount != 1:
            raise Conflict("Topic changed; reload its version and summary")

    async def cancel_actions(self, guild_id, topic_ids):
        if not topic_ids:
            return []
        scope = (
            DiscordActionRecord.guild_id == guild_id,
            DiscordActionRecord.topic_id.in_(topic_ids),
        )
        claimed = await self.session.scalar(
            select(DiscordActionRecord.id)
            .where(
                *scope,
                DiscordActionRecord.status == "CLAIMED",
            )
            .limit(1)
        )
        if claimed:
            raise Conflict("Resolve claimed Discord actions before correcting the topic")
        # Preserve sent actions and attempted DEAD actions as external-effect evidence.
        ids = list(
            await self.session.scalars(
                select(DiscordActionRecord.id)
                .where(
                    *scope,
                    DiscordActionRecord.status == "PENDING",
                )
                .order_by(DiscordActionRecord.id)
            )
        )
        await self.session.execute(
            update(DiscordActionRecord)
            .where(
                *scope,
                DiscordActionRecord.status == "PENDING",
            )
            .values(
                status="CANCELLED",
                error_type="ManualCorrection",
                lease_owner=None,
                lease_expires_at=None,
            )
            .execution_options(synchronize_session=False)
        )
        await self.session.execute(
            update(DiscordActionRecord)
            .where(
                *scope,
                DiscordActionRecord.status.in_(["DEAD", "CANCELLED"]),
            )
            .values(superseded=True)
            .execution_options(synchronize_session=False)
        )
        return ids

    async def valid_sources(self, guild_id, topic_id, source_ids):
        if not source_ids:
            return True
        found = await self.session.scalars(
            select(MessageRecord.discord_message_id)
            .join(MessageTopicAssociationRecord)
            .where(
                MessageRecord.guild_id == guild_id,
                MessageRecord.discord_message_id.in_(source_ids),
                MessageTopicAssociationRecord.guild_id == guild_id,
                MessageTopicAssociationRecord.topic_id == topic_id,
            )
        )
        return set(found) == set(source_ids)

    async def recover_action(self, guild_id, action_id, command):
        return await recover_action(self.session, guild_id, action_id, command)
