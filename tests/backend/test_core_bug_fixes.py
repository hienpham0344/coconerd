"""Tests for bug fixes in core, worker, domain, database, and API layers."""

import unicodedata
from datetime import UTC, datetime, timedelta, timezone

import pytest

ADMIN = {"X-Admin-API-Key": "admin-test-key"}
BOT = {"X-API-Key": "bot-test-key"}
NO_AUTH: dict[str, str] = {}


@pytest.mark.asyncio
async def test_mark_dormant_includes_resumed_topics(database_factory):
    """mark_dormant_topics must transition both ACTIVE and RESUMED topics."""
    from sqlalchemy import select

    from backend.application.services.topics import mark_dormant_topics
    from backend.domain.enums import TopicStatus
    from backend.infrastructure.database.models import TopicRecord
    from backend.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork

    cutoff = datetime.now(UTC) - timedelta(days=1)

    async with database_factory() as session:
        old_at = cutoff - timedelta(hours=1)
        session.add_all(
            [
                TopicRecord(
                    id="t-active",
                    guild_id="g1",
                    title="Active Topic",
                    description="",
                    status=TopicStatus.ACTIVE.value,
                    last_activity_at=old_at,
                ),
                TopicRecord(
                    id="t-resumed",
                    guild_id="g1",
                    title="Resumed Topic",
                    description="",
                    status=TopicStatus.RESUMED.value,
                    last_activity_at=old_at,
                ),
            ]
        )
        await session.commit()

    async with database_factory() as session:
        uow = SqlAlchemyUnitOfWork(session)
        count = await mark_dormant_topics(uow, dormant_after_days=0)

    assert count == 2

    async with database_factory() as session:
        statuses = set(
            await session.scalars(select(TopicRecord.status).where(TopicRecord.guild_id == "g1"))
        )
    assert statuses == {TopicStatus.DORMANT.value}


def test_compact_overview_truncates_at_line_boundaries():
    """_compact must keep whole lines and never cut mid-line within 400 chars."""
    from backend.application.topic_retriever import TopicCandidate, _compact

    lines = [f"Line {i:02d}: {'x' * 30}" for i in range(20)]
    overview = "\n".join(lines)

    candidate = TopicCandidate(
        id="t1",
        title="T",
        description="",
        status="ACTIVE",
        summary={"overview": overview, "decisions": [], "action_items": [], "open_questions": []},
    )
    result = _compact(candidate)
    compacted_overview = result.summary.get("overview", "")

    assert len(compacted_overview) <= 400
    assert lines[-1] in compacted_overview
    for line in compacted_overview.splitlines():
        assert line in lines


def test_validate_memory_nfc_quote_normalization():
    """validate_memory_replacements accepts NFD quote against NFC source_text."""
    from backend.application.contracts import MemoryReplacement, TopicDecision
    from backend.application.topic_memory import validate_memory_replacements

    old_fact = "Phát hành thứ Năm"
    nfc_old_fact = unicodedata.normalize("NFC", old_fact)
    nfd_quote = unicodedata.normalize("NFD", "Phát hành thứ Năm")
    source_text = unicodedata.normalize("NFC", "Dời lịch. Phát hành thứ Năm đã thay đổi.")

    previous = {
        "decisions": [nfc_old_fact],
        "overview": "",
        "action_items": [],
        "open_questions": [],
    }
    decision = TopicDecision(
        outcome="existing",
        confidence=0.9,
        reason="Updated release schedule",
        topic_id="t1",
        evidence_message_ids=["m1"],
        memory_replacements=[
            MemoryReplacement(
                field="decisions",
                previous=f"  {nfc_old_fact}  ",
                replacement="  Phát hành thứ Sáu  ",
                quote=nfd_quote,
            )
        ],
    )
    validate_memory_replacements(previous, decision, source_text)


def test_acks_bare_reference_with_reply_context_does_not_assert_new_facts():
    """An unclarified ACK with reply_ancestor context cannot create a new topic or assert facts."""
    from backend.application.contracts import ClassificationResult, TopicCandidate, TopicDecision
    from backend.application.decision_policy import validate_classification
    from backend.application.read_models import ContextMessage
    from backend.domain.entities import ConversationMessage

    msg = ConversationMessage(
        guild_id="g1",
        channel_id="c1",
        message_id="m2",
        author_id="u1",
        author_name="User",
        content="ok",
        created_at=datetime.now(UTC),
        reply_to_message_id="m1",
    )
    reply_ctx = [
        ContextMessage(
            message_id="m1",
            author_id="u2",
            author_name="Lead",
            created_at=datetime.now(UTC),
            relation="reply_ancestor",
            content="Ship beta Thursday?",
        )
    ]
    candidate = TopicCandidate(id="beta", title="Beta", description="", status="ACTIVE")
    raw = ClassificationResult(
        decision=TopicDecision(
            outcome="existing",
            topic_id="beta",
            confidence=0.9,
            reason="Ack reply",
            summary="Hallucinated summary",
            decisions=["Hallucinated decision"],
            evidence_message_ids=["m2", "m1"],
        ),
        model_id="test",
        latency_ms=1,
    )
    checked = validate_classification(raw, msg, [candidate], reply_ctx)
    assert checked.decision.outcome == "existing"
    assert checked.decision.summary == ""
    assert checked.decision.decisions == []


@pytest.mark.asyncio
async def test_new_discovery_and_admin_endpoints(api_client):
    """Verify guild list, settings read, guild topics list, and review queue endpoints."""
    body = {
        "enabled": True,
        "allowed_channel_ids": ["ch1"],
        "output_channel_id": "out1",
        "retention_days": 30,
    }
    put_r = await api_client.put("/api/v1/admin/guilds/g1/settings", headers=ADMIN, json=body)
    assert put_r.status_code == 200

    list_r = await api_client.get("/api/v1/admin/guilds", headers=ADMIN)
    assert list_r.status_code == 200
    assert any(item["guild_id"] == "g1" for item in list_r.json()["items"])

    for headers in (ADMIN, BOT):
        get_r = await api_client.get("/api/v1/guilds/g1/settings", headers=headers)
        assert get_r.status_code == 200
        assert get_r.json()["output_channel_id"] == "out1"

        topics_r = await api_client.get("/api/v1/guilds/g1/topics", headers=headers)
        assert topics_r.status_code == 200
        assert "items" in topics_r.json()

    reviews_r = await api_client.get("/api/v1/guilds/g1/reviews", headers=ADMIN)
    assert reviews_r.status_code == 200
    assert "deferred_messages" in reviews_r.json()
    assert "dead_actions" in reviews_r.json()


@pytest.mark.asyncio
async def test_dashboard_credential_non_utc_offset_normalized(api_client):
    """Dashboard credential expiry with non-UTC offset (+07:00) is normalized to UTC."""
    tz_plus_7 = timezone(timedelta(hours=7))
    expires = (datetime.now(tz_plus_7) + timedelta(minutes=4)).isoformat()
    path = f"/api/v1/admin/web/credentials/oauth/{'d' * 64}"
    put_r = await api_client.put(
        path,
        headers=ADMIN,
        json={"payload": "encrypted-state", "expires_at": expires},
    )
    assert put_r.status_code == 200
    get_r = await api_client.get(path, headers=ADMIN)
    assert get_r.status_code == 200
    assert get_r.json()["payload"] == "encrypted-state"
