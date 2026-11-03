"""Retention windows and source-data redaction policy."""

from datetime import UTC, datetime, timedelta

from backend.application.ports.persistence import UnitOfWork


async def prune_retained_data(uow: UnitOfWork) -> int:
    now = datetime.now(UTC)
    removed = 0
    await uow.retention.prune_rate_limits(now - timedelta(hours=1))
    for guild in await uow.retention.guild_settings():
        messages = await uow.retention.messages_before(
            guild.guild_id, now - timedelta(days=guild.retention_days)
        )
        if not messages:
            continue
        record_ids = [message.id for message in messages]
        source_ids = {message.discord_message_id for message in messages}
        for action in await uow.retention.actions(guild.guild_id):
            if action.payload.get("source_message_id") not in source_ids:
                continue
            await uow.actions.update(
                action.id,
                payload={
                    key: value for key, value in action.payload.items() if key != "source_content"
                },
            )
            if action.status in {"PENDING", "CLAIMED"}:
                await uow.actions.update(
                    action.id,
                    status="DEAD",
                    error_type="retention_expired",
                    lease_owner=None,
                    lease_expires_at=None,
                )
        for summary in await uow.retention.summary_sources(guild.guild_id):
            await uow.retention.replace_summary_sources(
                summary.id,
                [
                    message_id
                    for message_id in summary.source_message_ids
                    if message_id not in source_ids
                ],
            )
        await uow.retention.delete_messages(record_ids)
        removed += len(record_ids)
    await uow.commit()
    return removed
