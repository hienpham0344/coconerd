"""Bounded administrator commands shared by HTTP and application services."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=100)]
Fact = Annotated[str, Field(min_length=1, max_length=2000)]


class ReviewCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: Identifier
    actor: Identifier
    reason: str = Field(min_length=1, max_length=1000)


class ReviewedSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    topic_id: Identifier
    expected_version: int = Field(ge=1)
    overview: str = Field(default="", max_length=10000)
    proposals: list[Fact] = Field(default_factory=list, max_length=50)
    decisions: list[Fact] = Field(default_factory=list, max_length=50)
    open_questions: list[Fact] = Field(default_factory=list, max_length=50)
    action_items: list[Fact] = Field(default_factory=list, max_length=50)
    source_message_ids: list[Identifier] = Field(max_length=500)

    @model_validator(mode="after")
    def validate_sources(self):
        if len(set(self.source_message_ids)) != len(self.source_message_ids):
            raise ValueError("Source IDs must be unique")
        if not self.source_message_ids and any(
            (self.overview, self.proposals, self.decisions, self.open_questions, self.action_items)
        ):
            raise ValueError("Nonempty memory requires source messages")
        return self

    def memory(self, title: str) -> dict[str, object]:
        return {
            "title": title,
            **self.model_dump(exclude={"expected_version", "source_message_ids"}),
        }


class CorrectMessage(ReviewCommand):
    expected_revision: int = Field(ge=0)
    target_topic_id: Identifier | None
    summaries: list[ReviewedSummary] = Field(max_length=2)


class ResumeTopicSync(ReviewCommand):
    expected_version: int = Field(ge=1)
    discord_reconciled: Literal[True]
    discord_thread_id: Identifier


class RecoverAction(ReviewCommand):
    expected_attempt_count: int = Field(ge=0)
    resolution: Literal["not_performed", "performed"]
    discord_thread_id: Identifier | None = None
    discord_message_id: Identifier | None = None
