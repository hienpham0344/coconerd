"""Language hints must aid retrieval without rewriting source evidence."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from backend.application.contracts import TopicCandidate
from backend.application.decision_policy import classify_locally
from backend.application.read_models import ContextMessage
from backend.application.topic_retriever import retrieve_topic_candidates
from backend.application.topic_terms import search_terms
from backend.config import Settings
from backend.domain.entities import ConversationMessage
from backend.infrastructure import meta_provider


def message(content):
    return ConversationMessage("g", "c", "m", "u", "User", content, datetime.now(UTC))


def test_telex_expansion_reaches_topic_retrieval_without_mutating_source():
    target = message("ko ddawng nhaapj dc")
    candidates = [
        TopicCandidate(id=str(i), title=f"Unrelated {i}", description="", status="ACTIVE")
        for i in range(6)
    ]
    candidates.append(
        TopicCandidate(id="login", title="Đăng nhập", description="", status="ACTIVE")
    )
    assert "login" in search_terms(target.content)
    assert retrieve_topic_candidates(target, candidates)[0].id == "login"
    assert target.content == "ko ddawng nhaapj dc"


@pytest.mark.parametrize("content", ["dr do", "DR DO!", "đúng rồi đó", "acp cái này"])
def test_contextless_language_reference_defers_without_calling_model(content):
    result = classify_locally(message(content), [])
    assert result is not None
    assert result.decision.outcome == "defer"
    assert result.decision.defer_reason == "missing_context"
    assert result.model_calls == 0


def test_acknowledgement_with_reply_can_be_interpreted_by_model():
    context = [ContextMessage("parent", "u", "User", datetime.now(UTC), "reply_ancestor", "Beta?")]
    assert classify_locally(message("dr do"), context) is None


async def test_provider_sends_grounded_hints_beside_original_in_one_request(monkeypatch):
    requests = []

    async def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "outcome": "defer",
                                "confidence": 0,
                                "reason": "uncertain",
                            }
                        )
                    )
                )
            ],
            usage=None,
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(meta_provider, "AsyncOpenAI", lambda **kwargs: client)
    settings = Settings(_env_file=None, app_env="test", meta_api_key="test-key")
    target = message("acp cái này")
    await meta_provider.MetaModelProvider(settings).classify(target, [])
    assert len(requests) == 1
    payload = json.loads(requests[0]["messages"][1]["content"])
    assert payload["message"]["content"] == "acp cái này"
    hints = payload["language_hints"]["hints"]
    assert any(hint["surface"] == "acp" and "chấp nhận" in hint["candidates"] for hint in hints)
    assert all(hint["source"] and hint["entry_id"] for hint in hints)


def test_typo_candidates_are_bounded_and_do_not_invent_unknown_word():
    from backend.application.language_normalization import analyze_language

    raw = "toi thays là cáu nnayf onras"
    analysis = analyze_language(raw)
    hints = {hint.surface: hint for hint in analysis.hints}
    assert hints["thays"].candidates == ("thấy",)
    assert hints["nnayf"].candidates == ("này",)
    assert "cáu" not in hints
    assert "onras" not in hints
    assert "onras" in analysis.retrieval_text


def test_ambiguous_abbreviation_keeps_multiple_meanings():
    from backend.application.language_normalization import analyze_language

    analysis = analyze_language("bt")
    assert set(analysis.hints[0].candidates) >= {"biết", "bình thường"}
    assert analysis.retrieval_text == "bt"


@pytest.mark.parametrize(
    "content",
    [
        "`ko ddawng nhaapj`",
        "```python\nko = 'thays'\n```",
        "https://example.org/khum",
        "person@khum.vn",
        "<@1234>",
        "user_thays",
        "./data/khum.json",
        "ACP DC VS",
        "ship this class",
        "cáu",
        "normal text",
        "I took this",
        "took",
        "nays",
    ],
)
def test_code_links_identifiers_and_standard_text_are_not_normalized(content):
    from backend.application.language_normalization import analyze_language

    assert not analyze_language(content).hints


def test_hint_budget_and_unclosed_code_block_are_safe():
    from backend.application.language_normalization import analyze_language

    analysis = analyze_language("ko khum cx mik mn bth ngta ny lun iu zui đc")
    assert 0 < len(analysis.hints) <= 8
    assert not analyze_language("```python\nko thays").hints


def test_search_keeps_original_terms_alongside_suggested_terms():
    assert {"khum", "khong"} <= set(search_terms("khum"))


def test_decomposed_unicode_keeps_exact_source_offsets():
    from backend.application.language_normalization import analyze_language

    raw = "ro\u0300i"
    analysis = analyze_language(raw)
    assert analysis.hints[0].candidates == ("rồi",)
    hint = analysis.hints[0]
    assert raw[hint.start : hint.end] == hint.surface == raw


def test_large_whitespace_does_not_overflow_hint_payload():
    from backend.application.language_normalization import analyze_language

    analysis = analyze_language("dr" + " " * 7900 + "do")
    assert len(json.dumps(analysis.as_payload(), ensure_ascii=False)) < 4000


def test_retrieval_does_not_join_words_across_code_or_punctuation():
    from backend.application.language_normalization import analyze_language

    assert not analyze_language("dr `private` do").needs_context
    assert not analyze_language("dr. do").needs_context


async def test_language_expansion_is_used_by_database_topic_search(database_factory):
    from backend.domain.entities import ConversationTopic
    from backend.infrastructure.database.repositories.topics import TopicRepository

    async with database_factory() as session:
        topics = TopicRepository(session)
        topic = ConversationTopic.create("g", "Đăng nhập")
        await topics.create(topic)
        await session.commit()
        found = await topics.search("g", "ddawng nhaapj")
        assert [item.id for item in found] == [topic.id]


async def test_workflow_persists_hint_provenance_without_creating_false_facts():
    from backend.application.agent_workflow import create_topic_workflow
    from backend.application.services.messages import _classification_payload

    class RejectingProvider:
        model_id = "must-not-run"

        async def classify(self, *args, **kwargs):
            raise AssertionError("unresolved acknowledgements must not call the model")

    target = message("dr do")
    state = await create_topic_workflow(RejectingProvider()).ainvoke(
        {"message": target, "context": [], "candidates": []}
    )
    payload = _classification_payload(state["classification"])
    assert payload["language_hints"]["hints"][0]["source"] == "user-request"
    assert payload["decision"]["summary"] == ""
    assert payload["decision"]["decisions"] == []
    assert target.content == "dr do"


async def test_processing_keeps_raw_message_and_outbox_with_language_audit(database_factory):
    from sqlalchemy import select

    from backend.application.contracts import ClassificationResult, TopicDecision
    from backend.application.services.messages import ingest_message, process_message_record
    from backend.infrastructure.database.models import (
        AIDecisionRecord,
        DiscordActionRecord,
        GuildSettingsRecord,
        MessageRecord,
    )
    from backend.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork

    raw = "ko ddawng nhaapj dc"

    class Provider:
        model_id = "test-language"

        async def classify(self, target, candidates, context):
            assert target.content == raw
            return ClassificationResult(
                decision=TopicDecision(
                    outcome="new",
                    title="Lỗi đăng nhập",
                    confidence=0.9,
                    reason="login issue",
                    evidence_message_ids=[target.message_id],
                ),
                model_id=self.model_id,
                latency_ms=0,
            )

    async with database_factory() as session:
        session.add(
            GuildSettingsRecord(
                guild_id="g",
                enabled=True,
                allowed_channel_ids=["c"],
                retention_days=365,
            )
        )
        await session.commit()
        uow = SqlAlchemyUnitOfWork(session)
        ingested = await ingest_message(uow, message(raw), max_attempts=3)
        await process_message_record(uow, ingested.message_id, Provider())
        await session.commit()
        stored = await session.scalar(select(MessageRecord))
        decision = await session.scalar(select(AIDecisionRecord))
        action = await session.scalar(
            select(DiscordActionRecord).where(DiscordActionRecord.action_type == "CREATE_THREAD")
        )
        assert stored.content == raw
        assert action.payload["source_content"] == raw
        assert decision.payload["language_hints"]["version"] == "vi-language-v1"
        assert decision.payload["language_hints"]["hints"][0]["surface"] == "ko"


@pytest.mark.parametrize("content", ["acp cái này", "dr do"])
def test_bare_reference_can_link_topic_without_inventing_memory_updates(content):
    from backend.application.contracts import ClassificationResult, TopicDecision
    from backend.application.decision_policy import validate_classification

    target = message(content)
    candidates = [
        TopicCandidate(
            id="design",
            title="Thiết kế đăng nhập",
            description="",
            status="ACTIVE",
        )
    ]
    context = [
        ContextMessage(
            "parent",
            "u",
            "User",
            datetime.now(UTC),
            "reply_ancestor",
            "Bản thiết kế màn hình đăng nhập đang chờ duyệt.",
        )
    ]
    # Regression observed in the live API response: a bare reference became approval.
    result = ClassificationResult(
        decision=TopicDecision(
            outcome="existing",
            topic_id="design",
            confidence=0.9,
            reason="reply context identifies design",
            evidence_message_ids=["m", "parent"],
            summary="Người dùng đã chấp nhận bản thiết kế.",
            decisions=["Chấp nhận bản thiết kế"],
            proposals=["Đổi màu nút"],
            open_questions=["Triển khai khi nào?"],
            action_items=["Triển khai thiết kế"],
        ),
        model_id="test",
        latency_ms=0,
    )
    checked = validate_classification(result, target, candidates, context)
    assert checked.decision.outcome == "existing"
    assert checked.decision.topic_id == "design"
    assert checked.decision.summary == checked.decision.description == ""
    assert not any(
        [
            checked.decision.decisions,
            checked.decision.proposals,
            checked.decision.open_questions,
            checked.decision.action_items,
        ]
    )
    assert result.decision.decisions == ["Chấp nhận bản thiết kế"]


def test_bare_reference_cannot_create_a_new_topic():
    from backend.application.contracts import ClassificationResult, TopicDecision
    from backend.application.decision_policy import validate_classification

    result = ClassificationResult(
        decision=TopicDecision(
            outcome="new",
            title="Chấp nhận",
            confidence=0.9,
            reason="inferred approval",
            evidence_message_ids=["m"],
        ),
        model_id="test",
        latency_ms=0,
    )
    checked = validate_classification(result, message("acp cái này"), [], [])
    assert checked.decision.outcome == "defer"
    assert checked.decision.topic_id is None
    assert checked.decision.title is None
