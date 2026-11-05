from datetime import UTC, datetime

from sqlalchemy import select

from backend.application.contracts import ClassificationResult, TopicDecision
from backend.application.services.messages import process_message_record
from backend.domain.entities import ConversationMessage
from backend.infrastructure.database.models import TopicRecord, TopicSummaryRecord
from backend.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork


class MemoryProvider:
    model_id = "synthetic-memory-test"

    async def classify(self, message, candidates, context):
        if message.message_id == "first":
            decision = TopicDecision(
                outcome="new",
                title="Atlas",
                confidence=0.9,
                reason="new project",
                summary="Lan phụ trách QA.\nPhát hành thứ Năm",
                decisions=["Phát hành thứ Năm"],
                evidence_message_ids=[message.message_id],
            )
        else:
            decision = TopicDecision(
                outcome="existing",
                topic_id=candidates[0].id,
                confidence=0.9,
                reason="explicit schedule correction",
                summary="Thanh phụ trách API.",
                evidence_message_ids=[message.message_id],
                memory_replacements=[
                    {
                        "field": field,
                        "previous": "Phát hành thứ Năm",
                        "replacement": "Phát hành thứ Sáu",
                        "quote": "Dời phát hành sang thứ Sáu",
                    }
                    for field in ("overview", "decisions")
                ],
            )
        return ClassificationResult(decision=decision, model_id=self.model_id, latency_ms=0)


async def test_worker_projection_keeps_facts_and_history_while_replacing_decision(database_factory):
    async with database_factory() as session:
        uow = SqlAlchemyUnitOfWork(session)
        for mid, content in [
            ("first", "Atlas: Lan phụ trách QA. Phát hành thứ Năm."),
            ("second", "Atlas: Dời phát hành sang thứ Sáu. Thanh phụ trách API."),
        ]:
            message = ConversationMessage("g", "c", mid, "u", "User", content, datetime.now(UTC))
            record, _ = await uow.messages.ingest(message, 3)
            await uow.commit()
            result = await process_message_record(uow, record.id, MemoryProvider())
            assert result.outcome in {"new", "existing"}
            await uow.commit()
        summaries = list(
            await session.scalars(select(TopicSummaryRecord).order_by(TopicSummaryRecord.version))
        )
        assert len(summaries) == 2
        assert summaries[0].data["decisions"] == ["Phát hành thứ Năm"]
        current = summaries[-1].data
        assert current["decisions"] == ["Phát hành thứ Sáu"]
        assert "Lan phụ trách QA." in current["overview"]
        assert "Thanh phụ trách API." in current["overview"]
        assert "Phát hành thứ Năm" not in current["overview"]
        assert summaries[-1].source_message_ids == ["first", "second"]
        assert len(list(await session.scalars(select(TopicRecord)))) == 1


class ProjectionProvider:
    model_id = "synthetic-projection"

    def __init__(self, mode):
        self.mode = mode

    async def classify(self, message, candidates, context):
        initial = message.message_id == "first"
        title = "Atlas"
        changes = {}
        summary = "A" * 450 if self.mode == "truncated" and initial else "Atlas launch Friday"
        if not initial:
            summary = "" if self.mode in {"noop", "dead-create"} else "Lan handles QA"
            if self.mode == "truncated":
                changes["memory_replacements"] = [
                    {
                        "field": "overview",
                        "previous": "A" * 400,
                        "replacement": "Changed",
                        "quote": "Atlas correction",
                    }
                ]
        return ClassificationResult(
            model_id=self.model_id,
            latency_ms=0,
            decision=TopicDecision(
                outcome="new" if initial else "existing",
                title=title if initial else None,
                topic_id=None if initial else candidates[0].id,
                confidence=0.9,
                reason="explicit",
                summary=summary,
                evidence_message_ids=[message.message_id],
                **changes,
            ),
        )


async def _process(uow, mid, provider):
    message = ConversationMessage("g", "c", mid, "u", "User", "Atlas correction", datetime.now(UTC))
    record, _ = await uow.messages.ingest(message, 3)
    await uow.commit()
    result = await process_message_record(uow, record.id, provider)
    await uow.commit()
    return result


