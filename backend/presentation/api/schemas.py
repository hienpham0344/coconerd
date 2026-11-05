from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


class DeliveryReceiptResponse(BaseModel):
    discord_id: str = Field(min_length=1, max_length=100)


class MessageAttachment(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    filename: str = Field(min_length=1, max_length=1024)
    url: HttpUrl = Field(max_length=4096)
    content_type: str | None = Field(default=None, max_length=200)
    size: int = Field(ge=0)
    spoiler: bool = False


class MessageIngestRequest(BaseModel):
    guild_id: str = Field(min_length=1, max_length=100)
    channel_id: str = Field(min_length=1, max_length=100)
    message_id: str = Field(min_length=1, max_length=100)
    author_id: str = Field(min_length=1, max_length=100)
    author_name: str = Field(min_length=1, max_length=200)
    content: str = Field(max_length=8000)
    created_at: datetime
    reply_to_message_id: str | None = Field(default=None, max_length=100)
    attachments: list[MessageAttachment] = Field(default_factory=list, max_length=10)

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone offset")
        return value


class MessageIngestResponse(BaseModel):
    message_id: str
    status: str = "accepted"


class ActionClaimRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=100)
    limit: int = Field(default=20, ge=1, le=100)


class ActionCompletionRequest(BaseModel):
    lease_token: str | None = Field(default=None, min_length=1, max_length=36)
    worker_id: str = Field(min_length=1, max_length=100)
    discord_thread_id: str | None = Field(default=None, max_length=100)
    discord_message_id: str | None = Field(default=None, max_length=100)
    previous_discord_thread_id: str | None = Field(default=None, max_length=100)
    discord_channel_id: str | None = Field(default=None, max_length=100)


class ActionFailureRequest(BaseModel):
    lease_token: str | None = Field(default=None, min_length=1, max_length=36)
    worker_id: str = Field(min_length=1, max_length=100)
    error_type: str = Field(min_length=1, max_length=100)
    error_message: str = Field(min_length=1, max_length=1000)
    retryable: bool = True


class ActionResponse(BaseModel):
    lease_token: str | None = Field(default=None, min_length=1, max_length=36)
    model_config = ConfigDict(from_attributes=True)

    action_id: str
    type: str
    topic_id: str
    guild_id: str
    channel_id: str
    payload: dict[str, Any]
    status: str


class GuildSettingsRequest(BaseModel):
    enabled: bool
    allowed_channel_ids: list[str] = Field(max_length=200)
    retention_days: int = Field(default=365, ge=1, le=3650)
    output_channel_id: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def separate_input_and_output_channels(self) -> "GuildSettingsRequest":
        if self.output_channel_id and self.output_channel_id in self.allowed_channel_ids:
            raise ValueError("Output channel must be separate from input channels")
        return self


class ModelConfigRequest(BaseModel):
    provider: Literal["meta"] = "meta"
    model_id: str = Field(min_length=1, max_length=200)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, ge=1, le=32768)


class ModelConfigResponse(ModelConfigRequest):
    scope: str
    guild_id: str | None = None
    enabled: bool = True


class HealthResponse(BaseModel):
    status: str
    database: str
    worker: str
