"""Ingestion and classification use cases."""

from backend.application.agent_workflow import create_topic_workflow
from backend.application.contracts import ClassificationResult, ModelProvider, TopicCandidate
from backend.application.errors import ChannelNotAllowedError
from backend.application.ports.persistence import UnitOfWork
from backend.application.read_models import TopicReadModel
from backend.application.services.message_context import build_message_context
from backend.application.services.results import IngestResult, ProcessingResult
from backend.domain.entities import ConversationMessage, ConversationTopic
from backend.domain.enums import ActionType, AssociationKind, TopicStatus


def _classification_payload(
    result: ClassificationResult, context_message_ids: list[str] | None = None
) -> dict[str, object]:
    return {
        "decision": result.decision.model_dump(mode="json"),
        "stage": "topic_classification",
        "model_id": result.model_id,
        "candidate_topic_ids": result.candidate_topic_ids,
        "context_message_ids": context_message_ids or [],
        "usage": {
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "cached_tokens": result.cached_tokens,
            "latency_ms": result.latency_ms,
        },
    }


async def ingest_message(
    uow: UnitOfWork, message: ConversationMessage, max_attempts: int
) -> IngestResult:
    if not await uow.guilds.channel_is_enabled(message.guild_id, message.channel_id):
        raise ChannelNotAllowedError("Guild or channel is not enabled by an administrator")
    record, inserted = await uow.messages.ingest(message, max_attempts)
    await uow.commit()
    return IngestResult(record.id, inserted)


async def _summary_candidates(
    uow: UnitOfWork, topics: list[TopicReadModel], reply_topic_id: str | None = None
) -> list[TopicCandidate]:
    result: list[TopicCandidate] = []
    for topic in topics:
        summary = await uow.summaries.latest(topic.guild_id, topic.id)
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
    uow: UnitOfWork, message_record_id: str, provider: ModelProvider
) -> ProcessingResult:
    record = await uow.messages.get(message_record_id)
    if record is None:
        raise LookupError(f"Message record {message_record_id} does not exist")
    message = ConversationMessage(
        id=record.id,
        guild_id=record.guild_id,
        channel_id=record.channel_id,
        message_id=record.discord_message_id,
        author_id=record.author_id,
        author_name=record.author_name,
        content=record.content,
        created_at=record.created_at,
        reply_to_message_id=record.reply_to_message_id,
    )
    candidate_records = list(await uow.topics.candidates(message.guild_id))
    reply_topic_id: str | None = None
    if message.reply_to_message_id:
        associated_topic_id = await uow.messages.reply_topic_id(
            message.guild_id, message.reply_to_message_id
        )
        if associated_topic_id:
            reply_topic = await uow.topics.get(message.guild_id, associated_topic_id)
            if reply_topic and reply_topic.status != TopicStatus.CLOSED:
                reply_topic_id = reply_topic.id
                if all(candidate.id != reply_topic.id for candidate in candidate_records):
                    candidate_records.insert(0, reply_topic)
                else:
                    candidate_records.sort(key=lambda candidate: candidate.id != reply_topic.id)
    candidates = await _summary_candidates(uow, candidate_records, reply_topic_id)
    context = await build_message_context(uow.messages, message)
    # Provider work finishes before any classification writes are staged.
    state = await create_topic_workflow(provider).ainvoke(
        {"message": message, "candidates": candidates, "context": context}
    )
    classification = state["classification"]
    decision = classification.decision

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

    topic: TopicReadModel | None = None
    new_topic = False
    if decision.outcome == "existing" and decision.topic_id:
        topic = await uow.topics.get(message.guild_id, decision.topic_id)
        if topic is None or topic.status == TopicStatus.CLOSED:
            decision.outcome = "defer"
            decision.reason = "provider selected a missing, closed, or cross-guild topic"
        elif topic.status == TopicStatus.DORMANT:
            lifecycle = ConversationTopic.create(topic.guild_id, topic.title)
            lifecycle.status = TopicStatus(topic.status)
            lifecycle.transition_to(TopicStatus.RESUMED)
            await uow.topics.set_status(message.guild_id, topic.id, lifecycle.status.value)
            await uow.topics.add_episode(message.guild_id, topic.id, message.created_at)
    elif decision.outcome == "new":
        if not decision.title or not decision.title.strip():
            decision.outcome = "defer"
            decision.reason = "provider proposed a new topic without a title"
        else:
            entity = ConversationTopic.create(message.guild_id, decision.title)
            entity.description = decision.description
            entity.last_activity_at = message.created_at
            topic = await uow.topics.create(entity)
            await uow.topics.add_episode(message.guild_id, topic.id, message.created_at)
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
    await uow.messages.add_association(
        message.guild_id,
        message.id,
        topic.id if topic else None,
        association_kind.value,
        decision.confidence,
        decision.reason,
    )
    await uow.messages.add_decision(
        message.guild_id,
        message.id,
        decision.outcome,
        classification.model_id,
        _classification_payload(classification, [item.message_id for item in context]),
    )

    if topic is not None:
        await uow.topics.touch(message.guild_id, topic.id, topic.version, message.created_at)
        create_action_id: str | None = None
        source_payload = {
            "source_message_id": message.message_id,
            "source_author_name": message.author_name,
            "source_created_at": message.created_at.isoformat(),
            "source_content": message.content,
        }
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

        prior_summary = await uow.summaries.latest(message.guild_id, topic.id)
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
            summary = await uow.summaries.add(
                message.guild_id,
                topic.id,
                (prior_summary.version + 1) if prior_summary else 1,
                data,
                source_ids,
            )
            await uow.actions.add(
                message.guild_id,
                message.channel_id,
                topic.id,
                ActionType.UPSERT_SUMMARY,
                {"summary_id": summary.id, "version": summary.version, "summary": data},
                dependency_id=create_action_id,
            )
    return ProcessingResult(
        decision.outcome, topic.id if topic else None, classification.candidate_topic_ids
    )
