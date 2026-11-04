"""Lexical normalization for retrieval only; never modify user content."""

import re
import unicodedata

from backend.application.language_normalization import analyze_language

_STOPWORDS = set(
    [
        "a",
        "an",
        "and",
        "are",
        "for",
        "in",
        "is",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
        "we",
        "our",
        "la",
        "va",
        "cua",
        "cho",
        "minh",
        "toi",
        "ban",
        "mot",
        "nhung",
        "cac",
    ]
)
_ALIASES = {"db": "database", "csdl": "database", "auth": "authentication"}


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold().replace("đ", "d"))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(re.findall(r"[^\W_]+", value))


def search_terms(value: str, limit: int = 24) -> list[str]:
    original = value[:8000]
    suggested = analyze_language(original).retrieval_text
    normalized = normalize_text(f"{suggested} {original}")
    normalized = normalized.replace("co so du lieu", "database").replace("dang nhap", "login")
    return list(
        dict.fromkeys(
            _ALIASES.get(term, term) for term in normalized.split() if term not in _STOPWORDS
        )
    )[:limit]


def weighted_topic_terms(
    title: str, description: str, summary: dict[str, object]
) -> dict[str, float]:
    texts = [(title, 3.0), (description, 1.5), (str(summary.get("overview", "")), 0.75)]
    for field in ("proposals", "decisions", "open_questions", "action_items"):
        items = summary.get(field, [])
        if isinstance(items, list):
            texts.append((" ".join(item for item in items[:20] if isinstance(item, str)), 0.75))
    weights: dict[str, float] = {}
    for value, weight in texts:
        for term in search_terms(value, limit=300):
            weights[term] = max(weights.get(term, 0), weight)
    return weights
