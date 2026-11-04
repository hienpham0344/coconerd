"""Guild-scoped administrative read models, separate from write/fencing operations."""

from sqlalchemy import select

from backend.infrastructure.database.models import (
    AIDecisionRecord,
    DiscordActionRecord,
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
