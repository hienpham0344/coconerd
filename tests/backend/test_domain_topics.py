import pytest

from backend.domain.entities import ConversationTopic
from backend.domain.enums import TopicStatus
from backend.domain.exceptions import InvalidTopicTransition


def test_topic_can_be_resumed_from_dormant():
    topic = ConversationTopic.create(guild_id="guild-a", title="Launch plan")
    topic.transition_to(TopicStatus.DORMANT)

    topic.transition_to(TopicStatus.RESUMED)

    assert topic.status is TopicStatus.RESUMED


def test_topic_cannot_be_closed_from_active_without_explicit_close_rule():
    topic = ConversationTopic.create(guild_id="guild-a", title="Launch plan")

    with pytest.raises(InvalidTopicTransition):
        topic.transition_to(TopicStatus.CLOSED)


def test_topic_is_guild_scoped():
    topic = ConversationTopic.create(guild_id="guild-a", title="Launch plan")

    assert topic.guild_id == "guild-a"
    assert topic.id


def test_explicit_close_is_terminal():
    topic = ConversationTopic.create(guild_id="guild-a", title="Launch plan")

    topic.close()

    assert topic.status is TopicStatus.CLOSED
    with pytest.raises(InvalidTopicTransition):
        topic.transition_to(TopicStatus.ACTIVE)
