"""Ingestion and classification use cases."""

from backend.application.agent_workflow import create_topic_workflow
from backend.application.contracts import ClassificationResult, ModelProvider, TopicDecision
from backend.application.errors import ChannelNotAllowedError
from backend.application.ports.persistence import UnitOfWork
from backend.application.read_models import TopicReadModel
from backend.application.services.results import IngestResult, ProcessingResult
from backend.application.services.topic_projection import project_topic
from backend.application.services.topic_tools import TopicTools
from backend.application.topic_memory import InvalidMemoryUpdate, merge_topic_memory
from backend.domain.entities import ConversationMessage, ConversationTopic
from backend.domain.enums import AssociationKind, TopicStatus


def _classification_payload(
    result: ClassificationResult, context_message_ids: list[str] | None = None
) -> dict[str, object]:
    return {
        "decision": result.decision.model_dump(mode="json"),
        "stage": "topic_classification",
        "policy_version": result.policy_version,
        "model_calls": result.model_calls,
        "model_id": result.model_id,
        "candidate_topic_ids": result.candidate_topic_ids,
        "context_message_ids": context_message_ids or [],
        "language_hints": result.language_hints,
        "task_route": result.task_route,
        "usage": {
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "cached_tokens": result.cached_tokens,
            "reasoning_tokens": result.reasoning_tokens,
            "latency_ms": result.latency_ms,
        },
    }


async def ingest_message(
    uow: UnitOfWork, message: ConversationMessage, max_attempts: int
) -> IngestResult:
    if not await uow.guilds.channel_is_enabled(message.guild_id, message.channel_id):
        raise ChannelNotAllowedError("Guild or channel is not enabled by an administrator")
    record, inserted = await uow.messages.ingest(message, max_attempts)
    if inserted:
        await uow.jobs.wake_deferred(record.id)
    await uow.commit()
    return IngestResult(record.id, inserted)


async def process_message_record(
    uow: UnitOfWork,
    message_record_id: str,
    provider: ModelProvider,
    *,
    followup_message_id: str | None = None,
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
        attachments=record.attachments,
    )
    tools_context = await TopicTools(uow).gather(message, followup_message_id)
    candidates = tools_context.candidates
    context = tools_context.messages
    reply_topic_id = tools_context.reply_topic_id
    # Provider work finishes before any classification writes are staged.
    state = await create_topic_workflow(provider).ainvoke(
        {"message": message, "candidates": candidates, "context": context}
    )
    classification = state["classification"]
    decision = classification.decision

    topic: TopicReadModel | None = None
    new_topic = False
    if decision.outcome == "existing" and decision.topic_id:
        topic = await uow.topics.get(message.guild_id, decision.topic_id)
        if topic is None or topic.status == TopicStatus.CLOSED:
            classification.decision = decision = TopicDecision(
                outcome="defer",
                confidence=0,
                defer_reason="invalid_topic",
                reason="provider selected a missing, closed, or cross-guild topic",
            )
            topic = None
    elif decision.outcome == "new":
        if not decision.title or not decision.title.strip():
            decision.outcome = "defer"
            decision.reason = "provider proposed a new topic without a title"
        else:
            entity = ConversationTopic.create(message.guild_id, decision.title, message.channel_id)
            entity.description = decision.description
            entity.last_activity_at = message.created_at
            topic = await uow.topics.create(entity)
            await uow.topics.add_episode(message.guild_id, topic.id, message.created_at)
            new_topic = True
    elif decision.outcome not in {"defer", "irrelevant"}:
        decision.outcome = "defer"
        decision.reason = "unsupported provider outcome"

    prior_summary = None
    summary_data = {}
    if topic is not None:
        prior_summary = await uow.summaries.latest(message.guild_id, topic.id)
        try:
            summary_data = merge_topic_memory(
                prior_summary.data if prior_summary else {},
                decision,
                message.content,
                topic_id=topic.id,
                title=topic.title,
                description=topic.description,
            )
        except InvalidMemoryUpdate:
            classification.decision = decision = TopicDecision(
                outcome="defer",
                confidence=0,
                defer_reason="invalid_evidence",
                reason="memory reference no longer matches the complete stored topic",
            )
            topic = None
        if topic is not None and topic.status == TopicStatus.DORMANT:
            lifecycle = ConversationTopic.create(topic.guild_id, topic.title)
            lifecycle.status = TopicStatus(topic.status)
            lifecycle.transition_to(TopicStatus.RESUMED)
            await uow.topics.set_status(message.guild_id, topic.id, lifecycle.status.value)
            await uow.topics.add_episode(message.guild_id, topic.id, message.created_at)

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
        await project_topic(uow, message, topic, new_topic, prior_summary, summary_data)
        await uow.jobs.wake_deferred(message.id)
    return ProcessingResult(
        decision.outcome,
        topic.id if topic else None,
        classification.candidate_topic_ids,
        decision.defer_reason,
    )
