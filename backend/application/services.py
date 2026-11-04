from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.agent_workflow import create_topic_workflow
from backend.application.contracts import ModelProvider, TopicCandidate
from backend.domain.entities import ConversationMessage, ConversationTopic
from backend.domain.enums import ActionType, AssociationKind, JobStatus, TopicStatus
from backend.infrastructure.database.models import (
    AIDecisionRecord,
    DiscordActionRecord,
    EpisodeRecord,
    MessageRecord,
    MessageTopicAssociationRecord,
    ProcessingJobRecord,
    TopicRecord,
)
from backend.infrastructure.database.repositories import (
    ActionRepository,
    GuildRepository,
    MessageRepository,
    SummaryRepository,
    TopicRepository,
)


class ChannelNotAllowedError(Exception):
    pass


async def ingest_message(
    session: AsyncSession, message: ConversationMessage, max_attempts: int
) -> tuple[MessageRecord, bool]:
    if not await GuildRepository(session).channel_is_enabled(message.guild_id, message.channel_id):
        raise ChannelNotAllowedError("Guild or channel is not enabled by an administrator")
    record, inserted = await MessageRepository(session).ingest(message, max_attempts)
    await session.commit()
    return record, inserted


async def _summary_candidates(
    session: AsyncSession, topics: list[TopicRecord], reply_topic_id: str | None = None
) -> list[TopicCandidate]:
    summaries = SummaryRepository(session)
    result: list[TopicCandidate] = []
    for topic in topics:
        summary = await summaries.latest(topic.guild_id, topic.id)
        result.append(
            TopicCandidate(
                id=topic.id,
                title=topic.title,
                description=topic.description,
                status=topic.status,
                summary=summary.data if summary else {},
                evidence="direct_reply_target" if topic.id == reply_topic_id else "",
            )
        )
    return result


