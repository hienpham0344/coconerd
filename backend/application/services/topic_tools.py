"""Bounded read-only tools orchestrated by code, without a paid tool-calling loop."""

from dataclasses import dataclass

from backend.application.clarification import is_clarification
from backend.application.contracts import TopicCandidate
from backend.application.ports.persistence import UnitOfWork
from backend.application.read_models import ContextMessage, MessageReadModel
from backend.application.services.message_context import bound_context, build_message_context
from backend.application.topic_retriever import retrieval_message, retrieve_topic_candidates
from backend.domain.entities import ConversationMessage


@dataclass
class TopicContext:
    candidates: list[TopicCandidate]
    messages: list[ContextMessage]
    reply_topic_id: str | None


class TopicTools:
    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    async def get_reply_chain(self, message: ConversationMessage) -> list[ContextMessage]:
        return await build_message_context(self.uow.messages, message)

    async def search_topics(self, message: ConversationMessage, context: list[ContextMessage]):
        anchors = " ".join(
            item.content
            for item in context
            if item.relation in {"reply_ancestor", "followup_clarification"}
        )
        query = f"{message.content} {anchors}"[:2400]
        indexed = await self.uow.topics.search(message.guild_id, query, limit=30)
        recent = await self.uow.topics.candidates(message.guild_id)
        return list({item.id: item for item in [*indexed, *recent]}.values())

    async def get_topic_evidence(
        self, message: ConversationMessage, topic_id: str
    ) -> list[ContextMessage]:
        records = await self.uow.messages.evidence_for_topic(
            message.guild_id, message.channel_id, topic_id, message.created_at, limit=2
        )
        return [
            ContextMessage(
                item.discord_message_id,
                item.author_id,
                item.author_name,
                item.created_at,
                "topic_evidence",
                item.content[:400],
            )
            for item in records
        ]

    async def gather(
        self, message: ConversationMessage, followup_message_id: str | None = None
    ) -> TopicContext:
        context = await self.get_reply_chain(message)
        if followup_message_id:
            followup = await self.uow.messages.get(followup_message_id)
            target = MessageReadModel(
                message.id,
                message.guild_id,
                message.channel_id,
                message.message_id,
                message.author_id,
                message.author_name,
                message.content,
                message.created_at,
                message.reply_to_message_id,
            )
            if followup and is_clarification(target, followup):
                context = bound_context(
                    [
                        ContextMessage(
                            followup.discord_message_id,
                            followup.author_id,
                            followup.author_name,
                            followup.created_at,
                            "followup_clarification",
                            followup.content,
                        ),
                        *context,
                    ]
                )
        records = await self.search_topics(message, context)
        reply_topic_id = None
        if message.reply_to_message_id and any(
            item.message_id == message.reply_to_message_id and item.relation == "reply_ancestor"
            for item in context
        ):
            associated = await self.uow.messages.reply_topic_id(
                message.guild_id, message.reply_to_message_id
            )
            reply_topic = (
                await self.uow.topics.get(message.guild_id, associated) if associated else None
            )
            if reply_topic and reply_topic.status != "CLOSED":
                reply_topic_id = reply_topic.id
                records = [reply_topic, *(item for item in records if item.id != reply_topic.id)]
        bounded = records[:60]
        summaries = (
            await self.uow.summaries.latest_many(message.guild_id, [item.id for item in bounded])
            if bounded
            else {}
        )
        candidates = []
        for topic in bounded:
            summary = summaries.get(topic.id)
            candidates.append(
                TopicCandidate(
                    id=topic.id,
                    title=topic.title,
                    description=topic.description,
                    status=topic.status,
                    summary=summary.data if summary else {},
                    evidence="direct_reply_target" if topic.id == reply_topic_id else "",
                )
            )
        candidates = retrieve_topic_candidates(retrieval_message(message, context), candidates)
        if candidates:
            evidence = await self.get_topic_evidence(message, candidates[0].id)
            context = bound_context([*context, *evidence])
        return TopicContext(candidates, context, reply_topic_id)
