"""Persist topic activity, Discord actions and a prepared memory projection."""

from backend.application.ports.persistence import UnitOfWork
from backend.application.read_models import SummaryReadModel, TopicReadModel
from backend.domain.entities import ConversationMessage
from backend.domain.enums import ActionType


async def project_topic(
    uow: UnitOfWork,
    message: ConversationMessage,
    topic: TopicReadModel,
    new_topic: bool,
    prior_summary: SummaryReadModel | None,
    summary_data: dict[str, object],
) -> None:
    await uow.topics.touch(message.guild_id, topic.id, topic.version, message.created_at)
    create_action_id: str | None = None
    source_payload = {
        "source_message_id": message.message_id,
        "source_author_name": message.author_name,
        "source_created_at": message.created_at.isoformat(),
        "source_content": message.content,
    }
    if not topic.sync_paused:
        if new_topic:
            create_action = await uow.actions.add(
                message.guild_id,
                message.channel_id,
                topic.id,
                ActionType.CREATE_THREAD,
                {"title": topic.title, **source_payload},
            )
            create_action_id = create_action.id
        elif topic.discord_thread_id:
            await uow.actions.add(
                message.guild_id,
                message.channel_id,
                topic.id,
                ActionType.APPEND_MESSAGE,
                source_payload,
            )
        else:
            pending_create = await uow.actions.pending_create(message.guild_id, topic.id)
            if pending_create:
                create_action_id = pending_create.id
                await uow.actions.add(
                    message.guild_id,
                    message.channel_id,
                    topic.id,
                    ActionType.APPEND_MESSAGE,
                    source_payload,
                    dependency_id=pending_create.id,
                )
            else:
                create_action = await uow.actions.add(
                    message.guild_id,
                    message.channel_id,
                    topic.id,
                    ActionType.CREATE_THREAD,
                    {"title": topic.title, **source_payload},
                )
                create_action_id = create_action.id

    if prior_summary is None or summary_data != prior_summary.data:
        source_ids = list(
            dict.fromkeys(
                [
                    *(prior_summary.source_message_ids if prior_summary else []),
                    message.message_id,
                ]
            )
        )
        summary = await uow.summaries.add(
            message.guild_id,
            topic.id,
            prior_summary.version + 1 if prior_summary else 1,
            summary_data,
            source_ids,
        )
        if topic.sync_paused:
            return
        await uow.actions.add(
            message.guild_id,
            message.channel_id,
            topic.id,
            ActionType.UPSERT_SUMMARY,
            {"summary_id": summary.id, "version": summary.version, "summary": summary_data},
            dependency_id=create_action_id,
        )
