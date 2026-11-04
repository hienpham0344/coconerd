"""Memory updates preserve facts and require explicit grounded supersession."""

from copy import deepcopy

import pytest

from backend.application.contracts import TopicDecision


def decision(**changes):
    return TopicDecision(
        outcome="existing", topic_id="t", confidence=0.9, reason="same project", **changes
    )


def merge(previous, value, text="Dời phát hành sang thứ Sáu."):
    from backend.application.topic_memory import merge_topic_memory

    return merge_topic_memory(previous, value, text, topic_id="t", title="Atlas")


def test_unrelated_update_preserves_previous_overview_and_does_not_mutate_history():
    previous = {"overview": "Lan phụ trách QA.", "decisions": ["Dùng SQLite"]}
    snapshot = deepcopy(previous)
    updated = merge(previous, decision(summary="Phát hành thứ Sáu."))
    assert "Lan phụ trách QA." in updated["overview"]
    assert "Phát hành thứ Sáu." in updated["overview"]
    assert updated["decisions"] == ["Dùng SQLite"]
    assert previous == snapshot


@pytest.mark.parametrize("field", ["overview", "decisions", "action_items"])
def test_explicit_grounded_replacement_removes_old_active_fact(field):
    previous = {"overview": "Lan phụ trách QA.", "decisions": [], "action_items": []}
    previous[field] = "Phát hành thứ Năm" if field == "overview" else ["Phát hành thứ Năm"]
    snapshot = deepcopy(previous)
    updated = merge(
        previous,
        decision(
            memory_replacements=[
                {
                    "field": field,
                    "previous": "Phát hành thứ Năm",
                    "replacement": "Phát hành thứ Sáu",
                    "quote": "Dời phát hành sang thứ Sáu",
                }
            ]
        ),
    )
    assert "Phát hành thứ Năm" not in updated[field]
    assert "Phát hành thứ Sáu" in updated[field]
    assert previous == snapshot


@pytest.mark.parametrize(
    "previous,quote",
    [("unknown fact", "Dời phát hành"), ("Phát hành thứ Năm", "made up evidence")],
)
def test_unseen_fact_or_quote_cannot_replace_memory(previous, quote):
    from backend.application.topic_memory import InvalidMemoryUpdate

    with pytest.raises(InvalidMemoryUpdate):
        merge(
            {"decisions": ["Phát hành thứ Năm"]},
            decision(
                memory_replacements=[
                    {
                        "field": "decisions",
                        "previous": previous,
                        "replacement": None,
                        "quote": quote,
                    }
                ]
            ),
        )


def test_repeated_update_is_a_noop_and_cancelled_fact_is_removed():
    value = decision(summary="Lan phụ trách QA.", decisions=["Dùng SQLite"])
    previous = merge({}, value)
    assert merge(previous, value) == previous
    cancelled = merge(
        previous,
        decision(
            memory_replacements=[
                {
                    "field": "decisions",
                    "previous": "Dùng SQLite",
                    "replacement": None,
                    "quote": "Hủy quyết định dùng SQLite",
                }
            ]
        ),
        "Hủy quyết định dùng SQLite.",
    )
    assert cancelled["decisions"] == []


def test_conflicting_replacements_are_rejected():
    from backend.application.topic_memory import InvalidMemoryUpdate

    change = {
        "field": "decisions",
        "previous": "Phát hành thứ Năm",
        "replacement": "Phát hành thứ Sáu",
        "quote": "Dời phát hành",
    }
    with pytest.raises(InvalidMemoryUpdate):
        merge(
            {"decisions": ["Phát hành thứ Năm"]},
            decision(memory_replacements=[change, {**change, "replacement": None}]),
        )