async def process_message_record(
    session: AsyncSession, message_record_id: str, provider: ModelProvider
) -> None:
    message_record = await session.get(MessageRecord, message_record_id)
    if message_record is None:
        raise LookupError(f"Message record {message_record_id} does not exist")
    message = ConversationMessage(
        id=message_record.id,
        guild_id=message_record.guild_id,
        channel_id=message_record.channel_id,
        message_id=message_record.discord_message_id,
        author_id=message_record.author_id,
        author_name=message_record.author_name,
        content=message_record.content,
        created_at=message_record.created_at,
        reply_to_message_id=message_record.reply_to_message_id,
    )
    topics = TopicRepository(session)
    candidates_records = await topics.candidates(message.guild_id, channel_id=message.channel_id)
    reply_topic_id: str | None = None
    if message.reply_to_message_id:
        reply_association = await session.scalar(
            select(MessageTopicAssociationRecord)
            .join(
                MessageRecord, MessageRecord.id == MessageTopicAssociationRecord.message_record_id
            )
            .where(
                MessageRecord.guild_id == message.guild_id,
                MessageRecord.discord_message_id == message.reply_to_message_id,
                MessageTopicAssociationRecord.guild_id == message.guild_id,
                MessageTopicAssociationRecord.topic_id.is_not(None),
            )
        )
        if reply_association:
            reply_topic = await topics.get(message.guild_id, reply_association.topic_id)
            if (
                reply_topic
                and reply_topic.status != TopicStatus.CLOSED
                and reply_topic.channel_id == message.channel_id
            ):
                reply_topic_id = reply_topic.id
                if all(candidate.id != reply_topic.id for candidate in candidates_records):
                    candidates_records.insert(0, reply_topic)
                else:
                    candidates_records.sort(key=lambda candidate: candidate.id != reply_topic.id)
    candidates = await _summary_candidates(session, candidates_records, reply_topic_id)
    state = await create_topic_workflow(provider).ainvoke(
        {"message": message, "candidates": candidates}
    )
    decision = state["decision"]

    if decision.outcome == "new" and decision.title:
        requested_title = " ".join(decision.title.casefold().split())
        duplicate = next(
            (
                candidate
                for candidate in candidates
                if " ".join(candidate.title.casefold().split()) == requested_title
            ),
            None,
        )
        if duplicate:
            decision.outcome = "existing"
            decision.topic_id = duplicate.id
            decision.reason = "new topic title matches an existing guild topic"

    topic: TopicRecord | None = None
    new_topic = False
    if decision.outcome == "existing":
        if not decision.topic_id:
            decision.outcome = "defer"
            decision.reason = "provider selected an existing topic outcome without a topic_id"
            topic = None
        else:
            existing_candidate = await topics.get(message.guild_id, decision.topic_id)
            if (
                existing_candidate is None
                or existing_candidate.guild_id != message.guild_id
                or existing_candidate.channel_id != message.channel_id
                or existing_candidate.status == TopicStatus.CLOSED
            ):
                decision.outcome = "defer"
                decision.reason = (
                    "provider selected a missing, closed, cross-guild, or cross-channel topic"
                )
                topic = None
            elif existing_candidate.status == TopicStatus.DORMANT:
                topic = existing_candidate
                lifecycle = ConversationTopic.create(
                    topic.guild_id, topic.title, channel_id=topic.channel_id
                )
                lifecycle.status = TopicStatus(topic.status)
                lifecycle.transition_to(TopicStatus.RESUMED)
                topic.status = lifecycle.status.value
                session.add(
                    EpisodeRecord(
                        id=str(uuid4()),
                        guild_id=message.guild_id,
                        topic_id=topic.id,
                        started_at=message.created_at,
                    )
                )
            else:
                topic = existing_candidate
    elif decision.outcome == "new":
        if not decision.title or not decision.title.strip():
            decision.outcome = "defer"
            decision.reason = "provider proposed a new topic without a title"
        else:
            topic_entity = ConversationTopic.create(
                message.guild_id, decision.title, channel_id=message.channel_id
            )
            topic_entity.description = decision.description
            topic_entity.last_activity_at = message.created_at
            topic = await topics.create(topic_entity)
            session.add(
                EpisodeRecord(
                    id=str(uuid4()),
                    guild_id=message.guild_id,
                    topic_id=topic.id,
                    started_at=message.created_at,
                )
            )
            new_topic = True
    elif decision.outcome not in {"defer", "irrelevant"}:
        decision.outcome = "defer"
        decision.reason = "unsupported provider outcome"

    association_kind = {
        "existing": (
            AssociationKind.REPLY_LINK
            if reply_topic_id and decision.topic_id == reply_topic_id
            else AssociationKind.CLASSIFIED
        ),
        "new": AssociationKind.CLASSIFIED,
        "defer": AssociationKind.DEFERRED,
        "irrelevant": AssociationKind.IRRELEVANT,
    }[decision.outcome]
    session.add(
        MessageTopicAssociationRecord(
            id=str(uuid4()),
            guild_id=message.guild_id,
            message_record_id=message.id,
            topic_id=topic.id if topic else None,
            kind=association_kind.value,
            confidence=decision.confidence,
            reason=decision.reason,
        )
    )
    session.add(
        AIDecisionRecord(
            id=str(uuid4()),
            guild_id=message.guild_id,
            message_record_id=message.id,
            decision_type=decision.outcome,
            model_id=provider.model_id,
            payload=decision.model_dump(mode="json"),
        )
    )

    if topic is not None:
        topic.last_activity_at = message.created_at
        expected_version = topic.version
        version_result = await session.execute(
            update(TopicRecord)
            .where(TopicRecord.id == topic.id, TopicRecord.version == expected_version)
            .values(version=expected_version + 1, last_activity_at=message.created_at)
            .execution_options(synchronize_session=False)
        )
        if version_result.rowcount != 1:
            raise RuntimeError("Topic changed concurrently; processing will be retried")
        topic.version = expected_version + 1
        actions = ActionRepository(session)
        create_action_id: str | None = None
        if new_topic:
            create_action = await actions.add(
                guild_id=message.guild_id,
                channel_id=message.channel_id,
                topic_id=topic.id,
                action_type=ActionType.CREATE_THREAD,
                payload={
                    "title": topic.title,
                    "source_message_id": message.message_id,
                    "source_author_name": message.author_name,
                    "source_created_at": message.created_at.isoformat(),
                    "source_content": message.content,
                },
            )
            create_action_id = create_action.id
        elif topic.discord_thread_id:
            await actions.add(
                guild_id=message.guild_id,
                channel_id=message.channel_id,
                topic_id=topic.id,
                action_type=ActionType.APPEND_MESSAGE,
                payload={
                    "source_message_id": message.message_id,
                    "source_author_name": message.author_name,
                    "source_created_at": message.created_at.isoformat(),
                    "source_content": message.content,
                },
            )
        elif topic.discord_thread_id is None:
            pending_create = await session.scalar(
                select(DiscordActionRecord)
                .where(
                    DiscordActionRecord.guild_id == message.guild_id,
                    DiscordActionRecord.topic_id == topic.id,
                    DiscordActionRecord.action_type == ActionType.CREATE_THREAD.value,
                    DiscordActionRecord.status.in_(["PENDING", "CLAIMED"]),
                )
                .order_by(DiscordActionRecord.created_at)
                .limit(1)
            )
            if pending_create is not None:
                create_action_id = pending_create.id
                await actions.add(
                    guild_id=message.guild_id,
                    channel_id=message.channel_id,
                    topic_id=topic.id,
                    action_type=ActionType.APPEND_MESSAGE,
                    payload={
                        "source_message_id": message.message_id,
                        "source_author_name": message.author_name,
                        "source_created_at": message.created_at.isoformat(),
                        "source_content": message.content,
                    },
                    dependency_id=pending_create.id,
                )
            else:
                create_action = await actions.add(
                    guild_id=message.guild_id,
                    channel_id=message.channel_id,
                    topic_id=topic.id,
                    action_type=ActionType.CREATE_THREAD,
                    payload={
                        "title": topic.title,
                        "source_message_id": message.message_id,
                        "source_author_name": message.author_name,
                        "source_created_at": message.created_at.isoformat(),
                        "source_content": message.content,
                    },
                )
                create_action_id = create_action.id

        prior_summary = await SummaryRepository(session).latest(message.guild_id, topic.id)
        old = prior_summary.data if prior_summary else {}
        old_overview = str(old.get("overview", topic.description))
        overview = decision.summary.strip() or old_overview
        merged_lists: dict[str, list[str]] = {}
        lists_changed = False
        for field, additions in (
            ("proposals", decision.proposals),
            ("decisions", decision.decisions),
            ("open_questions", decision.open_questions),
            ("action_items", decision.action_items),
        ):
            existing = old.get(field, [])
            previous_items = (
                [item for item in existing if isinstance(item, str)]
                if isinstance(existing, list)
                else []
            )
            merged = list(dict.fromkeys([*previous_items, *additions]))
            merged_lists[field] = merged
            lists_changed = lists_changed or len(merged) > len(previous_items)
        summary_changed = prior_summary is None or overview != old_overview or lists_changed
        if summary_changed:
            data: dict[str, object] = {
                "topic_id": topic.id,
                "title": topic.title,
                "overview": overview,
                **merged_lists,
            }
            source_ids = list(
                dict.fromkeys(
                    [
                        *(prior_summary.source_message_ids if prior_summary else []),
                        message.message_id,
                    ]
                )
            )
            summary = await SummaryRepository(session).add(
                message.guild_id,
                topic.id,
                (prior_summary.version + 1) if prior_summary else 1,
                data,
                source_ids,
            )
            await actions.add(
                guild_id=message.guild_id,
                channel_id=message.channel_id,
                topic_id=topic.id,
                action_type=ActionType.UPSERT_SUMMARY,
                payload={"summary_id": summary.id, "version": summary.version, "summary": data},
                dependency_id=create_action_id,
            )


async def complete_job(session: AsyncSession, job: ProcessingJobRecord) -> None:
    job.status = JobStatus.SUCCEEDED
    job.lease_owner = None
    job.lease_expires_at = None
    job.error_type = None
    await session.commit()
