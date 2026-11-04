from datetime import UTC, datetime

import pytest

from backend.application.contracts import ClassificationResult, TopicCandidate, TopicDecision
from backend.application.decision_policy import classify_locally, validate_classification
from backend.application.read_models import ContextMessage
from backend.domain.entities import ConversationMessage


def message(content="Lỗi login trên mobile"):
    return ConversationMessage(
        guild_id="g",
        channel_id="c",
        message_id="target",
        author_id="a",
        author_name="A",
        content=content,
        created_at=datetime.now(UTC),
    )


def candidate():
    return TopicCandidate(id="mobile", title="Mobile login", description="", status="ACTIVE")


def result(**changes):
    fields = dict(
        outcome="existing",
        topic_id="mobile",
        confidence=0.99,
        reason="match",
        evidence_message_ids=["target"],
    )
    fields.update(changes)
    return ClassificationResult(decision=TopicDecision(**fields), model_id="test", latency_ms=1)


@pytest.mark.parametrize("content", ["ok", "OK!", "đồng ý", "yes"])
def test_ambiguous_ack_without_reply_defers_locally(content):
    classified = classify_locally(message(content), [])
    assert classified.decision.outcome == "defer"
    assert classified.decision.defer_reason == "missing_context"
    assert classified.model_calls == classified.prompt_tokens == classified.completion_tokens == 0


def test_reply_ack_is_left_for_model_even_with_unrelated_recent_messages():
    context = [ContextMessage("root", "a", "A", datetime.now(UTC), "reply_ancestor", "Beta?")]
    assert classify_locally(message("ok"), context) is None


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"evidence_message_ids": ["invented"]}, "invalid_evidence"),
        ({"evidence_message_ids": []}, "invalid_evidence"),
        ({"topic_id": "unseen"}, "invalid_topic"),
        ({"multiple_topics": True}, "multiple_topics"),
    ],
)
def test_invalid_or_multi_topic_assignment_cannot_update_memory(changes, reason):
    checked = validate_classification(
        result(summary="must not persist", **changes), message(), [candidate()], []
    )
    assert checked.decision.outcome == "defer"
    assert checked.decision.defer_reason == reason
    assert checked.decision.topic_id is None
    assert checked.decision.summary == ""


def test_valid_assignment_retains_evidence_and_policy_version():
    checked = validate_classification(result(), message(), [candidate()], [])
    assert checked.decision.outcome == "existing"
    assert checked.decision.evidence_message_ids == ["target"]
    assert checked.policy_version == "topic-policy-v3"


def test_identical_title_does_not_force_merge():
    checked = validate_classification(
        result(outcome="new", topic_id=None, title="Mobile login"), message(), [candidate()], []
    )
    assert checked.decision.outcome == "defer"
    assert checked.decision.defer_reason == "duplicate_topic"


async def test_workflow_ranking_retains_followup_evidence_and_original_text():
    from backend.application.agent_workflow import create_topic_workflow

    seen = []

    class Provider:
        model_id = "fake"

        async def classify(self, target, candidates, context):
            seen.append((target.content, candidates))
            return result(outcome="defer", topic_id=None, defer_reason="ambiguous")

    target = message("ok")
    context = [
        ContextMessage(
            "later",
            "a",
            "A",
            datetime.now(UTC),
            "followup_clarification",
            "ý mình là beta release schedule",
        )
    ]
    beta = TopicCandidate(id="beta", title="Beta release schedule", description="", status="ACTIVE")
    await create_topic_workflow(Provider()).ainvoke(
        {"message": target, "candidates": [candidate(), beta], "context": context}
    )
    assert seen[0][0] == "ok"
    assert seen[0][1][0].id == "beta"
    assert seen[0][1][0].evidence != "local_zero_overlap_fallback"
