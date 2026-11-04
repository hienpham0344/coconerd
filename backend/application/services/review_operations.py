"""Explicit reconciliation and recovery of external Discord effects."""

from backend.application.errors import Conflict, NotFound
from backend.application.ports.persistence import UnitOfWork
from backend.application.review_contracts import RecoverAction, ResumeTopicSync
from backend.application.services.review_audit import record, replay


async def topic_sync_state(
    uow: UnitOfWork, guild_id: str, topic_id: str, limit: int = 50, offset: int = 0
) -> dict:
    if await uow.topics.get(guild_id, topic_id) is None:
        raise NotFound("Topic not found")
    return await uow.reviews.sync_state(guild_id, topic_id, limit, offset)


async def resume_topic_sync(
    uow: UnitOfWork, guild_id: str, topic_id: str, command: ResumeTopicSync
) -> dict:
    fingerprint, saved = await replay(uow, guild_id, "resume_sync", topic_id, command)
    if saved is not None:
        return saved
    topic = await uow.topics.get(guild_id, topic_id)
    if topic is None:
        raise NotFound("Topic not found")
    if not topic.sync_paused:
        raise Conflict("Topic synchronization is not paused")
    try:
        await uow.reviews.fence_topic(
            guild_id, topic_id, command.expected_version, False, command.discord_thread_id
        )
        result = {
            "topic_id": topic_id,
            "sync_paused": False,
            "version": command.expected_version + 1,
        }
        return await record(
            uow, guild_id, "resume_sync", topic_id, command, fingerprint, result, topic_id=topic_id
        )
    except Exception:
        await uow.rollback()
        raise


async def recover_action(
    uow: UnitOfWork, guild_id: str, action_id: str, command: RecoverAction
) -> dict:
    fingerprint, saved = await replay(uow, guild_id, "recover_action", action_id, command)
    if saved is not None:
        return saved
    try:
        result = await uow.reviews.recover_action(guild_id, action_id, command)
        return await record(
            uow,
            guild_id,
            "recover_action",
            action_id,
            command,
            fingerprint,
            result,
            topic_id=result["topic_id"],
        )
    except Exception:
        await uow.rollback()
        raise
