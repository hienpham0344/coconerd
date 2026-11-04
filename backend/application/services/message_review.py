"""Review and correct assignments without invoking a model or rewriting source messages."""

from backend.application.errors import Conflict, InvalidTransition, NotFound
from backend.application.ports.persistence import UnitOfWork
from backend.application.review_contracts import CorrectMessage
from backend.application.services.review_audit import record, replay


async def review_message(uow: UnitOfWork, guild_id: str, discord_id: str) -> dict:
    message = await uow.messages.get_by_discord_id(guild_id, discord_id)
    if message is None:
        raise NotFound("Message not found")
    state = await uow.reviews.message_state(guild_id, message.id)
    return {"message_id": discord_id, "content": message.content, **state}


async def correct_message(
    uow: UnitOfWork, guild_id: str, discord_id: str, command: CorrectMessage
) -> dict:
    fingerprint, saved = await replay(uow, guild_id, "correct_message", discord_id, command)
    if saved is not None:
        return saved
    message = await uow.messages.get_by_discord_id(guild_id, discord_id)
    if message is None:
        raise NotFound("Message not found")
    state = await uow.reviews.message_state(guild_id, message.id)
    if state["revision"] != command.expected_revision:
        raise Conflict("Message association changed; reload its review")
    affected = sorted({t for t in [state["topic_id"], command.target_topic_id] if t})
    topics = {}
    for topic_id in affected:
        topic = await uow.topics.get(guild_id, topic_id)
        if topic is None:
            raise NotFound("Topic not found")
        if topic_id == command.target_topic_id and topic.status == "CLOSED":
            raise Conflict("Cannot assign to a closed topic")
        topics[topic_id] = topic
    snapshots = {s.topic_id: s for s in command.summaries}
    if set(snapshots) != set(affected) or len(snapshots) != len(command.summaries):
        raise InvalidTransition("Provide exactly one reviewed summary per affected topic")
    try:
        # Fence processing before changing the association; stale workers then cannot commit.
        await uow.reviews.finish_job(guild_id, message.id)
        for topic_id in affected:
            await uow.reviews.fence_topic(
                guild_id, topic_id, snapshots[topic_id].expected_version, True
            )
        await uow.reviews.reassign(
            guild_id, message.id, command.expected_revision, command.target_topic_id, command.reason
        )
        cancelled = await uow.reviews.cancel_actions(guild_id, affected)
        for topic_id in affected:
            snapshot = snapshots[topic_id]
            if not await uow.reviews.valid_sources(guild_id, topic_id, snapshot.source_message_ids):
                raise InvalidTransition("Summary sources must belong to the corrected topic")
            previous = await uow.summaries.latest(guild_id, topic_id)
            await uow.summaries.add(
                guild_id,
                topic_id,
                previous.version + 1 if previous else 1,
                snapshot.memory(topics[topic_id].title),
                snapshot.source_message_ids,
            )
        await uow.messages.add_decision(
            guild_id,
            message.id,
            "manual",
            "human",
            {
                "actor": command.actor,
                "reason": command.reason,
                "request_id": command.request_id,
                "previous_topic_id": state["topic_id"],
                "topic_id": command.target_topic_id,
            },
        )
        result = {
            "message_id": discord_id,
            "revision": command.expected_revision + 1,
            "topic_id": command.target_topic_id,
            "sync_paused_topic_ids": affected,
            "cancelled_action_ids": cancelled,
            "reconciliation_required": bool(affected),
        }
        return await record(
            uow,
            guild_id,
            "correct_message",
            discord_id,
            command,
            fingerprint,
            result,
            message_record_id=message.id,
        )
    except Exception:
        await uow.rollback()
        raise
