"""Use-case tests with persistence doubles, avoiding the SQLite connection stall."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from backend.application.contracts import ClassificationResult, TopicDecision
from backend.application.read_models import MessageReadModel, TopicReadModel
from backend.application.services.messages import ingest_message, process_message_record
from backend.domain.entities import ConversationMessage


async def _empty_recent(*_args, **_kwargs):
    return []


def _message() -> ConversationMessage:
    return ConversationMessage(
        guild_id="guild-1",
        channel_id="channel-1",
        message_id="discord-1",
        author_id="author-1",
        author_name="User",
        content="Discuss launch timing",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


class FakeProvider:
    model_id = "fake"

    async def classify(self, message, candidates):
        assert message.message_id == "discord-1"
        assert candidates == []
        return ClassificationResult(
            decision=TopicDecision(
                outcome="new",
                title="Launch",
                summary="Launch timing",
                confidence=0.8,
                reason="new discussion",
            ),
            model_id="fake",
            candidate_topic_ids=[],
            latency_ms=4,
        )


async def test_ingest_rejects_disallowed_channel_without_writes():
    from backend.application.errors import ChannelNotAllowedError

    class Messages:
        async def ingest(self, *_args):
            pytest.fail("disallowed message must not be persisted")

    async def disabled(*_args):
        return False

    uow = SimpleNamespace(
        guilds=SimpleNamespace(channel_is_enabled=disabled),
        messages=Messages(),
        commit=lambda: pytest.fail("disallowed message must not commit"),
    )
    with pytest.raises(ChannelNotAllowedError):
        await ingest_message(uow, _message(), 3)


async def test_ingest_duplicate_returns_same_record_id_and_commits_once():
    commits = []

    async def enabled(*_args):
        return True

    async def ingest(_message, _attempts):
        return SimpleNamespace(id="persisted-id"), False

    async def commit():
        commits.append(True)

    uow = SimpleNamespace(
        guilds=SimpleNamespace(channel_is_enabled=enabled),
        messages=SimpleNamespace(ingest=ingest),
        commit=commit,
    )
    result = await ingest_message(uow, _message(), 3)
    assert (result.message_id, result.inserted) == ("persisted-id", False)
    assert commits == [True]


async def test_processing_writes_new_topic_decision_summary_and_actions_atomically(monkeypatch):
    from backend.application.services import messages as message_service

    class Workflow:
        async def ainvoke(self, state):
            return {
                "classification": await FakeProvider().classify(
                    state["message"], state["candidates"]
                )
            }

    monkeypatch.setattr(message_service, "create_topic_workflow", lambda _provider: Workflow())
    message = _message()
    record = MessageReadModel(
        id="record-1",
        guild_id=message.guild_id,
        channel_id=message.channel_id,
        discord_message_id=message.message_id,
        author_id=message.author_id,
        author_name=message.author_name,
        content=message.content,
        created_at=message.created_at,
        reply_to_message_id=None,
    )
    writes = []

    async def get_message(_id):
        assert _id == "record-1"
        return record

    async def candidates(_guild):
        return []

    async def create(topic):
        writes.append(("topic", topic.id))
        return SimpleNamespace(
            id=topic.id,
            guild_id=topic.guild_id,
            title=topic.title,
            description=topic.description,
            status=topic.status.value,
            last_activity_at=topic.last_activity_at,
            version=1,
            discord_thread_id=None,
        )

    async def add_action(
        _guild, _channel, _topic, action_type, _payload, dependency_id=None, max_attempts=5
    ):
        writes.append(("action", action_type.value, dependency_id))
        return SimpleNamespace(
            id="create-action" if action_type.value == "CREATE_THREAD" else "other"
        )

    async def add_summary(*args):
        writes.append(("summary", args[2], args[3]["overview"]))
        return SimpleNamespace(id="summary-1", version=args[2])

    async def none(*_args):
        return None

    async def touch(*_args):
        writes.append(("touch",))

    async def episode(*_args):
        writes.append(("episode",))

    async def association(*args):
        writes.append(("association", args[3]))

    async def decision(*args):
        writes.append(("decision", args[2], args[4]))

    async def commit():
        writes.append(("commit",))

    uow = SimpleNamespace(
        messages=SimpleNamespace(
            get=get_message,
            recent_before=_empty_recent,
            evidence_for_topic=_empty_recent,
            reply_topic_id=none,
            add_association=association,
            add_decision=decision,
        ),
        topics=SimpleNamespace(
            search=_empty_recent,
            candidates=candidates,
            create=create,
            get=none,
            touch=touch,
            add_episode=episode,
        ),
        summaries=SimpleNamespace(latest=none, add=add_summary),
        actions=SimpleNamespace(add=add_action, pending_create=none),
        commit=commit,
    )
    result = await process_message_record(uow, "record-1", FakeProvider())
    assert result.outcome == "new"
    assert result.topic_id is not None
    assert result.candidate_topic_ids == []
    assert [item[0] for item in writes] == [
        "topic",
        "episode",
        "association",
        "decision",
        "touch",
        "action",
        "summary",
        "action",
    ]
    assert writes[6] == ("summary", 1, "Launch timing")
    assert writes[7] == ("action", "UPSERT_SUMMARY", "create-action")
    assert writes[3][2]["candidate_topic_ids"] == []


async def test_processing_persists_nonempty_retrieved_candidate_ids(monkeypatch):
    """A real shortlist must survive the workflow-to-decision boundary."""
    from backend.application.services import messages as message_service

    message = _message()
    topic = TopicReadModel(
        id="topic-1",
        guild_id="guild-1",
        title="Launch timing",
        description="Scheduling",
        status="ACTIVE",
        last_activity_at=message.created_at,
        version=2,
        discord_thread_id="thread-1",
    )
    observed_candidates = []
    payloads = []

    class Workflow:
        async def ainvoke(self, state):
            observed_candidates.extend(state["candidates"])
            return {
                "classification": ClassificationResult(
                    decision=TopicDecision(outcome="defer", confidence=0.3, reason="uncertain"),
                    model_id="fake",
                    candidate_topic_ids=["topic-1"],
                    latency_ms=7,
                )
            }

    async def get_message(_id):
        return MessageReadModel(
            id="record-1",
            guild_id=message.guild_id,
            channel_id=message.channel_id,
            discord_message_id=message.message_id,
            author_id=message.author_id,
            author_name=message.author_name,
            content=message.content,
            created_at=message.created_at,
            reply_to_message_id=None,
        )

    async def candidates(_guild):
        return [topic]

    async def none(*_args):
        return None

    async def add_association(*_args):
        return None

    async def add_decision(_guild, _message_id, _outcome, _model, payload):
        payloads.append(payload)

    monkeypatch.setattr(message_service, "create_topic_workflow", lambda _provider: Workflow())
    uow = SimpleNamespace(
        messages=SimpleNamespace(
            get=get_message,
            recent_before=_empty_recent,
            evidence_for_topic=_empty_recent,
            add_association=add_association,
            add_decision=add_decision,
        ),
        topics=SimpleNamespace(candidates=candidates, search=_empty_recent),
        summaries=SimpleNamespace(latest=none),
    )
    result = await process_message_record(uow, "record-1", FakeProvider())

    assert [item.id for item in observed_candidates] == ["topic-1"]
    assert result.candidate_topic_ids == ["topic-1"]
    assert payloads[0]["candidate_topic_ids"] == ["topic-1"]
