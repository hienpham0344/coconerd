from datetime import UTC, datetime

import pytest

from backend.application.contracts import TopicCandidate
from backend.application.topic_retriever import retrieve_topic_candidates
from backend.domain.entities import ConversationMessage


def _message(content: str) -> ConversationMessage:
    return ConversationMessage(
        guild_id="guild-1",
        channel_id="channel-1",
        message_id="message-1",
        author_id="user-1",
        author_name="User",
        content=content,
        created_at=datetime.now(UTC),
    )


def _candidate(
    topic_id: str,
    title: str,
    *,
    description: str = "",
    summary: dict[str, object] | None = None,
    evidence: str = "",
    status: str = "ACTIVE",
) -> TopicCandidate:
    return TopicCandidate(
        id=topic_id,
        title=title,
        description=description,
        status=status,
        summary=summary or {},
        evidence=evidence,
    )


def test_retriever_ranks_title_above_summary_matches():
    title_match = _candidate("title", "Payment gateway migration")
    summary_match = _candidate(
        "summary", "Other topic", summary={"overview": "Discuss payment gateway migration"}
    )

    result = retrieve_topic_candidates(
        _message("payment gateway migration"), [summary_match, title_match]
    )

    assert [candidate.id for candidate in result] == ["title", "summary"]


def test_retriever_keeps_direct_reply_first():
    recent = _candidate("recent", "Unrelated")
    reply = _candidate("reply", "Old topic", evidence="direct_reply_target")

    result = retrieve_topic_candidates(_message("unrelated subject"), [recent, reply])

    assert result[0].id == "reply"
    assert result[0].evidence == "direct_reply_target"


def test_retriever_uses_recent_fallback_for_zero_overlap():
    candidates = [_candidate(str(index), f"Recent topic {index}") for index in range(7)]

    result = retrieve_topic_candidates(_message("🪐 unrelated jargon"), candidates)

    assert [candidate.id for candidate in result] == ["0", "1", "2", "3", "4"]
    assert result[0].evidence == "local_zero_overlap_fallback"


def test_retriever_handles_unicode_and_candidate_limit():
    candidates = [_candidate(str(index), f"Candidate {index}") for index in range(60)]
    candidates[0] = _candidate("viet", "Thảo luận tiếng Việt")
    candidates[2] = _candidate("closed", "Thảo luận tiếng Việt", status="CLOSED")
    candidates.append(_candidate("outside-bound", "Thảo luận tiếng Việt"))

    result = retrieve_topic_candidates(_message("thảo luận tiếng Việt"), candidates)

    assert result[0].id == "viet"
    assert len(result) == 5
    result_ids = {candidate.id for candidate in result}
    assert "outside-bound" not in result_ids
    assert "closed" not in result_ids


def test_retriever_compacts_candidate_context():
    candidate = _candidate(
        "topic",
        "T" * 140,
        description="D" * 260,
        summary={
            "overview": "O" * 450,
            "proposals": ["P" * 130] * 5,
            "decisions": ["Decision"] * 5,
            "private_extra": "drop this field",
        },
    )

    result = retrieve_topic_candidates(_message("topic discussion"), [candidate])

    compacted = result[0]
    assert len(compacted.title) == 120
    assert len(compacted.description) == 240
    assert len(compacted.summary["overview"]) == 400
    assert len(compacted.summary["proposals"]) == 3
    assert len(compacted.summary["proposals"][0]) == 120
    assert "private_extra" not in compacted.summary


@pytest.mark.parametrize(
    "query,title",
    [
        ("persistent storage engine", "Cơ sở dữ liệu"),
        ("sign in", "Đăng nhập"),
        ("thanh toán", "Payment"),
        ("hạn chót", "Deadline"),
    ],
)
def test_bounded_domain_paraphrases_retrieve_older_candidate(query, title):
    candidates = [_candidate(str(i), f"Unrelated {i}") for i in range(6)]
    candidates.append(_candidate("gold", title))
    ranked = retrieve_topic_candidates(_message(query), candidates)
    assert ranked[0].id == "gold"


def test_domain_expansion_keeps_project_and_platform_distinctions():
    ranked = retrieve_topic_candidates(
        _message("Atlas mobile sign in"),
        [_candidate("other", "Boreal web login"), _candidate("gold", "Atlas mobile login")],
    )
    assert ranked[0].id == "gold"


def test_compact_memory_exposes_newest_facts_within_existing_bounds():
    recent = "Newest schedule: Friday"
    candidate = _candidate(
        "t",
        "Atlas",
        summary={
            "overview": "Old background " * 50 + recent,
            "decisions": [f"Fact {i}" for i in range(6)],
        },
    )
    summary = retrieve_topic_candidates(_message("Atlas"), [candidate])[0].summary
    assert recent in summary["overview"]
    assert len(summary["overview"]) <= 400
    assert summary["decisions"] == ["Fact 3", "Fact 4", "Fact 5"]


def test_search_index_keeps_recent_facts_when_memory_grows():
    from backend.application.topic_terms import weighted_topic_terms

    terms = weighted_topic_terms(
        "Atlas",
        "",
        {
            "overview": "Earlier planning. " * 600 + "Nimbus milestone",
            "decisions": [f"Previous item {i}" for i in range(25)] + ["Nebula rollout"],
        },
    )
    assert "nebula" in terms
    assert "nimbus" in terms