async def test_noop_memory_emits_no_extra_summary_version_or_summary_action(database_factory):
    from backend.infrastructure.database.models import DiscordActionRecord

    async with database_factory() as session:
        uow = SqlAlchemyUnitOfWork(session)
        provider = ProjectionProvider("noop")
        await _process(uow, "first", provider)
        await _process(uow, "second", provider)
        assert len(list(await session.scalars(select(TopicSummaryRecord)))) == 1
        actions = list(await session.scalars(select(DiscordActionRecord)))
        assert [a.action_type for a in actions].count("UPSERT_SUMMARY") == 1
        assert [a.action_type for a in actions].count("APPEND_MESSAGE") == 1


async def test_chatter_does_not_create_conversation_or_discord_actions(database_factory):
    from backend.infrastructure.database.models import DiscordActionRecord

    class ChatterProvider(ProjectionProvider):
        async def classify(self, *args):
            result = await super().classify(*args)
            result.decision.is_noteworthy = False
            return result

    async with database_factory() as session:
        uow = SqlAlchemyUnitOfWork(session)
        result = await _process(uow, "first", ChatterProvider("noop"))
        assert result.outcome == "irrelevant"
        assert list(await session.scalars(select(TopicRecord))) == []
        assert list(await session.scalars(select(TopicSummaryRecord))) == []
        assert list(await session.scalars(select(DiscordActionRecord))) == []


async def test_initial_conversation_action_already_contains_its_note(database_factory):
    from backend.infrastructure.database.models import DiscordActionRecord

    async with database_factory() as session:
        uow = SqlAlchemyUnitOfWork(session)
        await _process(uow, "first", ProjectionProvider("noop"))
        create = await session.scalar(
            select(DiscordActionRecord).where(DiscordActionRecord.action_type == "CREATE_THREAD")
        )
        assert create.payload["summary"]["overview"] == "Atlas launch Friday"


async def test_truncated_memory_reference_cannot_mutate_full_stored_memory(database_factory):
    from backend.infrastructure.database.models import DiscordActionRecord

    async with database_factory() as session:
        uow = SqlAlchemyUnitOfWork(session)
        provider = ProjectionProvider("truncated")
        await _process(uow, "first", provider)
        result = await _process(uow, "second", provider)
        assert (result.outcome, result.defer_reason) == ("defer", "invalid_evidence")
        assert len(list(await session.scalars(select(DiscordActionRecord)))) == 2
        assert len(list(await session.scalars(select(TopicSummaryRecord)))) == 1


async def test_paused_topic_keeps_db_memory_current_without_dispatching_actions(database_factory):
    from backend.infrastructure.database.models import DiscordActionRecord

    async with database_factory() as session:
        uow = SqlAlchemyUnitOfWork(session)
        provider = ProjectionProvider("paused")
        await _process(uow, "first", provider)
        topic = await session.scalar(select(TopicRecord))
        topic.sync_paused = True
        await session.commit()
        await _process(uow, "second", provider)
        assert len(list(await session.scalars(select(DiscordActionRecord)))) == 2
        assert len(list(await session.scalars(select(TopicSummaryRecord)))) == 2


async def test_new_message_does_not_silently_retry_dead_create_thread(database_factory):
    from backend.infrastructure.database.models import DiscordActionRecord

    async with database_factory() as session:
        uow = SqlAlchemyUnitOfWork(session)
        provider = ProjectionProvider("dead-create")
        await _process(uow, "first", provider)
        create = await session.scalar(
            select(DiscordActionRecord).where(DiscordActionRecord.action_type == "CREATE_THREAD")
        )
        create.status, create.attempt_count = "DEAD", 5
        await session.commit()
        await _process(uow, "second", provider)
        actions = list(await session.scalars(select(DiscordActionRecord)))
        assert [a.action_type for a in actions].count("CREATE_THREAD") == 1
        assert (
            next(a for a in actions if a.action_type == "APPEND_MESSAGE").dependency_id == create.id
        )
