"""Return values for message use cases."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IngestResult:
    message_id: str
    inserted: bool


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    outcome: str
    topic_id: str | None
    candidate_topic_ids: list[str]
