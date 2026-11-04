"""Bounded lexical retrieval of language hints, never a rewrite of source evidence.

Only a finite, attributed lexicon is searched. Fuzzy matches are limited to one
edit of known Telex forms. Scores are deliberately not presented as confidence.
"""

import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from functools import lru_cache
from importlib.resources import files

_MAX_INPUT = 8000
_MAX_HINTS = 8
_WORDS = re.compile(r"(?:[^\W_]|[\u0300-\u036f])+", re.UNICODE)
_PROTECTED = re.compile(
    r"```[\s\S]*?(?:```|$)|`[^`\n]*(?:`|$)|https?://\S+|www\.\S+|"
    r"[\w.+-]+@[\w.-]+\.[\w-]+|<[^>]*>|"
    r"(?:[\w.-]+/|\./|/)[\w./-]+|\b\w*_\w*\b"
)
_BARE_REFERENCE = re.compile(r"(?:acp|chấp nhận|duyệt) (?:cái này|cai nay|cái đó|cai do)")


@dataclass(frozen=True)
class LanguageHint:
    surface: str
    candidates: tuple[str, ...]
    entry_id: str
    source: str
    method: str
    start: int
    end: int


@dataclass(frozen=True)
class LanguageAnalysis:
    version: str
    hints: tuple[LanguageHint, ...]
    retrieval_text: str
    needs_context: bool

    def as_payload(self) -> dict[str, object]:
        return {"version": self.version, "hints": [asdict(hint) for hint in self.hints]}


@lru_cache(maxsize=1)
def _lexicon() -> dict:
    # Cache the public lexicon, never user messages.
    return json.loads(
        files("backend.application.data").joinpath("vietnamese_lexicon.json").read_text("utf-8")
    )


def _key(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def _one_edit(left: str, right: str) -> bool:
    """A single insertion, deletion, substitution, or adjacent transposition."""
    if abs(len(left) - len(right)) > 1 or left == right:
        return False
    if len(left) == len(right):
        differences = [i for i, (a, b) in enumerate(zip(left, right, strict=True)) if a != b]
        return len(differences) == 1 or (
            len(differences) == 2
            and differences[1] == differences[0] + 1
            and left[differences[0]] == right[differences[1]]
            and left[differences[1]] == right[differences[0]]
        )
    shorter, longer = sorted((left, right), key=len)
    return any(longer[:i] + longer[i + 1 :] == shorter for i in range(len(longer)))


def analyze_language(content: str) -> LanguageAnalysis:
    lexicon = _lexicon()
    bounded = content[:_MAX_INPUT]
    protected = [(match.start(), match.end()) for match in _PROTECTED.finditer(bounded)]
    words = [
        match
        for match in _WORDS.finditer(bounded)
        if not any(start < match.end() and match.start() < end for start, end in protected)
    ]
    variants = [(variant, entry) for entry in lexicon["entries"] for variant in entry["variants"]]
    hints = []
    replacements = []
    index = 0
    while index < len(words) and len(hints) < _MAX_HINTS:
        word = words[index]
        matches = []
        consumed = 1
        end = word.end()
        # Longest contiguous phrase first, never bridge code or sentence boundaries.
        for size in range(min(4, len(words) - index), 0, -1):
            end_word = words[index + size - 1]
            surface = bounded[word.start() : end_word.end()]
            if len(surface) > 96:
                continue
            if any(
                not bounded[words[n].end() : words[n + 1].start()].isspace()
                for n in range(index, index + size - 1)
            ):
                continue
            key = _key(surface)
            matches = [
                entry
                for variant, entry in variants
                if key == variant and (not surface.isupper() or entry["kind"] == "acknowledgement")
            ]
            if matches:
                consumed, end = size, end_word.end()
                break
        surface = bounded[word.start() : end]
        method = "exact"
        if not matches:
            end = word.end()
            surface = word.group()
            if surface.isascii() and surface.islower() and 4 <= len(surface) <= 16:
                matches = [
                    entry
                    for variant, entry in variants
                    if entry["kind"] == "telex"
                    and " " not in variant
                    and len(variant) >= 4
                    and surface[-1] == variant[-1]
                    and surface[-1] in "sfrxj"
                    and _one_edit(surface, variant)
                ]
                method = "one_edit_telex"
        # Ambiguous fuzzy lookup stays ambiguous instead of selecting the nearest winner.
        unique = {entry["id"]: entry for entry in matches}
        for entry in unique.values():
            if len(hints) >= _MAX_HINTS:
                break
            hint = LanguageHint(
                surface,
                tuple(entry["candidates"]),
                entry["id"],
                entry["source"],
                method,
                word.start(),
                end,
            )
            hints.append(hint)
            if len(unique) == 1 and len(hint.candidates) == 1 and entry["retrieval_safe"]:
                replacements.append((hint.start, hint.end, hint.candidates[0]))
        index += consumed
    retrieval = bounded
    for start, end, replacement in reversed(replacements):
        retrieval = retrieval[:start] + replacement + retrieval[end:]
    # A standalone reference is unresolved even when its spelling is understood.
    phrase = _key(bounded.strip().rstrip(".!?…"))
    acknowledgement = any(
        entry["kind"] == "acknowledgement" and phrase in entry["variants"]
        for entry in lexicon["entries"]
    )
    return LanguageAnalysis(
        lexicon["version"],
        tuple(hints),
        retrieval,
        acknowledgement or _BARE_REFERENCE.fullmatch(phrase) is not None,
    )
