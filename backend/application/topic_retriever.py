"""Bounded, deterministic local shortlist for topic classification."""

import re

from backend.application.contracts import TopicCandidate
from backend.domain.entities import ConversationMessage

_MAX_SOURCE_CANDIDATES = 30
_MAX_CANDIDATES = 5
_FIELD_WEIGHTS = (("title", 3.0), ("description", 1.5))
_SUMMARY_LISTS = ("proposals", "decisions", "open_questions", "action_items")
_ELIGIBLE_STATUSES = {"ACTIVE", "DORMANT", "RESUMED"}
_TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)


def _tokens(value: str) -> set[str]:
    return set(_TOKEN_PATTERN.findall(value.casefold()))


def _compact(candidate: TopicCandidate) -> TopicCandidate:
    summary = candidate.summary
    compact_summary: dict[str, object] = {}
    overview = summary.get("overview")
    if isinstance(overview, str):
        compact_summary["overview"] = overview[:400]
    for key in _SUMMARY_LISTS:
        values = summary.get(key)
        if isinstance(values, list):
            compact_summary[key] = [value[:120] for value in values[:3] if isinstance(value, str)]
    return candidate.model_copy(
        update={
            "title": candidate.title[:120],
            "description": candidate.description[:240],
            "summary": compact_summary,
        }
    )


def _score(message_tokens: set[str], candidate: TopicCandidate) -> float:
    if not message_tokens:
        return 0.0
    title_tokens = _tokens(candidate.title)
    description_tokens = _tokens(candidate.description)
    summary_tokens = _tokens(str(candidate.summary.get("overview", "")))
    for key in _SUMMARY_LISTS:
        values = candidate.summary.get(key)
        if isinstance(values, list):
            summary_tokens.update(_tokens(" ".join(v for v in values if isinstance(v, str))))
    total = 0.0
    for token in message_tokens:
        total += max(
            3.0 if token in title_tokens else 0.0,
            1.5 if token in description_tokens else 0.0,
            0.75 if token in summary_tokens else 0.0,
        )
    return total / (3.0 * len(message_tokens))


def retrieve_topic_candidates(
    message: ConversationMessage,
    candidates: list[TopicCandidate],
    limit: int = _MAX_CANDIDATES,
) -> list[TopicCandidate]:
    """Rank up to 30 eligible guild candidates and return compact cards.

    The caller supplies the guild-scoped repository results. Candidate input order is
    recent-first, so it also provides a deterministic fallback for weak lexical matches.
    """
    if limit <= 0:
        return []
    bounded = [
        candidate
        for candidate in candidates[:_MAX_SOURCE_CANDIDATES]
        if candidate.status.upper() in _ELIGIBLE_STATUSES
    ]
    if not bounded:
        return []

    limit = min(limit, _MAX_CANDIDATES)
    direct_reply = next(
        (candidate for candidate in bounded if candidate.evidence == "direct_reply_target"),
        None,
    )
    message_tokens = _tokens(message.content)
    ranked = sorted(
        bounded,
        key=lambda candidate: -_score(message_tokens, candidate),
    )
    zero_overlap = not message_tokens or _score(message_tokens, ranked[0]) == 0.0
    selected = [direct_reply] if direct_reply is not None else []
    selected.extend(candidate for candidate in ranked if candidate not in selected)
    shortlist = selected[:limit]
    if zero_overlap:
        shortlist = [
            candidate.model_copy(update={"evidence": "local_zero_overlap_fallback"})
            if candidate.evidence != "direct_reply_target"
            else candidate
            for candidate in shortlist
        ]
    return [_compact(candidate) for candidate in shortlist]
