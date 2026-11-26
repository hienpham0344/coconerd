"""Guild-scoped administrative read models, separate from write/fencing operations."""

from datetime import UTC, datetime

from sqlalchemy import and_, or_, select

from backend.application.errors import NotFound
from backend.infrastructure.database.models import (
    AIDecisionRecord,
    DiscordActionRecord,
    MessageRecord,
    MessageTopicAssociationRecord,
    ProcessingJobRecord,
    ReviewEventRecord,
    TopicRecord,
)


async def message_state(session, guild_id: str, message_id: str) -> dict:
    association = await session.scalar(
        select(MessageTopicAssociationRecord)
        .where(
            MessageTopicAssociationRecord.guild_id == guild_id,
            MessageTopicAssociationRecord.message_record_id == message_id,
        )
        .execution_options(populate_existing=True)
    )
    job = await session.scalar(
        select(ProcessingJobRecord).where(
            ProcessingJobRecord.guild_id == guild_id,
            ProcessingJobRecord.message_record_id == message_id,
        )
    )
    decision = await session.scalar(
        select(AIDecisionRecord)
        .where(
            AIDecisionRecord.guild_id == guild_id,
            AIDecisionRecord.message_record_id == message_id,
        )
        .order_by(AIDecisionRecord.created_at.desc(), AIDecisionRecord.id)
        .limit(1)
    )
    event = await session.scalar(
        select(ReviewEventRecord)
        .where(
            ReviewEventRecord.guild_id == guild_id,
            ReviewEventRecord.message_record_id == message_id,
        )
        .order_by(ReviewEventRecord.created_at.desc(), ReviewEventRecord.id)
        .limit(1)
    )
    return {
        "revision": association.revision if association else 0,
        "topic_id": association.topic_id if association else None,
        "kind": association.kind if association else None,
        "job": {
            "status": job.status,
            "model_call_count": job.model_call_count,
            "attempt_count": job.attempt_count,
            "error_type": job.error_type,
        }
        if job
        else None,
        "latest_decision": decision.payload if decision else None,
        "latest_correction": {
            "request_id": event.request_id,
            "actor": event.actor,
            "reason": event.reason,
            "result": event.result,
        }
        if event
        else None,
    }


async def sync_state(session, guild_id: str, topic_id: str, limit: int, offset: int) -> dict:
    topic = await session.scalar(
        select(TopicRecord).where(
            TopicRecord.id == topic_id,
            TopicRecord.guild_id == guild_id,
        )
    )
    if topic is None:
        raise NotFound("Topic not found")
    actions = await session.scalars(
        select(DiscordActionRecord)
        .where(
            DiscordActionRecord.guild_id == guild_id,
            DiscordActionRecord.topic_id == topic_id,
        )
        .order_by(DiscordActionRecord.created_at, DiscordActionRecord.id)
        .limit(limit)
        .offset(offset)
    )
    return {
        "topic_id": topic_id,
        "version": topic.version,
        "sync_paused": topic.sync_paused,
        "discord_thread_id": topic.discord_thread_id,
        "limit": limit,
        "offset": offset,
        "actions": [
            {
                "action_id": a.id,
                "type": a.action_type,
                "status": a.status,
                "attempt_count": a.attempt_count,
                "error_type": a.error_type,
                "superseded": a.superseded,
                "discord_message_id": a.discord_message_id,
                "discord_thread_id": a.discord_thread_id,
                "payload": a.payload,
            }
            for a in actions
        ],
    }


async def review_queue(session, guild_id: str, limit: int = 50) -> dict:
    now = datetime.now(UTC)
    message_rows = await session.execute(
        select(MessageRecord, MessageTopicAssociationRecord, ProcessingJobRecord)
        .outerjoin(
            MessageTopicAssociationRecord,
            and_(
                MessageTopicAssociationRecord.guild_id == MessageRecord.guild_id,
                MessageTopicAssociationRecord.message_record_id == MessageRecord.id,
            ),
        )
        .outerjoin(
            ProcessingJobRecord,
            and_(
                ProcessingJobRecord.guild_id == MessageRecord.guild_id,
                ProcessingJobRecord.message_record_id == MessageRecord.id,
            ),
        )
        .where(
            MessageRecord.guild_id == guild_id,
            or_(
                MessageTopicAssociationRecord.kind == "DEFERRED",
                ProcessingJobRecord.status.in_(["WAITING", "DEAD"]),
            ),
        )
        .order_by(MessageRecord.created_at.desc(), MessageRecord.id.desc())
        .limit(limit)
    )
    deferred_messages = [
        {
            "message_id": message.discord_message_id,
            "channel_id": message.channel_id,
            "author_id": message.author_id,
            "author_name": message.author_name,
            "content": message.content,
            "created_at": message.created_at,
            "topic_id": assoc.topic_id if assoc else None,
            "kind": assoc.kind if assoc else None,
            "revision": assoc.revision if assoc else 0,
            "confidence": assoc.confidence if assoc else None,
            "reason": assoc.reason if assoc else "",
            "job_status": job.status if job else None,
            "attempt_count": job.attempt_count if job else 0,
            "error_type": job.error_type if job else None,
        }
        for message, assoc, job in message_rows
    ]
    dead_action_rows = await session.scalars(
        select(DiscordActionRecord)
        .where(
            DiscordActionRecord.guild_id == guild_id,
            DiscordActionRecord.superseded.is_(False),
            or_(
                DiscordActionRecord.status == "DEAD",
                and_(
                    DiscordActionRecord.status == "CLAIMED",
                    DiscordActionRecord.lease_expires_at <= now,
                ),
            ),
        )
        .order_by(DiscordActionRecord.created_at.desc(), DiscordActionRecord.id.desc())
        .limit(limit)
    )
    dead_actions = [
        {
            "action_id": a.id,
            "topic_id": a.topic_id,
            "channel_id": a.channel_id,
            "type": a.action_type,
            "action_type": a.action_type,
            "status": a.status,
            "attempt_count": a.attempt_count,
            "max_attempts": a.max_attempts,
            "error_type": a.error_type,
            "error_message": a.error_message,
            "superseded": a.superseded,
            "discord_thread_id": a.discord_thread_id,
            "discord_message_id": a.discord_message_id,
            "payload": a.payload,
            "created_at": a.created_at,
        }
        for a in dead_action_rows
    ]
    event_rows = await session.scalars(
        select(ReviewEventRecord)
        .where(ReviewEventRecord.guild_id == guild_id)
        .order_by(ReviewEventRecord.created_at.desc(), ReviewEventRecord.id.desc())
        .limit(limit)
    )
    recent_events = [
        {
            "event_id": e.id,
            "request_id": e.request_id,
            "operation": e.operation,
            "resource_id": e.resource_id,
            "actor": e.actor,
            "reason": e.reason,
            "result": e.result,
            "topic_id": e.topic_id,
            "created_at": e.created_at,
        }
        for e in event_rows
    ]
    return {
        "guild_id": guild_id,
        "deferred_messages": deferred_messages,
        "dead_actions": dead_actions,
        "recent_events": recent_events,
    }
