"""Pure reduction of topic facts; replacement requires a known fact and source quote."""

import unicodedata

from backend.application.contracts import TopicDecision

MEMORY_LIST_FIELDS = ("proposals", "decisions", "open_questions", "action_items")


class InvalidMemoryUpdate(ValueError):
    """A model tried to replace unseen memory or cited text outside the target."""


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def _facts(previous: dict[str, object]) -> dict[str, list[str]]:
    overview = previous.get("overview", "")
    facts = {"overview": _unique(overview.splitlines()) if isinstance(overview, str) else []}
    for field in MEMORY_LIST_FIELDS:
        values = previous.get(field, [])
        facts[field] = (
            _unique([value for value in values if isinstance(value, str)])
            if isinstance(values, list)
            else []
        )
    return facts


def validate_memory_replacements(
    previous: dict[str, object], decision: TopicDecision, source_text: str
) -> None:
    facts = _facts(previous)
    seen = set()
    normalized_source = unicodedata.normalize("NFC", source_text)
    for change in decision.memory_replacements:
        previous_fact = change.previous.strip()
        replacement_fact = change.replacement.strip() if change.replacement is not None else None
        quote = unicodedata.normalize("NFC", change.quote.strip())
        key = (change.field, previous_fact)
        if (
            decision.outcome != "existing"
            or key in seen
            or not previous_fact
            or previous_fact not in facts[change.field]
            or not quote
            or quote not in normalized_source
            or (change.replacement is not None and not replacement_fact)
        ):
            raise InvalidMemoryUpdate(
                "Memory replacement lacks a unique known fact or source quote"
            )
        raw_additions = (
            decision.summary.splitlines()
            if change.field == "overview"
            else getattr(decision, change.field)
        )
        additions = [item.strip() for item in raw_additions if item.strip()]
        if previous_fact in additions and replacement_fact != previous_fact:
            raise InvalidMemoryUpdate("A superseded fact cannot also be reintroduced")
        seen.add(key)


def merge_topic_memory(
    previous: dict[str, object],
    decision: TopicDecision,
    source_text: str,
    *,
    topic_id: str,
    title: str,
    description: str = "",
) -> dict[str, object]:
    validate_memory_replacements(previous, decision, source_text)
    facts = _facts(previous)
    for change in decision.memory_replacements:
        previous_fact = change.previous.strip()
        facts[change.field] = [item for item in facts[change.field] if item != previous_fact]
        if change.replacement is not None:
            if change.field == "overview":
                facts[change.field].extend(change.replacement.splitlines())
            else:
                facts[change.field].append(change.replacement.strip())
    facts["overview"].extend(decision.summary.splitlines())
    if not previous and not facts["overview"] and description.strip():
        facts["overview"] = description.splitlines()
    for field in MEMORY_LIST_FIELDS:
        facts[field].extend(getattr(decision, field))
    return {
        "topic_id": topic_id,
        "title": title,
        "overview": "\n".join(_unique(facts["overview"])),
        **{field: _unique(facts[field]) for field in MEMORY_LIST_FIELDS},
    }
