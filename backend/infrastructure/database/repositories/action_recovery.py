"""Explicit administrator recovery; never automatically replay an uncertain side effect."""

from datetime import UTC, datetime

from sqlalchemy import and_, or_, select, update

from backend.application.errors import Conflict, InvalidTransition, NotFound
from backend.infrastructure.database.models import DiscordActionRecord, TopicRecord


async def recover_action(session, guild_id, action_id, command):
    action = await session.scalar(
        select(DiscordActionRecord).where(
            DiscordActionRecord.id == action_id,
            DiscordActionRecord.guild_id == guild_id,
        )
    )
    if action is None:
        raise NotFound("Action not found")
    topic = await session.scalar(
        select(TopicRecord).where(
            TopicRecord.id == action.topic_id,
            TopicRecord.guild_id == guild_id,
        )
    )
    if topic is None or topic.sync_paused:
        raise Conflict("Reconcile the paused topic before recovering an action")
    # A correction invalidates old actions even after synchronization resumes.
    if action.superseded:
        raise Conflict("Superseded actions cannot be replayed")
    now = datetime.now(UTC)
    performed = command.resolution == "performed"
    if performed and action.action_type == "CREATE_THREAD" and not command.discord_thread_id:
        raise InvalidTransition("Performed CREATE_THREAD requires discord_thread_id")
    if (
        performed
        and action.action_type in {"APPEND_MESSAGE", "UPSERT_SUMMARY"}
        and not command.discord_message_id
    ):
        raise InvalidTransition("Performed message action requires discord_message_id")
    if not performed and (command.discord_thread_id or command.discord_message_id):
        raise InvalidTransition("not_performed must not contain Discord result IDs")
    values = dict(
        status="SUCCEEDED" if performed else "PENDING",
        lease_owner=None,
        lease_expires_at=None,
        error_type=None,
        error_message=None,
        available_at=now,
    )
    if performed:
        values.update(
            discord_thread_id=command.discord_thread_id,
            discord_message_id=command.discord_message_id,
            completed_at=now,
        )
    else:
        values["max_attempts"] = max(action.max_attempts, action.attempt_count + 1)
    changed = await session.execute(
        update(DiscordActionRecord)
        .where(
            DiscordActionRecord.id == action_id,
            DiscordActionRecord.guild_id == guild_id,
            DiscordActionRecord.attempt_count == command.expected_attempt_count,
            DiscordActionRecord.superseded.is_(False),
            or_(
                DiscordActionRecord.status == "DEAD",
                and_(
                    DiscordActionRecord.status == "CLAIMED",
                    DiscordActionRecord.lease_expires_at <= now,
                ),
            ),
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        raise Conflict("Action is active, cancelled, completed, or changed since review")
    if performed and action.action_type == "CREATE_THREAD":
        if topic.discord_thread_id and topic.discord_thread_id != command.discord_thread_id:
            raise Conflict("Topic already maps to another Discord thread")
        duplicate = await session.scalar(
            select(TopicRecord.id).where(
                TopicRecord.discord_thread_id == command.discord_thread_id,
                TopicRecord.id != topic.id,
            )
        )
        if duplicate:
            raise Conflict("Discord thread is already mapped")
        await session.execute(
            update(TopicRecord)
            .where(TopicRecord.id == topic.id)
            .values(discord_thread_id=command.discord_thread_id)
        )
    await session.execute(
        update(DiscordActionRecord)
        .where(
            DiscordActionRecord.guild_id == guild_id,
            DiscordActionRecord.dependency_id == action_id,
            DiscordActionRecord.status == "DEAD",
            DiscordActionRecord.error_type == "DependencyFailed",
        )
        .values(status="PENDING", error_type=None, available_at=now)
    )
    return {
        "action_id": action_id,
        "topic_id": topic.id,
        "status": values["status"],
        "attempt_count": action.attempt_count,
    }
