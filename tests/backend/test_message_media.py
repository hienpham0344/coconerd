from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from backend.application.contracts import TopicCandidate
from backend.application.decision_policy import classify_locally
from backend.domain.entities import ConversationMessage
from backend.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork
from backend.presentation.api.schemas import MessageIngestRequest

ATTACHMENT = {
    "id": "55",
    "filename": "photo.png",
    "url": "https://cdn.discordapp.com/attachments/1/55/photo.png",
    "content_type": "image/png",
    "size": 12,
    "spoiler": False,
}


def media_message(**changes):
    return ConversationMessage(
        **{
            "guild_id": "g",
            "channel_id": "c",
            "message_id": "m",
            "author_id": "u",
            "author_name": "Lan",
            "content": "",
            "created_at": datetime.now(UTC),
            "attachments": [dict(ATTACHMENT)],
            **changes,
        }
    )


def test_ingest_contract_preserves_attachments_and_empty_caption():
    body = MessageIngestRequest(
        **{
            "guild_id": "g",
            "channel_id": "c",
            "message_id": "m",
            "author_id": "u",
            "author_name": "Lan",
            "content": "",
            "created_at": datetime.now(UTC),
            "attachments": [ATTACHMENT],
        }
    )
    assert body.model_dump(mode="json")["attachments"] == [ATTACHMENT]
    assert body.content == ""


async def test_attachments_survive_persistence(database_factory):
    message = media_message()
    async with database_factory() as session:
        uow = SqlAlchemyUnitOfWork(session)
        first, inserted = await uow.messages.ingest(message, 5)
        await uow.commit()
        assert inserted
    async with database_factory() as session:
        stored = await SqlAlchemyUnitOfWork(session).messages.get(first.id)
        assert stored.content == ""
        assert stored.attachments == [ATTACHMENT]


@pytest.mark.parametrize("anchored", [False, True])
def test_attachment_only_uses_explicit_reply_or_generic_topic_without_model(anchored):
    candidates = (
        [
            TopicCandidate(
                id="topic",
                title="Ăn trưa",
                description="",
                status="ACTIVE",
                evidence="direct_reply_target",
            )
        ]
        if anchored
        else []
    )
    result = classify_locally(
        media_message(reply_to_message_id="parent" if anchored else None), [], candidates
    )
    assert result.decision.outcome == ("existing" if anchored else "new")
    assert result.decision.topic_id == ("topic" if anchored else None)
    assert result.decision.summary == ""
    assert result.decision.evidence_message_ids == ["m"]
    assert result.model_calls == 0


def test_generic_attachment_topic_title_is_readable_and_not_a_source_identifier():
    candidate = TopicCandidate(
        id="old", title="Tệp đính kèm từ Lan", description="", status="ACTIVE"
    )
    result = classify_locally(media_message(message_id="987654321"), [], [candidate])
    assert "987654321" not in result.decision.title
    assert result.decision.title != candidate.title


async def test_image_only_pipeline_preserves_history_and_reply_topic(api_client, database_factory):
    from backend.config import Settings
    from backend.worker import ConversationWorker

    configured = await api_client.put(
        "/api/v1/admin/guilds/g/settings",
        headers={"X-Admin-API-Key": "admin-test-key"},
        json={"enabled": True, "allowed_channel_ids": ["c"], "output_channel_id": "output"},
    )
    assert configured.status_code == 200
    worker = ConversationWorker(
        Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:")
    )
    unused_engine = worker.session_factory.kw["bind"]
    worker.session_factory = database_factory
    worker._provider_for_guild = AsyncMock(side_effect=AssertionError("Media must not call vision"))
    try:
        for identifier, parent in [("m", None), ("reply", "m")]:
            body = MessageIngestRequest(
                guild_id="g",
                channel_id="c",
                message_id=identifier,
                author_id="u",
                author_name="Lan",
                content="",
                created_at=datetime.now(UTC),
                reply_to_message_id=parent,
                attachments=[ATTACHMENT],
            )
            response = await api_client.post(
                "/api/v1/messages",
                headers={"X-API-Key": "bot-test-key"},
                json=body.model_dump(mode="json"),
            )
            assert response.status_code == 202
            assert await worker.process_once()
        response = await api_client.post(
            "/api/v1/actions/claim",
            headers={"X-API-Key": "bot-test-key"},
            json={"worker_id": "media-bot", "limit": 1},
        )
        assert response.status_code == 200
        item = response.json()[0]
        assert item["payload"]["source_attachments"] == [ATTACHMENT]
        history = await api_client.get(
            f"/api/v1/topics/{item['topic_id']}/messages",
            params={"guild_id": "g"},
            headers={"X-API-Key": "bot-test-key"},
        )
        assert history.status_code == 200
        from sqlalchemy import select

        from backend.infrastructure.database.models import AIDecisionRecord

        async with database_factory() as session:
            decisions = list(await session.scalars(select(AIDecisionRecord.payload)))
        assert {item["message_id"] for item in history.json()["items"]} == {"m", "reply"}, [
            (
                item["decision"]["outcome"],
                item["decision"].get("topic_id"),
                item["candidate_topic_ids"],
            )
            for item in decisions
        ]
        assert all(item["attachments"] == [ATTACHMENT] for item in history.json()["items"])
        worker._provider_for_guild.assert_not_awaited()
    finally:
        await unused_engine.dispose()
